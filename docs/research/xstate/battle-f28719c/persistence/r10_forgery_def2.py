from __future__ import annotations
import asyncio, json, time
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.events import DoneEvent
SPEC={"id":"sec","initial":"a","strict":True,"onUnhandled":"error",
 "states":{"a":{"invoke":[{"id":"k","src":"svc","onDone":{"target":"done_","actions":["stash"]}}],
 "on":{"KNOWN":"b"}},"b":{},"done_":{}}}
def build(kind,secs):
    def svc_def(i,c,e): time.sleep(secs); return {"real":True}
    async def svc_async(i,c,e): await asyncio.sleep(secs); return {"real":True}
    def stash(i,c,e,a): c.setdefault("seen",[]).append(getattr(e,"data",None))
    return create_machine(json.loads(json.dumps(SPEC)),
      logic=MachineLogic(services={"svc":svc_def if kind=="def" else svc_async},
                         actions={"stash":stash}))
async def run(kind,svc,settle):
    i=Interpreter(build(kind,svc)); await i.start(children_timeout=0.5)
    await asyncio.sleep(0.05); b=sorted(i.current_state_ids)
    await i.send(DoneEvent(type="done.invoke.k",data={"forged":True},src="k"))
    await asyncio.sleep(settle)
    print("  [%-5s] svc=%-4s settle=%-4s %s -> %-16s seen=%r"%(kind,svc,settle,b,
        str(sorted(i.current_state_ids)),i.context.get("seen")))
    await i.stop()
async def main():
    print("def, service still running, generous settle (loop is NOT blocked:\n"
          "def services go to run_in_executor, interpreter.py:2813):")
    for s in (0.5,1.0,2.0):
        await run("def",8,s)
asyncio.run(main())
