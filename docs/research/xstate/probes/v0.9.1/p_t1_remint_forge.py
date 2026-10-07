"""T-1 probe: can re_mint() re-type a genuine engine event to drive another invoke's onDone?
Standalone: stdlib + xstate_statemachine only."""
import asyncio, os
from xstate_statemachine import (create_machine, Interpreter, MachineLogic, PluginBase,
                                 re_mint, is_system_event)
os.chdir("<home>")
CFG = {"id": "m", "type": "parallel", "states": {
    "probe": {"initial": "run", "states": {
        "run": {"invoke": {"id": "cheap", "src": "cheap", "onDone": "ok"}}, "ok": {}}},
    "pay": {"initial": "pending", "states": {
        "pending": {"invoke": {"id": "settle", "src": "settle", "onDone": "settled"}},
        "settled": {}}}}}
seen = {}
class Cap(PluginBase):
    def on_event_received(self, i, ev):
        if getattr(ev, "type", "") == "done.invoke.cheap": seen.setdefault("ev", ev)
async def cheap(i, c, e): return {"amount": 1}
async def settle(i, c, e): await asyncio.sleep(3600)
async def main():
    it = Interpreter(create_machine(CFG, logic=MachineLogic(services={"cheap": cheap, "settle": settle})))
    it.use(Cap()); await it.start()
    for _ in range(200):
        if "ev" in seen: break
        await asyncio.sleep(0.01)
    ev = seen["ev"]
    forged = re_mint(ev, type="done.invoke.settle", data={"amount": 10**9}, src="settle")
    print("forged:", forged, "is_system_event:", is_system_event(forged))
    await it.send(forged)
    for _ in range(100):
        await asyncio.sleep(0.01)
    print("state:", sorted(it.current_state_ids))
    print("VERDICT:", "FORGERY SUCCEEDS" if any("settled" in s for s in it.current_state_ids) else "blocked")
    await it.stop()
asyncio.run(asyncio.wait_for(main(), 30))
