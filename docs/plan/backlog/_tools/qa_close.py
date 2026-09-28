"""Deterministic QA closer. Usage: python docs/plan/backlog/_tools/qa_close.py <KEY> <issue#>
Closes the ticket as Done ONLY if the latest 'QA verification' comment on the issue says VERDICT: PASS
(and no later comment says FAIL). Exit 0 closed, 1 not closed (reason printed)."""
import json, os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import publish_board as pb
key, issue = sys.argv[1], sys.argv[2]
r = subprocess.run([pb.GH, "issue", "view", issue, "-R", pb.REPO, "--json", "comments,state"], capture_output=True, text=True, encoding="utf-8")
d = json.loads(r.stdout)
verdicts = [(c["createdAt"], m.group(1).upper()) for c in d["comments"]
            for m in [re.search(r"QA (?:re-)?verification[^\n]*VERDICT:\s*(PASS|FAIL)", c["body"] or "", re.I)] if m]
if not verdicts:
    print(f"{key} #{issue}: NOT CLOSED — no QA verification verdict comment"); sys.exit(1)
latest = sorted(verdicts)[-1][1]
if latest != "PASS":
    print(f"{key} #{issue}: NOT CLOSED — latest QA verdict is {latest}"); sys.exit(1)
subprocess.run([sys.executable, os.path.join(HERE, "set_status.py"), key, "Done",
                "QA verification PASS (independent QA agent; AC→evidence table above). Closed by the QA role per C-10.4 / C-10.1 v1.1.0."], check=True)
if d["state"] != "CLOSED":
    subprocess.run([pb.GH, "issue", "close", issue, "-R", pb.REPO, "--reason", "completed"], check=True)
print(f"{key} #{issue}: DONE")
