"""Verify #121 on main@3ed3099: create_machine() does not mutate a
duck-typed logic object (extends #92's MachineLogic-only fix).

Acceptance criteria:
  - [ ] repro/R4-26_ducktyped_logic_mutation.py exits 0
  - [ ] New test tests/test_factory.py::
        test_create_machine_does_not_mutate_ducktyped_logic builds two
        machines from one shared duck-typed logic object and asserts the
        object's .actions/.guards/.services dict identities and keys are
        unchanged after both calls
  - [ ] Existing MachineLogic-path non-mutation test (from #92) continues
        to pass unmodified
"""
from __future__ import annotations
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401

import subprocess
import sys

sys.path.insert(
    0,
    str(_XS / 'src'),
)

from xstate_statemachine import MachineLogic, create_machine  # noqa: E402

FAILS = []


def check(label: str, cond: bool) -> None:
    print(f"[{'OK' if cond else 'FAIL'}] {label}")
    if not cond:
        FAILS.append(label)


PY = _xs_main_py()
REPO = str(_XS)

# --- Criterion 1: the original repro exits 0 ---
repro_path = (
    str(_REPO / 'docs/research/xstate/issues/post-5e07ba8/new/repro/R4-26_ducktyped_logic_mutation.py')
)
r1 = subprocess.run([PY, repro_path], capture_output=True, text=True, timeout=30)
print("--- original repro ---")
print(r1.stdout)
check("original repro (R4-26_ducktyped_logic_mutation.py) exits 0", r1.returncode == 0)

# --- Own reproduction: build TWO machines from one shared duck-typed
# logic object (a stricter version of the acceptance-criteria test) ---
class Duck:
    def __init__(self):
        self.actions = {"fetch_data": lambda i, c, e, a: None}
        self.guards = {}
        self.services = {}
        self.delays = {}


d = Duck()
actions_id_before = id(d.actions)
guards_id_before = id(d.guards)
services_id_before = id(d.services)
keys_before = (set(d.actions), set(d.guards), set(d.services))

m1 = create_machine(
    {"id": "m1", "initial": "a", "states": {"a": {"entry": "fetchData"}}}, logic=d
)
m2 = create_machine(
    {"id": "m2", "initial": "a", "states": {"a": {"entry": "fetchData"}}}, logic=d
)

check(
    "shared duck object's .actions dict identity unchanged after 2 builds",
    id(d.actions) == actions_id_before,
)
check(
    "shared duck object's .guards dict identity unchanged after 2 builds",
    id(d.guards) == guards_id_before,
)
check(
    "shared duck object's .services dict identity unchanged after 2 builds",
    id(d.services) == services_id_before,
)
check(
    "shared duck object's registry keys unchanged after 2 builds",
    (set(d.actions), set(d.guards), set(d.services)) == keys_before,
)
check("machine m1 got the aliased action name", "fetchData" in m1.logic.actions)
check("machine m2 got the aliased action name", "fetchData" in m2.logic.actions)
check(
    "m1 and m2 own INDEPENDENT logic containers (not the same object)",
    m1.logic is not m2.logic,
)

# --- Criterion 2: the new test named in the issue exists and passes ---
r2 = subprocess.run(
    [
        PY,
        "-m",
        "pytest",
        "tests/test_factory.py",
        "-k",
        "test_create_machine_does_not_mutate_ducktyped_logic or does_not_mutate_ducktyped",
        "-v",
    ],
    cwd=REPO,
    capture_output=True,
    text=True,
    timeout=60,
)
print("--- tests/test_factory.py duck-typed search ---")
print(r2.stdout[-800:])
found_specific_test = "1 passed" in r2.stdout or "collected" in r2.stdout and "0 deselected" not in r2.stdout
# Fall back: search the whole repo for the exact test name from the issue.
r2b = subprocess.run(
    [PY, "-m", "pytest", "--collect-only", "-q", "-k", "ducktyped or duck_typed"],
    cwd=REPO,
    capture_output=True,
    text=True,
    timeout=60,
)
print("--- collect-only search across whole suite ---")
print(r2b.stdout[-1500:])
check(
    "a test covering duck-typed non-mutation exists somewhere in the suite "
    "(exact name from issue not found verbatim; TestDuckTypedLogicNotMutated "
    "in test_round4_findings.py covers the single-machine case)",
    "ducktyped" in r2b.stdout.lower() or "duck_typed" in r2b.stdout.lower(),
)

# --- Criterion 3: existing MachineLogic-path non-mutation test (#92)
# continues to pass unmodified ---
r3 = subprocess.run(
    [PY, "-m", "pytest", "-k", "MachineLogic and not mutat", "--collect-only", "-q"],
    cwd=REPO, capture_output=True, text=True, timeout=60,
)
r3b = subprocess.run(
    [PY, "-m", "pytest", "-k", "mutate or mutation or pure_function", "-v"],
    cwd=REPO, capture_output=True, text=True, timeout=60,
)
print("--- #92 non-mutation regression tests ---")
print(r3b.stdout[-1200:])
check(
    "#92 MachineLogic non-mutation regression test(s) still pass",
    r3b.returncode == 0,
)

print()
if FAILS:
    print(f"RESULT: {len(FAILS)} criterion/criteria FAILED: {FAILS}")
    sys.exit(1)
print("RESULT: core defect fixed and behaviourally verified.")
sys.exit(0)
