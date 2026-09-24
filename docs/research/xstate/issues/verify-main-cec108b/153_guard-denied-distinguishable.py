"""Verify #153 on cec108b: guard-denied is distinguishable from an undeclared
event via Receipt.denied and on_unhandled_event disposition 'guard_denied'.
Exit 0 only if all criteria pass."""
import sys

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine
from xstate_statemachine.plugins import PluginBase


class Hook(PluginBase):
    def __init__(self):
        self.seen = []

    def on_unhandled_event(self, i, e, ids, disp):
        self.seen.append(disp)


def probe(guarded: bool, policy: str = "ignore", event: str = "GO"):
    on = {"GO": ({"target": "b", "guard": "deny"} if guarded else "b")}
    cfg = {"id": "m", "initial": "a", "onUnhandled": policy,
           "states": {"a": {"on": on}, "b": {}}}
    h = Hook()
    s = SyncInterpreter(
        create_machine(cfg, logic=MachineLogic(guards={"deny": lambda c, e: False}))
    ).use(h).start()
    r = s.send(event, wait=True)
    return (r.changed, r.denied, r.deferred, tuple(h.seen))


def main() -> int:
    results = []

    noop = probe(False, event="NOPE")
    denied = probe(True)
    deferred = probe(False, policy="defer", event="NOPE")

    results.append(("noop pattern", noop == (False, False, False, ("ignored",))))
    results.append(("denied pattern", denied == (False, True, False, ("guard_denied",))))
    results.append(("deferred pattern", deferred == (False, False, True, ("deferred",))))
    results.append(("all three pairwise distinct", len({noop, denied, deferred}) == 3))

    # denied-only-when-all-candidates-denied
    cfg2 = {"id": "m", "initial": "a",
            "states": {"a": {"on": {"GO": [{"target": "b", "guard": "deny"}, {"target": "c"}]}},
                       "b": {}, "c": {}}}
    s2 = SyncInterpreter(
        create_machine(cfg2, logic=MachineLogic(guards={"deny": lambda c, e: False}))
    ).start()
    r2 = s2.send("GO", wait=True)
    results.append(("fallback candidate: changed=True", r2.changed is True))
    results.append(("fallback candidate: denied=False", r2.denied is False))

    print("RESULTS:")
    ok = True
    for label, passed in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
        ok = ok and passed
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
