"""Orchestrator merge step (runs in the main session, never in a sub-agent sandbox).
Usage: python docs/plan/backlog/_tools/merge_ready.py <PR> <KEY> [--design]
Gates, in order: latest verdicts APPROVE (reviews+comments, after last commit) → CI checks pass →
verify_pr.py PASS → [design: Penpot link + embedded PNG] → squash-merge → In Test.
Exit 0 merged, 1 gate failed (reason printed), 2 error."""
import json, os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import publish_board as pb
GH = pb.GH; REPO = pb.REPO
pr, key = sys.argv[1], sys.argv[2]; design = "--design" in sys.argv
def gh(*a):
    r = subprocess.run([GH, *a], capture_output=True, text=True, encoding="utf-8", errors="replace"); return r
def fail(msg): print(f"PR #{pr} {key}: GATE FAIL — {msg}"); sys.exit(1)
d = json.loads(gh("pr", "view", pr, "--json", "state,isDraft,mergeable,commits,reviews,comments,body,statusCheckRollup").stdout)
if d["state"] != "OPEN": fail(f"state={d['state']}")
if d["isDraft"]: fail("draft")
last = max(c["committedDate"] for c in d["commits"])
items = [(r["submittedAt"], r["body"]) for r in d["reviews"]] + [(c["createdAt"], c["body"]) for c in d["comments"]]
verdicts = sorted([(t, b) for t, b in items if re.search(r"VERDICT:\s*(APPROVE|REQUEST_CHANGES)", b or "", re.I)])
after = [(t, b) for t, b in verdicts if t > last]
if not after: fail(f"no VERDICT after last commit {last}")
if any(re.search(r"VERDICT:\s*REQUEST_CHANGES", b, re.I) and t == after[-1][0] for t, b in after): fail("latest verdict is REQUEST_CHANGES")
if not any(re.search(r"VERDICT:\s*APPROVE", b, re.I) for _, b in after): fail("no APPROVE after last commit")
bad = [c for c in d.get("statusCheckRollup") or [] if c.get("conclusion") not in (None, "SUCCESS", "NEUTRAL", "SKIPPED") or c.get("state") in ("FAILURE", "ERROR")]
if bad: fail("failing checks: " + ", ".join(c.get("name") or c.get("context", "?") for c in bad))
r = subprocess.run([sys.executable, os.path.join(HERE, "verify_pr.py"), pr], capture_output=True, text=True, encoding="utf-8", errors="replace")
print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:])
if r.returncode: fail("verify_pr FAIL")
if design:
    body = d["body"] or ""
    if "design.penpot.app" not in body or not re.search(r"!\[[^\]]*\]\([^)]*\.png", body): fail("design evidence missing (Penpot link and/or embedded PNG)")
if d["mergeable"] == "CONFLICTING": fail("CONFLICTING — needs rebase")
m = gh("pr", "merge", pr, "--squash", "--delete-branch")
if m.returncode: fail("merge: " + (m.stderr or m.stdout).strip()[-200:])
sha = json.loads(gh("pr", "view", pr, "--json", "mergeCommit").stdout).get("mergeCommit", {}).get("oid", "")[:7]
subprocess.run([sys.executable, os.path.join(HERE, "set_status.py"), key, "In Test", f"merged {sha}; reviews APPROVE; CI green; verify_pr PASS; QA verification pending"], check=False)
print(f"PR #{pr} {key}: MERGED {sha}")
