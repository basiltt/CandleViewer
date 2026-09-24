import asyncio, gc, sys
from xstate_statemachine import Interpreter, create_machine, MachineLogic
from xstate_statemachine.plugins import PluginBase
class H(PluginBase):
    def __init__(s): s.n=[]
    def on_receipt_dropped(s,i,t): s.n.append(t)
def act(i,ctx,e,ad): i.send("B", wait=True)   # dropped awaitable inside an action
CFG={"id":"m","initial":"s1","states":{"s1":{"on":{"A":{"target":"s2","actions":["act"]}}},"s2":{"on":{"B":"s3"}},"s3":{"type":"final"}}}
async def run(top):
    h=H(); i=Interpreter(create_machine(CFG,logic=MachineLogic(actions={"act":act}))).use(h); await i.start()
    if top: i.send("A", wait=True)
    else: await i.send("A", wait=True)
    await asyncio.sleep(0.02); gc.collect(); await asyncio.sleep(0.01)
    print("top-level" if top else "in-action", "dropped_receipts", i.dropped_receipts, "hook", h.n, "state", sorted(i.current_state_ids))
    await i.stop()
asyncio.run(run(False)); asyncio.run(run(True))
