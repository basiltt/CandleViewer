"""Verify #144 on main @ cec108b (nested invoke onDone ancestor livelock)."""
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import subprocess
import sys

REPRO = (
    str(_REPO / 'docs/research/xstate/issues/post-3ed3099/new/repro/R5-04_nested-invoke-ondone-ancestor-livelock.py')
)
PY = _xs_main_py()
REPO = str(_XS)

ok = True

r = subprocess.run([PY, REPRO], capture_output=True, text=True, timeout=90)
print("REPRO exit:", r.returncode)
print(r.stdout[-2000:])
if r.returncode != 0:
    ok = False

r2 = subprocess.run(
    [PY, "-m", "pytest", "tests/test_round5_findings.py", "-k",
     "InvokeCycleTerminates", "-q"],
    capture_output=True, text=True, cwd=REPO, timeout=90,
)
print(r2.stdout[-2000:])
if r2.returncode != 0:
    ok = False

sys.exit(0 if ok else 1)
