# -*- coding: utf-8 -*-
"""Wire vector: does a TAMPERED snapshot reconstitute a trusted DoneEvent?"""
from __future__ import annotations
import asyncio, json, time
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.events import Event, restore_event, is_system_event

SPEC={"id":"sec","initial":"a","strict":True,"onUnhandled":"error",
 "states":{"a":{"invoke":[{"id":"k","src":"svc","onDone":{"target":"done_","actions":["stash"]}}],
 "on":{"KNOWN":"b"}},"b":{},"done_":{}}}
def build(kind):
    def svc_def(i,c,e): time.sleep(8); return {"real":True}
    async def svc_async(i,c,e): await asyncio.sleep(8); return {"real":True}
    def stash(i,c,e,a): c["got"]=getattr(e,"data",None)
    return create_machine(json.loads(json.dumps(SPEC)),
      logic=MachineLogic(services={"svc":svc_def if kind=="def" else svc_async},
                         actions={"stash":stash}))

async def main():
    print("1) restore_event() on an ATTACKER-AUTHORED record:")
    rec={"kind":"done","type":"done.invoke.k","data":{"forged":True,"px":9e9},"src":"k"}
    ev=restore_event(rec)
    print("   record=%s"%json.dumps(rec))
    print("   -> %r  is_system_event=%s"%(ev,is_system_event(ev)))
    print("   (no signature/provenance check at the restore boundary)\n")

    print("2) can that restored object drive onDone on a live machine?")
    for kind in ("def","async"):
        i=Interpreter(build(kind)); await i.start(children_timeout=0.5)
        await asyncio.sleep(0.05); b=sorted(i.current_state_ids)
        await i.send(ev); await asyncio.sleep(0.2)
        print("   [%-5s] %s -> %-16s ctx.got=%r"%(kind,b,
            str(sorted(i.current_state_ids)),i.context.get("got")))
        await i.stop()

    print("\n3) is the snapshot blob integrity-protected at all?")
    i=Interpreter(build("async")); await i.start(children_timeout=0.5)
    snap=i.get_snapshot(); await i.stop()
    d=json.loads(snap) if isinstance(snap,str) else snap
    print("   top-level keys:",sorted(d.keys()) if isinstance(d,dict) else type(d))
asyncio.run(main())
