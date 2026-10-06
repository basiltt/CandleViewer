"""Verify #124 on main@3ed3099: Interpreter.start() and
SyncInterpreter.start() emit the same on_transition behavior at index 0
(both emit the synthetic init record, or neither does).

Acceptance criteria:
  - [ ] Interpreter.start() and SyncInterpreter.start() emit the same
        on_transition behavior at index 0 (both emit the synthetic init
        record, or neither does).
  - [ ] A test named test_sync_async_init_transition_hook_parity (or
        equivalent) exists under tests/.
  - [ ] repro/R4-29_sync_start_synthetic_init_hook.py exits 0 once fixed.
"""
from __future__ import annotations
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401

import asyncio
import subprocess
import sys

sys.path.insert(
    0,
    str(_XS / 'src'),
)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

FAILS = []


def check(label: str, cond: bool) -> None:
    print(f"[{'OK' if cond else 'FAIL'}] {label}")
    if not cond:
        FAILS.append(label)


PY = _xs_main_py()
REPO = str(_XS)

CFG = {
    "id": "h",
    "initial": "a",
    "states": {"a": {"on": {"GO": "b"}}, "b": {}},
}


def make_spy(store):
    class S(PluginBase):
        def on_transition(self, i, src, tgt, tr):
            store.append(tr.event)

    return S()


a: list = []
s = SyncInterpreter(create_machine(CFG)).use(make_spy(a))
s.start()
s.send("GO")
s.stop()


async def async_main():
    b: list = []
    i = Interpreter(create_machine(CFG)).use(make_spy(b))
    await i.start()
    await i.send("GO", wait=True)
    await i.stop()
    return b


b = asyncio.run(async_main())

check("sync and async on_transition traces are identical", a == b)
check(
    "index 0 IS the synthetic init record on both engines",
    len(a) > 0 and a[0] == "___xstate_statemachine_init___",
)
check("async engine also emits the synthetic init record at index 0", len(b) > 0 and b[0] == a[0])

# --- both-neither invariant, tested against a machine with an entry
# action too (ensure init record isn't an artifact of the simple case) ---
CFG2 = {
    "id": "h2",
    "initial": "x",
    "states": {"x": {"entry": [], "on": {"GO": "y"}}, "y": {}},
}
a2: list = []
s2 = SyncInterpreter(create_machine(CFG2)).use(make_spy(a2))
s2.start()
s2.stop()


async def async_main2():
    b2: list = []
    i2 = Interpreter(create_machine(CFG2)).use(make_spy(b2))
    await i2.start()
    await i2.stop()
    return b2


b2 = asyncio.run(async_main2())
check(
    "second shape: sync and async agree on whether init record is emitted "
    "(both-or-neither invariant)",
    bool(a2) == bool(b2) and a2 == b2,
)

# --- Criterion 2: dedicated test exists and passes ---
r = subprocess.run(
    [PY, "-m", "pytest", "tests/test_round4_findings.py", "-k", "HookParity", "-v"],
    cwd=REPO, capture_output=True, text=True, timeout=60,
)
check(
    "dedicated hook-parity test passes (test_init_on_transition_record_on_both)",
    r.returncode == 0 and "test_init_on_transition_record_on_both PASSED" in r.stdout,
)
print(r.stdout[-500:])

# --- Criterion 3: original repro exits 0 ---
repro_path = (
    str(_REPO / 'docs/research/xstate/issues/post-5e07ba8/new/repro/R4-29_sync_start_synthetic_init_hook.py')
)
r2 = subprocess.run([PY, repro_path], capture_output=True, text=True, timeout=30)
print("--- original repro ---")
print(r2.stdout)
check("original repro (R4-29_sync_start_synthetic_init_hook.py) exits 0", r2.returncode == 0)

print()
if FAILS:
    print(f"RESULT: {len(FAILS)} criterion/criteria FAILED: {FAILS}")
    sys.exit(1)
print("RESULT: all #124 acceptance criteria satisfied.")
sys.exit(0)
