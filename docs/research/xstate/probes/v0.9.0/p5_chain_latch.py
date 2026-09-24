"""S-probe 5: #226 chain_trips/last_chain_error across a snapshot; upcast
defaults; RestoredError type; machine_hash coverage; clear_chain_error."""
import asyncio, json
from xstate_statemachine import (create_machine, MachineLogic, Interpreter,
                                 RestoredError)
CFG = {"id": "m", "initial": "a", "maxIterations": 3, "states": {
    "a": {"entry": [{"type": "xstate.raise", "params": {"event": "LOOP"}}],
          "on": {"LOOP": {"target": "a", "reenter": True}}}}}

async def main():
    m = create_machine(CFG, logic=MachineLogic())
    i = Interpreter(m)
    await i.start(); await asyncio.sleep(0.2)
    print("trips=", i.chain_trips, "latched=", type(i.last_chain_error).__name__)
    snap = i.get_persisted_snapshot(); await i.stop()
    print("keys present:", "chain_trips" in snap, "last_chain_error" in snap)
    h = snap["machine_hash"]
    snap2 = dict(snap); snap2["chain_trips"] = 999; snap2["last_chain_error"] = "FORGED"
    r = Interpreter.from_snapshot(json.dumps(snap2), m)
    print("hash-covers-new-fields:", h == snap2["machine_hash"], "-> accepted forged:",
          r.chain_trips, type(r.last_chain_error).__name__, str(r.last_chain_error))
    print("is RestoredError:", isinstance(r.last_chain_error, RestoredError),
          "is RunawayChainError:", type(r.last_chain_error).__mro__[1].__name__)
    r.clear_chain_error()
    print("after clear:", r.last_chain_error, "trips=", r.chain_trips)
    # upcast: old blob without the fields
    old = dict(snap); old.pop("chain_trips"); old.pop("last_chain_error")
    r2 = Interpreter.from_snapshot(json.dumps(old), m)
    print("upcast defaults:", r2.chain_trips, r2.last_chain_error)
    await r.stop(); await r2.stop()

asyncio.run(asyncio.wait_for(main(), 25))
