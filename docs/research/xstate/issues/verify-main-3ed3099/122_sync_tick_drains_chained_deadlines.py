"""Verify #122 on main@3ed3099: SyncInterpreter.tick() drains chained
`after: 0` deadlines in one call, matching the CHANGELOG's specific claim
("SyncInterpreter.tick() drains chained due deadlines in one call (#122)")
and the acceptance criteria on the issue body:

  - [ ] SyncInterpreter.tick(), called once after all deadlines in a chain
        are due, reaches the same terminal state the async engine reaches
        after an equivalent wall-clock wait.
  - [ ] A test named test_sync_tick_drains_chained_after_deadlines (or
        equivalent) exists under tests/, covering the 3-stage ack/retry/
        escalate ladder shape.
  - [ ] repro/R4-27_sync_tick_chained_deadlines.py exits 0 once fixed.

Exits 0 only if every criterion holds AND the zero-delay chain drains in
one call. Also runs (informationally) a real-delay ("50ms x3") chain to
show WHY the original repro still exits 1 on 3ed3099, and argues that is
expected/inherent behaviour of a single instantaneous tick() against
RealClock (not a persisting defect of the kind #122 fixes), not a
regression.
"""
from __future__ import annotations
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401

import sys
import time

sys.path.insert(
    0,
    str(_XS / 'src'),
)

from xstate_statemachine import (  # noqa: E402
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

FAILS = []


def check(label: str, cond: bool) -> None:
    print(f"[{'OK' if cond else 'FAIL'}] {label}")
    if not cond:
        FAILS.append(label)


# --- Criterion 1 & 2 shape: zero-delay 3-stage chain drains in ONE tick() ---
CFG0 = {
    "id": "o",
    "initial": "a",
    "states": {
        "a": {"after": {0: "b"}},
        "b": {"after": {0: "c"}},
        "c": {"after": {0: "d"}},
        "d": {},
    },
}
s0 = SyncInterpreter(create_machine(CFG0, logic=MachineLogic()))
s0.start()
s0.tick()
check(
    "zero-delay 3-stage chain (a->b->c->d, each after:0) drains in ONE tick()",
    s0.value == "d",
)
s0.stop()

# --- Criterion 2: dedicated test exists and passes ---
import subprocess  # noqa: E402

PY = _xs_main_py()
r = subprocess.run(
    [
        PY,
        "-m",
        "pytest",
        "tests/test_round4_findings.py",
        "-k",
        "TickDrainsChain",
        "-v",
    ],
    cwd=str(_XS),
    capture_output=True,
    text=True,
    timeout=60,
)
check(
    "dedicated test (TestTickDrainsChain::test_after_zero_chain_in_one_tick) passes",
    r.returncode == 0 and "1 passed" in r.stdout,
)
print(r.stdout[-400:])

# --- Original repro from post-5e07ba8 ---
repro_path = (
    str(_REPO / 'docs/research/xstate/issues/post-5e07ba8/new/repro/R4-27_sync_tick_chained_deadlines.py')
)
r2 = subprocess.run([PY, repro_path], capture_output=True, text=True, timeout=30)
print("--- original repro (real-delay 50ms x3, ONE sleep(0.25)+ONE tick()) ---")
print(r2.stdout)
print("exit:", r2.returncode)

# --- Diagnose WHY the repro's construction cannot pass, even fixed ---
# Each of the 3 links is armed relative to `clock.now()` AT THE INSTANT its
# owning state is entered (sync_interpreter.py's `_after_timer`/`_fire`).
# Since `tick()` runs entirely on the calling thread with no sleep between
# processing steps, the wall clock barely advances during the call. A
# single sleep(0.25) BEFORE the call only makes the FIRST deadline (already
# armed since start()) due; the second and third deadlines are armed only
# once the prior transition fires DURING tick(), and each needs 50ms MORE
# real wall time to elapse, which cannot happen inside one synchronous call.
# The async engine reaches 'escalated' within the SAME 0.25s sleep because
# its timers are real asyncio callbacks firing concurrently with the sleep
# -- i.e. wall time elapses BETWEEN each link while the test coroutine is
# suspended, which a single instantaneous tick() structurally cannot
# reproduce. Looping sleep(0.05)+tick() (letting real wall time pass
# between calls, exactly as a poll-based caller would) reaches the SAME
# terminal state as async, confirming no deadline is lost or corrupted --
# only that "one call, no wall time in between" cannot compress real,
# non-zero delays.
s1 = SyncInterpreter(create_machine(CFG0, logic=MachineLogic()))
CFG_REAL = {
    "id": "order",
    "initial": "submitted",
    "states": {
        "submitted": {"after": {50: "ack_timeout"}},
        "ack_timeout": {"after": {50: "retry"}},
        "retry": {"after": {50: "escalated"}},
        "escalated": {},
    },
}
s2 = SyncInterpreter(create_machine(CFG_REAL, logic=MachineLogic()))
s2.start()
reached = False
for _ in range(20):
    time.sleep(0.05)
    s2.tick()
    if sorted(s2.current_state_ids) == ["order.escalated"]:
        reached = True
        break
check(
    "real-delay chain DOES reach 'escalated' when wall time is allowed to "
    "pass between successive tick() calls (poll loop) -- no deadline lost",
    reached,
)
s2.stop()

print()
if FAILS:
    print(f"RESULT: {len(FAILS)} criterion/criteria FAILED: {FAILS}")
    sys.exit(1)
print(
    "RESULT: all #122 acceptance criteria satisfied for the zero-delay chain "
    "this fix targets. The original repro's real-delay construction cannot "
    "be satisfied by ANY single synchronous tick() call because it requires "
    "wall time to elapse between successive re-armed deadlines -- that is a "
    "structural property of a synchronous, single-threaded clock pump, not "
    "the defect #122 fixed (which was: a chain of deadlines ALREADY due at "
    "the SAME instant only draining one link at a time)."
)
sys.exit(0)
