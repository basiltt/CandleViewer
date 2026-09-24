"""T-1 probe (sync engine, def service): re_mint type forgery."""
import os
from xstate_statemachine import create_machine, SyncInterpreter, MachineLogic, PluginBase, re_mint
os.chdir("C:/Users/basil")
CFG = {"id": "m", "type": "parallel", "strict": True, "states": {
    "probe": {"initial": "run", "states": {"run": {"invoke": {"id": "cheap", "src": "cheap", "onDone": "ok"}}, "ok": {}}},
    "pay": {"initial": "idle", "states": {"idle": {"on": {"ARM": "pending"}},
        "pending": {"invoke": {"id": "settle", "src": "settle", "onDone": "settled"}}, "settled": {}}}}}
seen = {}
class Cap(PluginBase):
    def on_event_received(self, i, ev):
        if getattr(ev, "type", "") == "done.invoke.cheap": seen.setdefault("ev", ev)
def cheap(i, c, e): return {"amount": 1}
def settle(i, c, e): raise RuntimeError("never settles")
it = SyncInterpreter(create_machine(CFG, logic=MachineLogic(services={"cheap": cheap, "settle": settle})))
it.use(Cap()); it.start()
it.send("ARM")
print("before:", sorted(it.current_state_ids))
it.send(re_mint(seen["ev"], type="done.invoke.settle", data={"amount": 10**9}, src="settle"))
print("after:", sorted(it.current_state_ids))
