"""Verify #136 on 3ed3099: aliased-cycle config raises typed
InvalidConfigError instead of RecursionError.

Acceptance criteria (from gh issue #136):
1. StateNode.__init__ (or call site) detects a cyclic config via
   visited-id tracking and raises InvalidConfigError.
2. InvalidConfigError message names the state id/path where the cycle
   was detected.
3. tests/test_validation.py (or equivalent, here
   test_round4_findings.py) has a test asserting InvalidConfigError
   (not RecursionError) for an aliased-cycle dict.
4. repro/R4-38_config_cycle_recursionerror.py exits 0.

Exits 0 only if all criteria pass.
"""
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(
    str(_XS)
)
PY = _xs_main_py()
REPRO = Path(
    str(_REPO / 'docs/research/xstate/issues/post-5e07ba8/new/repro/R4-38_config_cycle_recursionerror.py')
)

sys.path.insert(0, str(REPO / "src"))


def check(label, cond):
    print(f"[{'OK' if cond else 'FAIL'}] {label}")
    return cond


def main() -> int:
    ok = True

    from xstate_statemachine import MachineLogic, create_machine
    from xstate_statemachine.exceptions import InvalidConfigError

    a: dict = {"initial": "x", "states": {}}
    a["states"]["x"] = a
    cfg = {"id": "m", "initial": "a", "states": {"a": a}}

    raised_typed = False
    raised_recursion = False
    msg = ""
    try:
        create_machine(cfg, logic=MachineLogic())
    except InvalidConfigError as exc:
        raised_typed = True
        msg = str(exc)
    except RecursionError:
        raised_recursion = True

    ok &= check("1. Cyclic config raises InvalidConfigError (not RecursionError)", raised_typed and not raised_recursion)
    ok &= check(
        "2. Error message names the cyclic state ('m.a.x' path)",
        "m.a.x" in msg or ("cycle" in msg.lower() and "m.a" in msg),
    )

    tests = (REPO / "tests/test_round4_findings.py").read_text(encoding="utf-8")
    has_test = "test_cyclic_config_is_typed" in tests and "InvalidConfigError" in tests
    ok &= check("3. Regression test exists (test_cyclic_config_is_typed)", has_test)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    result = subprocess.run([PY, str(REPRO)], capture_output=True, text=True, env=env, cwd=str(REPO))
    print("--- repro stdout ---")
    print(result.stdout)
    ok &= check(f"4. repro exit=={result.returncode} == 0", result.returncode == 0)

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
