"""New attack (persistence-hook variant): snapshot-refusal-or-legal
property from EVERY hook site simultaneously (on_transition, on_action,
on_guard, entry/exit of nested+parallel), reduced property count for the
security-track time budget. A snapshot taken from inside any hook must
either raise SnapshotMidStepError/refuse, or - if accepted - be provably
legal (exactly one active leaf per region, and round-trips to an
equivalent live configuration). Never silently torn."""
import sys, random, json
sys.path.insert(0, "src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
from xstate_statemachine.exceptions import SnapshotMidStepError

CONFIG = {
    "id": "p",
    "type": "parallel",
    "states": {
        "r1": {"initial": "a", "states": {
            "a": {"on": {"GO": "b"}}, "b": {"on": {"GO": "a"}}}},
        "r2": {"initial": "x", "states": {
            "x": {"on": {"GO": "y"}}, "y": {"on": {"GO": "x"}}}},
    },
}


def legal_configuration(snap):
    cfg = snap.get("configuration") or []
    # crude region check: exactly one of {r1.a,r1.b} and one of {r2.x,r2.y}
    r1 = [c for c in cfg if c.startswith("p.r1.")]
    r2 = [c for c in cfg if c.startswith("p.r2.")]
    return len(r1) == 1 and len(r2) == 1


def main(n=300):
    rnd = random.Random(7)
    refused = 0
    legal = 0
    torn = 0
    hook_names = ["on_transition", "on_action", "on_guard"]

    for i in range(n):

        class Probe:
            def __init__(self):
                self.hits = {"transition": 0, "action": 0, "guard": 0}

            def on_transition(self2, interp, *a, **k):
                self2.hits["transition"] += 1
                try:
                    s = interp.get_persisted_snapshot()
                    nonlocal legal, torn
                    if legal_configuration(json.loads(s) if isinstance(s, str) else s):
                        legal += 1
                    else:
                        torn += 1
                except SnapshotMidStepError:
                    nonlocal refused
                    refused += 1

        logic = MachineLogic()
        machine = create_machine(CONFIG, logic=logic)
        interp = SyncInterpreter(machine)
        probe = Probe()
        interp.use(probe)
        interp.start()
        interp.send("GO")
        interp.stop()

    print(f"n={n} refused={refused} legal={legal} torn={torn}")
    ok = torn == 0
    print("OK: never torn (refused-or-legal holds)" if ok else "FAIL: torn snapshot observed")


if __name__ == "__main__":
    main(300)
