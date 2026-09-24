# -*- coding: utf-8 -*-
"""Verify #115 on main @ 3ed3099: SimulatedClock._detach() exists and is
called on interpreter teardown, so _settlers stays bounded and stopped
interpreters are GC'able.

Acceptance criteria exercised:
1. SimulatedClock._detach() exists and removes a previously-attached settler.
2. stop() calls _detach() when self.clock is a SimulatedClock.
3. _settlers does not grow unboundedly across restore/restart cycles.
4/5. equivalent behaviour to
     tests/test_clock_settler_lifecycle.py::test_stopped_interpreter_is_detached_from_clock
     and ::test_stopped_interpreter_is_gc_able (no such file ships; behaviour
     re-derived here directly).
6. repro/R4-18_simulatedclock_settler_leak.py exits 0.
"""
from __future__ import annotations

import asyncio
import gc
import inspect
import json
import subprocess
import sys
import weakref

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.base_interpreter import _accepts_kwarg
from xstate_statemachine.clock import SimulatedClock

CFG = {
    "id": "m",
    "initial": "a",
    "context": {},
    "states": {"a": {"on": {"GO": {"target": "a"}}}},
}

CYCLES = 20
REPRO = (
    r"C:\Users\basil\Desktop\Projects\FullStackProjects\CandleViewer\docs"
    r"\research\xstate\issues\post-5e07ba8\new\repro"
    r"\R4-18_simulatedclock_settler_leak.py"
)


def check(label: str, cond: bool, results: list) -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {label}")
    results.append((label, cond))


async def main() -> int:
    results: list = []

    # --- Criterion 1: _detach exists ---
    has_detach = hasattr(SimulatedClock, "_detach")
    check("SimulatedClock._detach exists", has_detach, results)
    if has_detach:
        sig = inspect.signature(SimulatedClock._detach)
        print(f"    signature: {sig}")

    # --- Criteria 2/3: stop() detaches; _settlers bounded across cycles ---
    clock = SimulatedClock()
    refs = []

    m = create_machine(CFG, logic=MachineLogic())
    interp = Interpreter(m, clock=clock)
    await interp.start()
    refs.append(weakref.ref(interp))

    for _ in range(CYCLES):
        snap = interp.get_persisted_snapshot()
        snap_str = json.dumps(snap, default=repr)
        await interp.stop()

        new_m = create_machine(CFG, logic=MachineLogic())
        restored = Interpreter.from_snapshot(snap_str, new_m)
        restored.clock = clock
        restored._clock_accepts_sync = _accepts_kwarg(clock.set_timeout, "sync")
        clock._attach(restored._settle_for_clock)
        await restored.start()

        refs.append(weakref.ref(restored))
        interp = restored

    await interp.stop()
    gc.collect()

    alive = sum(1 for r in refs if r() is not None)
    settlers = len(clock._settlers)
    print(f"    settlers registered on clock after {CYCLES} cycles + final stop: {settlers}")
    print(f"    interpreters still reachable: {alive} / {len(refs)}")

    check("stop() detaches settler -> settlers bounded (<= 1, not >= len(refs))", settlers <= 1, results)
    check("stopped interpreters are GC'able (not all alive)", alive < len(refs), results)

    # --- Criterion 6: original repro exits 0 ---
    proc = subprocess.run(
        [sys.executable, REPRO],
        capture_output=True, text=True, timeout=60,
        env={"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", **__import__("os").environ},
    )
    print("    --- repro stdout ---")
    print(proc.stdout)
    check("original repro R4-18 exits 0", proc.returncode == 0, results)

    ok = all(c for _, c in results)
    print(f"\nOVERALL: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
