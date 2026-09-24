"""Verify #154 on cec108b: sync restore attaches the SimulatedClock so
increment() alone fires an `after` transition, both restore paths (snapshot
object w/ restart_timers, and persisted-inbox / from_snapshot(clock=)).
Exit 0 only if all criteria pass."""
import sys

from xstate_statemachine import MachineLogic, SimulatedClock, SyncInterpreter, create_machine

CFG = {
    "id": "tm", "initial": "idle", "context": {"late": 0},
    "states": {
        "idle": {"on": {"GO": "armed"}},
        "armed": {"after": {"50": {"target": "idle", "actions": ["late"]}}},
    },
}


def mk():
    return create_machine(
        CFG,
        logic=MachineLogic(actions={"late": lambda i, c, e, a: c.__setitem__("late", c["late"] + 1)}),
    )


def main() -> int:
    results = []

    # restart_timers path
    src = SyncInterpreter(mk(), clock=SimulatedClock()).start()
    src.send("GO")
    snap = src.get_snapshot()
    clock = SimulatedClock()
    r = SyncInterpreter.from_snapshot(snap, mk(), clock=clock, restart_timers=True).start()
    results.append(("restart_timers: 1 settler attached", len(clock._settlers) == 1))
    clock.increment(200)
    results.append(("restart_timers: fires via increment() alone", r.context["late"] == 1))

    # double-start does not double-attach
    r.start()
    results.append(("double start(): still 1 settler", len(clock._settlers) == 1))

    # persisted-inbox path
    import json
    cfg2 = {"id": "q", "initial": "a",
            "states": {"a": {"on": {"GO": "b"}}, "b": {"after": {"10": "c"}}, "c": {}}}
    blob = {"version": 1, "status": "running", "context": {}, "state_ids": ["q.a"],
            "configuration": ["q", "q.a"],
            "pending_events": [{"kind": "event", "type": "GO", "payload": {}}]}
    clock2 = SimulatedClock()
    r2 = SyncInterpreter.from_snapshot(json.dumps(blob), create_machine(cfg2), clock=clock2).start()
    results.append(("persisted-inbox path: 1 settler attached", len(clock2._settlers) == 1))
    clock2.increment(20)
    results.append(("persisted-inbox path: fires via increment()", r2.value == "c"))

    print("RESULTS:")
    ok = True
    for label, passed in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
        ok = ok and passed
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
