"""Resync issue bodies + blocked-by edges + Blocked→Ready statuses after a backlog rewrite (idempotent)."""
import json, os, re, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.dirname(__file__))
import publish_board as pb
led = json.load(open(pb.LEDGER_PATH, encoding="utf-8")); tickets = pb.load_tickets(); by = {t["key"]: t for t in tickets}
live = [t for t in tickets if "retired" not in (t.get("labels") or []) and t["key"] in led]
only = set(sys.argv[1:]) if len(sys.argv) > 1 else None
def gh(*a, **k): return subprocess.run([pb.GH, *a], capture_output=True, text=True, encoding="utf-8", **k)
# 1) bodies (only tickets whose body changed: detect via marker or blocked_by diff vs ledger)
n_body = 0
for t in live:
    if only and t["key"] not in only: continue
    changed_deps = set(t.get("blocked_by") or []) != set(led[t["key"]].get("blockedby_done") or []) and t["kind"] != "Epic"
    if "## Agent-delivery adaptations" not in t["body"] and not changed_deps and not re.search(r"ADR-00(1[7-9]|2\d|3\d)", t["body"]): continue
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f: f.write(pb.render_body(t)); p = f.name
    r = gh("issue", "edit", str(led[t["key"]]["number"]), "-R", pb.REPO, "--body-file", p); os.unlink(p)
    if r.returncode: print("body FAIL", t["key"], r.stderr[:120])
    else: n_body += 1
    if n_body % 50 == 0: print("bodies", n_body, flush=True)
print("bodies updated", n_body)
# 2) blocked-by edges: remove stale (epic) edges, add new ones
mut = []
for t in live:
    if t["kind"] == "Epic" or (only and t["key"] not in only): continue
    want = set(b for b in (t.get("blocked_by") or []) if b in led); have = set(led[t["key"]].get("blockedby_done") or [])
    me = led[t["key"]]["node_id"]
    for b in have - want: mut.append(("rm", t["key"], b, 'removeBlockedBy(input:{issueId:"%s",blockingIssueId:"%s"}){issue{id}}' % (me, led[b]["node_id"])))
    for b in want - have: mut.append(("add", t["key"], b, 'addBlockedBy(input:{issueId:"%s",blockingIssueId:"%s"}){issue{id}}' % (me, led[b]["node_id"])))
print("edge mutations", len(mut))
ok_total = 0
for i in range(0, len(mut), 20):
    chunk = mut[i:i+20]
    res = pb.graphql_batch_raw([("m%d" % j, m[3]) for j, m in enumerate(chunk)], aliases_per_call=20)
    for j, m in enumerate(chunk):
        if res.get("m%d" % j):
            ok_total += 1; done = set(led[m[1]].get("blockedby_done") or [])
            (done.discard if m[0] == "rm" else done.add)(m[2]); led[m[1]]["blockedby_done"] = sorted(done)
    pb.save_ledger(led); time.sleep(0.3)
print("edges applied", ok_total)
# 3) statuses: Blocked -> Ready for every live ticket (agents re-evaluate blockers themselves)
q = '{node(id:"%s"){... on ProjectV2{items(first:100%s){pageInfo{hasNextPage endCursor} nodes{id fieldValueByName(name:"Status"){... on ProjectV2ItemFieldSingleSelectValue{name}}}}}}}'
after = ""; blocked = []
while True:
    r = gh("api", "graphql", "-f", "query=" + q % (pb.PROJECT_ID, after)); d = json.loads(r.stdout)["data"]["node"]["items"]
    blocked += [n["id"] for n in d["nodes"] if (n["fieldValueByName"] or {}).get("name") == "Blocked"]
    if not d["pageInfo"]["hasNextPage"]: break
    after = ',after:"%s"' % d["pageInfo"]["endCursor"]
print("blocked items", len(blocked))
muts = [("s%d" % i, pb._mk_sso(item, pb.FIELD_IDS["Status"], pb.STATUS_OPTS["Ready"])) for i, item in enumerate(blocked)]
res = pb.graphql_batch_raw(muts, aliases_per_call=20) if muts else {}
print("reset to Ready", sum(1 for v in res.values() if v))
