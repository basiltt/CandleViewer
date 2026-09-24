# -*- coding: utf-8 -*-
"""Is the `def` path immune, or merely stalled by the blocking service?"""
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

async def run(kind,svc_secs,settle,tag):
    i=Interpreter(build(kind,svc_secs)); await i.start(children_timeout=0.5)
    await asyncio.sleep(0.05); before=sorted(i.current_state_ids)
    await i.send(DoneEvent(type="done.invoke.k",data={"forged":True},src="k"))
    await asyncio.sleep(settle)
    print("  [%-5s] %-30s %s -> %s seen=%r"%(kind,tag,before,
        sorted(i.current_state_ids),i.context.get("seen")))
    await i.stop()

async def main():
    print("def with SHORT service (0.4s) + long settle: does the forged event\n"
          "land once the loop is free again?")
    await run("def",0.4,1.5,"svc=0.4s settle=1.5s")
    await run("async",0.4,1.5,"svc=0.4s settle=1.5s")
    print("\ndef with NO blocking at all (svc=0s):")
    await run("def",0.0,0.6,"svc=0s settle=0.6s")
asyncio.run(main())
