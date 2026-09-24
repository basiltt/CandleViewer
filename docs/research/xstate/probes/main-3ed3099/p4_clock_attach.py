"""J-7d: does `from_snapshot(clock=...)` attach the interpreter's settle hook
to the injected SimulatedClock the way the constructor does?

Run: python p4_clock_attach.py
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, r"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine")

from src.xstate_statemachine import (  # noqa: E402
    MachineLogic,
    SimulatedClock,
    SyncInterpreter,
    create_machine,
)

OUT = {}

CFG = {
    "id": "tm",
    "initial": "a",
    "states": {"a": {"after": {1000: "b"}}, "b": {"after": {1000: "c"}}, "c": {}},
}


def settlers(clock):
    return len(getattr(clock, "_settlers", []))


def main() -> None:
    # --- baseline: constructor-injected clock ---
    c1 = SimulatedClock()
    i = SyncInterpreter(create_machine(CFG), clock=c1).start()
    OUT["ctor_settlers"] = settlers(c1)
    c1.increment(1001)
    OUT["ctor_value_after_increment_only"] = i.value
    i.stop()

    # --- from_snapshot(clock=) path ---
    c0 = SimulatedClock()
    a = SyncInterpreter(create_machine(CFG), clock=c0).start()
    snap = a.get_snapshot()
    a.stop()
    c2 = SimulatedClock()
    r = SyncInterpreter.from_snapshot(
        snap, create_machine(CFG), clock=c2, restart_timers=True
    )
    OUT["restored_settlers_before_start"] = settlers(c2)
    r.start()
    OUT["restored_settlers_after_start"] = settlers(c2)
    OUT["restored_clock_pending"] = c2.pending
    c2.increment(1001)
    OUT["restored_value_after_increment_only"] = r.value
    r.tick()
    OUT["restored_value_after_explicit_tick"] = r.value
    # chained: second timer
    c2.increment(1001)
    OUT["restored_value_chain_increment_only"] = r.value
    r.stop()

    # --- from_snapshot WITHOUT clock= (uses RealClock) but restart_timers ---
    c3 = SimulatedClock()
    b = SyncInterpreter(create_machine(CFG), clock=c3).start()
    s3 = b.get_snapshot()
    b.stop()
    q = SyncInterpreter.from_snapshot(
        s3, create_machine(CFG), restart_timers=True
    )
    OUT["no_clock_arg_clock_type"] = type(q.clock).__name__
    q.stop()

    # --- exact-deadline boundary (explains j7's 'a' at total 1000) ---
    c4 = SimulatedClock()
    z = SyncInterpreter(create_machine(CFG), clock=c4).start()
    c4.increment(1000)  # EXACTLY the deadline
    OUT["exact_deadline_value"] = z.value
    c4.increment(1)
    OUT["exact_deadline_plus1_value"] = z.value
    z.stop()

    print(json.dumps(OUT, indent=2, default=str))


if __name__ == "__main__":
    main()
