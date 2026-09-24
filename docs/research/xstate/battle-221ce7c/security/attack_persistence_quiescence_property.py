"""New attack (reduced): snapshot at every quiescent point of a randomized
event-sending run must always succeed and round-trip; SnapshotMidStepError
must never fire at quiescence. Reduced to 500 events (from a notional 2k)
for the time budget."""
import sys, random, json
sys.path.insert(0, "src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
from xstate_statemachine.exceptions import SnapshotMidStepError

cfg = {
    "id": "m",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {"on": {"GO": "b", "SELF": "a"}},
        "b": {"on": {"GO": "c", "SELF": "b"}},
        "c": {"on": {"GO": "a", "SELF": "c"}},
    },
}
m = create_machine(cfg, logic=MachineLogic())
interp = SyncInterpreter(m).start()

random.seed(7)
events = ["GO", "SELF", "UNHANDLED"]
N = 500
mid_step_at_quiescence = 0
roundtrip_failures = 0
for i in range(N):
    ev = random.choice(events)
    interp.send(ev)
    # quiescent here: send() returned, no in-flight macrostep
    try:
        snap = interp.get_snapshot()
    except SnapshotMidStepError:
        mid_step_at_quiescence += 1
        continue
    try:
        restored = SyncInterpreter.from_snapshot(snap, m)
        rsnap = restored.get_snapshot()
        if json.loads(rsnap)["state_ids"] != json.loads(snap)["state_ids"]:
            roundtrip_failures += 1
    except Exception as e:
        roundtrip_failures += 1
        print("roundtrip exc at", i, type(e).__name__, e)

print(f"events={N} mid_step_at_quiescence={mid_step_at_quiescence} roundtrip_failures={roundtrip_failures}")
assert mid_step_at_quiescence == 0, "SnapshotMidStepError fired at a quiescent point"
assert roundtrip_failures == 0, "snapshot round-trip failed at a quiescent point"
print("OK: quiescent snapshot always succeeded and round-tripped over", N, "events")
