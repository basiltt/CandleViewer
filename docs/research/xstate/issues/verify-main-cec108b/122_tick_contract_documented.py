"""Verify #122 on main@cec108b: SyncInterpreter.tick() contract is documented
(drains what is DUE, does not advance time) -- per CHANGELOG this is a
DOC clarification, not a "sync tick chains through already-due deadlines
armed by wall-clock passage during a single tick() call" behavior change.

Checks:
- tick.__doc__ documents the contract (does NOT advance; needs one tick()
  per rung for real delays; SimulatedClock+increment() settles chains).
- A same-tick chain of *zero-delay* deadlines (all due at the moment of
  entry, not merely "wall clock passed while tick() was running") drains
  fully in one tick() -- the acceptance-criteria test shape
  (test_sync_tick_drains_chained_after_deadlines equivalent, R4-27 ladder
  is 50/50/50ms with a real sleep(0.25) BEFORE tick(), which is a
  different, stronger claim -- see below).
- The original repro (real RealClock, sleep(0.25) before a single tick())
  is re-run verbatim for comparison.
"""
from __future__ import annotations
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401

import asyncio
import sys
import time

sys.path.insert(
    0, str(_XS / 'src')
)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

failures = []


def check(name, cond):
    print(f"[{'OK' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


def main() -> int:
    doc = SyncInterpreter.tick.__doc__ or ""
    check("tick.__doc__ documents 'does NOT advance'", "does NOT advance" in doc)
    check("tick.__doc__ mentions SimulatedClock", "SimulatedClock" in doc)

    # Acceptance-criteria shape: zero-delay chain, all due at entry -> one tick.
    cfg0 = {
        "id": "o",
        "initial": "a",
        "states": {
            "a": {"after": {0: "b"}},
            "b": {"after": {0: "c"}},
            "c": {"after": {0: "d"}},
            "d": {},
        },
    }
    s0 = SyncInterpreter(create_machine(cfg0, logic=MachineLogic())).start()
    s0.tick()
    check("zero-delay chain drains fully in one tick()", s0.value == "d")
    s0.stop()

    # Documented SimulatedClock path: increment() settles a real-delay ladder.
    cfg1 = {
        "id": "o",
        "initial": "s",
        "states": {
            "s": {"after": {50: "a"}},
            "a": {"after": {50: "r"}},
            "r": {"after": {50: "e"}},
            "e": {},
        },
    }
    clock = SimulatedClock()
    i = SyncInterpreter(create_machine(cfg1, logic=MachineLogic()), clock=clock).start()
    clock.increment(250)
    check("SimulatedClock.increment(250) settles the whole ladder", {"o.e"} == i.current_state_ids)
    i.stop()

    # Original R4-27 repro: RealClock, real sleep(0.25), single tick() call.
    # This is a STRONGER claim than the doc contract promises (the doc says
    # each real-delay rung needs its own tick() call after that rung's delay
    # has passed) -- included for completeness / stale-script judgement.
    def sync_run():
        s = SyncInterpreter(create_machine(cfg1, logic=MachineLogic())).start()
        time.sleep(0.25)
        s.tick()
        result = sorted(s.current_state_ids)
        s.stop()
        return result

    async def async_run():
        i = await Interpreter(create_machine(cfg1, logic=MachineLogic())).start()
        await asyncio.sleep(0.25)
        result = sorted(i.current_state_ids)
        await i.stop()
        return result

    sync_result = sync_run()
    async_result = asyncio.run(async_run())
    print(f"original repro: sync(1 tick after sleep)={sync_result} async(settle)={async_result}")
    repro_matches_async = sync_result == async_result
    print(
        f"[INFO] original R4-27 repro (RealClock + single tick after sleep) "
        f"{'PASSES' if repro_matches_async else 'still returns exit 1'} "
        f"-- NOT an acceptance criterion; the CHANGELOG/docstring only "
        f"promise 'one tick() per rung' for RealClock, and recommend "
        f"SimulatedClock for deterministic chain settling."
    )

    return 0 if not failures else 1


if __name__ == "__main__":
    rc = main()
    print(f"\nRESULT: {'PASS' if rc == 0 else 'FAIL'} ({len(failures)} failing)")
    sys.exit(rc)
