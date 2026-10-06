"""Verify #138 on 3ed3099: provenance survives copy.deepcopy and pickle.

Acceptance criteria (from gh issue #138):
1. Either Event.__deepcopy__/__reduce__ is implemented so provenance
   survives copy.deepcopy and pickle, OR docstrings document the loss
   with persist_event/restore_event pointed to as the alternative.
   (Verify which route was taken and check it accordingly.)
2. A test pins down the chosen behavior.
3. repro/R4-40_provenance_deepcopy_pickle.py exits 0 (if fixed route
   taken) or is updated to assert the documented behavior (if doc-only
   route taken).

Exits 0 only if all criteria pass for whichever route was actually
implemented.
"""
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import copy
import os
import pickle
import subprocess
import sys
from pathlib import Path

REPO = Path(
    str(_XS)
)
PY = _xs_main_py()
REPRO = Path(
    str(_REPO / 'docs/research/xstate/issues/post-5e07ba8/new/repro/R4-40_provenance_deepcopy_pickle.py')
)

sys.path.insert(0, str(REPO / "src"))


def check(label, cond):
    print(f"[{'OK' if cond else 'FAIL'}] {label}")
    return cond


def main() -> int:
    ok = True

    from xstate_statemachine.events import Event, is_system_event, system_event

    ev = system_event("xstate.init")
    original_ok = is_system_event(ev)
    copy_ok = is_system_event(copy.copy(ev))
    deepcopy_ok = is_system_event(copy.deepcopy(ev))
    pickle_ok = is_system_event(pickle.loads(pickle.dumps(ev)))
    # anti-forgery: a plain user event must NOT read as a system event
    # after the same round-trips (guards against a naive fix that makes
    # __reduce__ always mark provenance as engine-owned).
    user_ev = Event("USER_EVENT")
    user_stays_user = not is_system_event(copy.deepcopy(user_ev)) and not is_system_event(
        pickle.loads(pickle.dumps(user_ev))
    )

    fixed_route = original_ok and copy_ok and deepcopy_ok and pickle_ok

    ok &= check(
        "1. Provenance survives copy.copy, copy.deepcopy, and pickle (fixed route implemented)",
        fixed_route,
    )
    ok &= check(
        "1b. Anti-forgery preserved: plain user Event does not become a system event via deepcopy/pickle",
        user_stays_user,
    )

    tests = (REPO / "tests/test_round4_findings.py").read_text(encoding="utf-8")
    has_test = "test_provenance_survives_deepcopy_and_pickle" in tests
    ok &= check("2. Test pins down the chosen (fixed) behavior", has_test)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    result = subprocess.run([PY, str(REPRO)], capture_output=True, text=True, env=env, cwd=str(REPO))
    print("--- repro stdout ---")
    print(result.stdout)
    ok &= check(f"3. repro exit=={result.returncode} == 0", result.returncode == 0)

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
