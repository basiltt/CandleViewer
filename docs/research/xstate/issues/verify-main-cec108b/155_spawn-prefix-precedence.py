"""Verify #155 on cec108b: a user action named spawn_* takes precedence over
the built-in spawn-actor path; unregistered spawn_* names still spawn.
Exit 0 only if all criteria pass."""
import json
import sys

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

CFG = {
    "id": "m", "initial": "a", "context": {},
    "states": {"a": {"on": {"GO": {"target": "b", "actions": ["spawn_place_order"]}}}, "b": {}},
}


def main() -> int:
    results = []

    called = []
    s = SyncInterpreter(
        create_machine(CFG, logic=MachineLogic(actions={"spawn_place_order": lambda *a: called.append(1)}))
    ).start()
    s.send("GO")
    results.append(("user action ran instead of spawn", called == [1]))
    results.append(("transition still occurred", s.value == "b"))

    class P:
        def spawn_place_order(self, i, c, e, a):
            c["ran"] = True

    m = create_machine(json.loads(json.dumps(CFG)), logic_providers=[P()])
    results.append(("auto-discovered as action", "spawn_place_order" in m.logic.actions))
    results.append(("not mistakenly registered as service", "place_order" not in m.logic.services))

    # unregistered spawn_* still spawns
    child = {"id": "kid", "initial": "x", "states": {"x": {}}}
    cfg2 = {"id": "p", "initial": "a", "states": {"a": {"entry": ["spawn_kid"]}}}
    s2 = SyncInterpreter(
        create_machine(cfg2, logic=MachineLogic(services={"kid": create_machine(child)}))
    ).start()
    spawned = any(k.startswith("p:") for k in s2._actors)
    s2.stop()
    results.append(("unregistered spawn_* still spawns", spawned))

    print("RESULTS:")
    ok = True
    for label, passed in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
        ok = ok and passed
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
