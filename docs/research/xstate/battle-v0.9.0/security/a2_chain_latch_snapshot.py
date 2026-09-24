"""D12-security-1 re-check: does chain_trips/last_chain_error now survive
a snapshot round-trip per #226? Also monotonic-across-N-restarts property.
STANDALONE: stdlib + xstate_statemachine only."""
import sys, json
sys.path.insert(0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
from xstate_statemachine.exceptions import RunawayChainError
from xstate_statemachine.actions import raise_ as raise_action

cfg = {
    "id": "m", "initial": "a", "maxIterations": 3,
    "states": {
        "a": {"entry": [raise_action({"type": "GO"})], "on": {"GO": {"target": "a", "reenter": True}}},
    },
}

m = create_machine(cfg, logic=MachineLogic())
interp = SyncInterpreter(m).start()
try:
    interp.send("GO")
except RunawayChainError:
    pass
print("chain_trips after trip1:", interp.chain_trips, "last_chain_error:", interp.last_chain_error)

snap = interp.get_persisted_snapshot()
print("type(get_persisted_snapshot()):", type(snap).__name__)
print("v3 envelope has chain_trips key:", "chain_trips" in snap, "last_chain_error key:", "last_chain_error" in snap)

restored = SyncInterpreter.from_snapshot(json.dumps(snap), m)
print("chain_trips SURVIVES restore:", restored.chain_trips)
print("last_chain_error SURVIVES restore (RestoredError):", restored.last_chain_error)
print("RestoredError type:", type(restored.last_chain_error).__name__ if restored.last_chain_error else None)

current = restored
for n in range(2, 5):
    try:
        current.send("GO")
    except RunawayChainError:
        pass
    snap2 = current.get_persisted_snapshot()
    current = SyncInterpreter.from_snapshot(json.dumps(snap2), m)
    print(f"restart#{n-1}: chain_trips={current.chain_trips} monotonic_ok={current.chain_trips==n}")

current.clear_chain_error()
print("after clear_chain_error(): last_chain_error:", current.last_chain_error, "count unchanged:", current.chain_trips)

# v2 upcast: old blob has no chain_trips/last_chain_error -> defaults
old = SyncInterpreter(m).start().get_persisted_snapshot()
old["version"] = 2
old.pop("chain_trips", None)
old.pop("last_chain_error", None)
r2 = SyncInterpreter.from_snapshot(json.dumps(old), m)
print("v2 upcast defaults: chain_trips=", r2.chain_trips, "last_chain_error=", r2.last_chain_error)
