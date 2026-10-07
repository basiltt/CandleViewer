"""Chain-trip latch across snapshot round-trip (#222) + recursive nested
unknown-key fuzz (#220), both engines/kinds where relevant.
STANDALONE: stdlib + xstate_statemachine only.
"""
import sys, json
sys.path.insert(0, "<workspace>/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
from xstate_statemachine.exceptions import RunawayChainError

# --- A: chain-trip latch survives snapshot/restore ---
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
print("state:", interp.current_state_ids)
print("chain_trips after trip:", interp.chain_trips, "last_chain_error:", interp.last_chain_error)
snap = interp.get_snapshot()
restored = SyncInterpreter.from_snapshot(snap, m)
print("chain_trips SURVIVES restore (persisted?):", getattr(restored, "chain_trips", None))
print("last_chain_error SURVIVES restore:", restored.last_chain_error)
# benign event after restore should not erase pre-existing latch unless cleared
try:
    restored.send("GO")
except RunawayChainError:
    pass
print("chain_trips after post-restore event:", restored.chain_trips,
      "last_chain_error still latched:", restored.last_chain_error is not None)
restored.clear_chain_error()
print("after clear_chain_error(): last_chain_error:", restored.last_chain_error,
      "chain_trips (monotonic, unchanged):", restored.chain_trips)
