"""Verify #146 on main @ cec108b (hostile snapshot fields typed)."""
import subprocess
import sys

REPRO = (
    "C:/Users/basil/Desktop/Projects/FullStackProjects/CandleViewer/docs/"
    "research/xstate/issues/post-3ed3099/new/repro/"
    "R5-03_from_snapshot_untyped_errors.py"
)
PY = "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/.venv-main/Scripts/python"
REPO = "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine"

ok = True

r = subprocess.run([PY, REPRO], capture_output=True, text=True, timeout=90)
print("REPRO exit:", r.returncode)
print(r.stdout[-2000:])
if r.returncode != 0:
    ok = False

r2 = subprocess.run(
    [PY, "-m", "pytest", "tests/test_round5_findings.py", "-k",
     "HostileSnapshotFieldsAreTyped", "-q"],
    capture_output=True, text=True, cwd=REPO, timeout=90,
)
print(r2.stdout[-2000:])
if r2.returncode != 0:
    ok = False

sys.exit(0 if ok else 1)
