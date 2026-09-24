# -*- coding: utf-8 -*-
"""Verify #117 on main @ 3ed3099: from_snapshot(snapshot_str, machine, *,
clock=None, ...) accepts and forwards a caller-supplied clock, on both
Interpreter and SyncInterpreter.

Acceptance criteria exercised:
1. from_snapshot accepts a `clock` keyword argument on both Interpreter and
   SyncInterpreter.
2. Passing clock=some_simulated_clock -> restored.clock is some_simulated_clock.
3. Omitting clock= preserves current default behaviour (no regression).
4/5. Equivalent to tests/test_persistence_clock.py::
     test_from_snapshot_accepts_clock_param and
     test_from_snapshot_default_clock_unchanged (re-derived here).
6. repro/R4-22_from_snapshot_no_clock_param.py exits 0.
"""
from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys

from xstate_statemachine import Interpreter, SyncInterpreter, create_machine
from xstate_statemachine.clock import RealClock, SimulatedClock

CFG = {
    "id": "m",
    "initial": "a",
    "context": {},
    "states": {"a": {"on": {"GO": {"target": "a"}}}},
}

REPRO = (
    r"C:\Users\basil\Desktop\Projects\FullStackProjects\CandleViewer\docs"
    r"\research\xstate\issues\post-5e07ba8\new\repro"
    r"\R4-22_from_snapshot_no_clock_param.py"
)


def check(label: str, cond: bool, results: list) -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {label}")
    results.append((label, cond))


def main() -> int:
    results: list = []

    sig_async = inspect.signature(Interpreter.from_snapshot)
    sig_sync = inspect.signature(SyncInterpreter.from_snapshot)
    print(f"    Interpreter.from_snapshot sig: {sig_async}")
    print(f"    SyncInterpreter.from_snapshot sig: {sig_sync}")

    check("Interpreter.from_snapshot has 'clock' kwarg", "clock" in sig_async.parameters, results)
    check("SyncInterpreter.from_snapshot has 'clock' kwarg", "clock" in sig_sync.parameters, results)

    # Async engine: clock forwarded
    m = create_machine(CFG)
    clock = SimulatedClock()
    interp = Interpreter(m, clock=clock)
    snap = interp.get_persisted_snapshot()
    snap_str = json.dumps(snap, default=str)

    m2 = create_machine(CFG)
    restored = Interpreter.from_snapshot(snap_str, m2, clock=clock)
    check("Interpreter: restored.clock is the passed-in clock", restored.clock is clock, results)

    m3 = create_machine(CFG)
    restored_default = Interpreter.from_snapshot(snap_str, m3)
    check(
        "Interpreter: omitting clock= keeps default RealClock behaviour",
        isinstance(restored_default.clock, RealClock),
        results,
    )

    # Sync engine: clock forwarded
    sm = create_machine(CFG)
    sclock = SimulatedClock()
    sinterp = SyncInterpreter(sm, clock=sclock)
    ssnap = sinterp.get_persisted_snapshot()
    ssnap_str = json.dumps(ssnap, default=str)

    sm2 = create_machine(CFG)
    srestored = SyncInterpreter.from_snapshot(ssnap_str, sm2, clock=sclock)
    check("SyncInterpreter: restored.clock is the passed-in clock", srestored.clock is sclock, results)

    sm3 = create_machine(CFG)
    srestored_default = SyncInterpreter.from_snapshot(ssnap_str, sm3)
    check(
        "SyncInterpreter: omitting clock= keeps default RealClock behaviour",
        isinstance(srestored_default.clock, RealClock),
        results,
    )

    proc = subprocess.run(
        [sys.executable, REPRO],
        capture_output=True, text=True, timeout=60,
        env={"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", **os.environ},
    )
    print("    --- repro stdout ---")
    print(proc.stdout)
    check("original repro R4-22 exits 0", proc.returncode == 0, results)

    ok = all(c for _, c in results)
    print(f"\nOVERALL: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
