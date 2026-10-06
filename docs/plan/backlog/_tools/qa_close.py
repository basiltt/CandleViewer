"""Deterministic QA closer. Usage: python docs/plan/backlog/_tools/qa_close.py <KEY> <issue#>
Closes the ticket as Done ONLY if the latest 'QA verification' comment on the issue says VERDICT: PASS
(and no later comment says FAIL) AND done_gate.py (DoD evidence, #1859) passes.
Owner override: --force-owner "<reason>" skips the done-gate; allowed only when `gh api user` is the repo
owner (basiltt); the reason is logged in the close comment.
Exit 0 closed, 1 not closed (reason printed)."""
import json, os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import publish_board as pb
OWNER = "basiltt"
argv = sys.argv[1:]
force = None
if "--force-owner" in argv:
    i = argv.index("--force-owner")
    force = " ".join(argv[i + 1:]).strip()
    argv = argv[:i]
    if not force:
        print("NOT CLOSED — --force-owner requires a reason"); sys.exit(1)
    who = subprocess.run([pb.GH, "api", "user", "--jq", ".login"], capture_output=True, text=True, encoding="utf-8", check=False)
    if who.returncode or who.stdout.strip() != OWNER:
        print(f"NOT CLOSED — --force-owner refused: caller {who.stdout.strip() or '?'!r} is not the owner {OWNER!r}"); sys.exit(1)
key, issue = argv[0], argv[1]
r = subprocess.run([pb.GH, "issue", "view", issue, "-R", pb.REPO, "--json", "comments,state"], capture_output=True, text=True, encoding="utf-8")
d = json.loads(r.stdout)
verdicts = [(c["createdAt"], m.group(1).upper()) for c in d["comments"]
            for m in [re.search(r"QA (?:re-)?verification[^\n]*VERDICT:\s*(PASS|FAIL)", c["body"] or "", re.I)] if m]
if not verdicts:
    print(f"{key} #{issue}: NOT CLOSED — no QA verification verdict comment"); sys.exit(1)
latest = sorted(verdicts)[-1][1]
if latest != "PASS":
    print(f"{key} #{issue}: NOT CLOSED — latest QA verdict is {latest}"); sys.exit(1)
note = "QA verification PASS (independent QA agent; AC→evidence table above). Closed by the QA role per C-10.4 / C-10.1 v1.1.0."
if force:
    print(f"{key} #{issue}: done-gate SKIPPED by --force-owner: {force}")
    note += f" Done-gate OVERRIDDEN by owner (--force-owner): {force}"
else:
    g = subprocess.run([sys.executable, os.path.join(HERE, "done_gate.py"), key, issue], capture_output=True, text=True, encoding="utf-8")
    if g.returncode:
        print(f"{key} #{issue}: NOT CLOSED — done-gate failed (DoD evidence missing)\n{g.stdout}{g.stderr}"); sys.exit(1)
    note += " Done-gate (DoD evidence) PASS."
subprocess.run([sys.executable, os.path.join(HERE, "set_status.py"), key, "Done", note], check=True)
if d["state"] != "CLOSED":
    subprocess.run([pb.GH, "issue", "close", issue, "-R", pb.REPO, "--reason", "completed"], check=True)
print(f"{key} #{issue}: DONE")
