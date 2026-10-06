"""Verify #142 on main @ cec108b.

Runs original R5-01 repro (expect exit 0) and the pytest evidence for the
new `_configuration_is_legal` predicate. Exits 0 only if all pass.
"""
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import subprocess
import sys

REPRO = (
    str(_REPO / 'docs/research/xstate/issues/post-3ed3099/new/repro/R5-01_parallel-tear-passes-midstep-guard.py')
)
PY = _xs_main_py()
REPO = str(_XS)

ok = True

r = subprocess.run([PY, REPRO], capture_output=True, text=True, timeout=90)
print("REPRO exit:", r.returncode)
print(r.stdout[-1500:])
if r.returncode != 0:
    ok = False

r2 = subprocess.run(
    [PY, "-m", "pytest", "tests/test_round5_findings.py", "-k",
     "ConfigurationLegality", "-q"],
    capture_output=True, text=True, cwd=REPO, timeout=90,
)
print(r2.stdout[-2000:])
if r2.returncode != 0:
    ok = False

sys.exit(0 if ok else 1)
