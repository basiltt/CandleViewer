# Does the DOCUMENTED-safe procedure avoid the tear? (docs/_guide/snapshots.md:134)
import asyncio, json
from xstate_statemachine import create_machine, MachineLogic, Interpreter
from xstate_statemachine.plugins import PluginBase
from xstate_statemachine.exceptions import XStateMachineError

CFG = {"id":"oms","type":"parallel","states":{
 "exchange":{"initial":"idle","states":{
   "idle":{"on":{"GO":"working"}},
   "working":{"entry":["slow_book"],"on":{"FILL":"filled"}},
   "filled":{"type":"final"}}},
 "risk":{"initial":"ok","states":{"ok":{}}}}}

async def main():
    out={}
    async def slow_book(i,c,e,ad=None):
        c["booked"]=False; await asyncio.sleep(0.03); c["booked"]=True
    class P(PluginBase):
        def on_transition(self, interp, frm, to, ev):
            if "on_transition" in out: return
            try: s=interp.get_persisted_snapshot(); out["on_transition"]=(s["state_ids"], s["context"])
            except XStateMachineError as ex: out["on_transition"]="REFUSED:"+type(ex).__name__
    m=create_machine(CFG, logic=MachineLogic(actions={"slow_book":slow_book}))
    i=Interpreter(m); i.use(P()); await i.start()
    r=await i.send("GO", wait=True)
    s=i.get_persisted_snapshot()
    out["after_wait_True"]=(s["state_ids"], s["context"])
    out["live"]=(sorted(i.current_state_ids), dict(i.context))
    await i.stop()
    print(json.dumps(out, indent=1, default=str))
asyncio.run(main())
