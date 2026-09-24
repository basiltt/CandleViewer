# -*- coding: utf-8 -*-
"""Refutation probe for R8-05: does the forged DoneEvent drive onDone for
BOTH service kinds, and is a *correct-usage* alternative available?"""
from __future__ import annotations
import asyncio, json, time
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.events import AfterEvent, DoneEvent, Event
try:
    from xstate_statemachine.events import is_system_event, event_kind
except Exception:
    is_system_event = event_kind = None

SPEC = {"id":"sec","initial":"a","strict":True,"onUnhandled":"error",
 "states":{"a":{"invoke":[{"id":"k","src":"svc","onDone":{"target":"done_",
   "actions":["stash"]}}],"on":{"KNOWN":"b"}},"b":{},"done_":{}}}

def build(kind, secs):
    def svc_def(i,c,e): time.sleep(secs); return {"real":True}
    async def svc_async(i,c,e): await asyncio.sleep(secs); return {"real":True}
    def stash(i,c,e,a): c["got"]=getattr(e,"data",None)
    return create_machine(json.loads(json.dumps(SPEC)),
        logic=MachineLogic(services={"svc": svc_def if kind=="def" else svc_async},
                           actions={"stash":stash}))

async def run(kind, wait_before, tag):
    i=Interpreter(build(kind,5))
    await i.start(children_timeout=0.5)
    await asyncio.sleep(wait_before)
    before=sorted(i.current_state_ids)
    await i.send(DoneEvent(type="done.invoke.k",data={"forged":True,"px":9e9},src="k"))
    await asyncio.sleep(0.15)
    print("  [%-5s] %-22s %s -> %s ctx.got=%r status=%s"%(
        kind,tag,before,sorted(i.current_state_ids),i.context.get("got"),i.status))
    await i.stop()

async def main():
    print("A) forged DoneEvent vs a LIVE invoke, real clock, both kinds:")
    for kind in ("def","async"):
        for w,tag in ((0.05,"forge @50ms"),(0.30,"forge @300ms")):
            await run(kind,w,tag)
    print("\nB) is_system_event on hand-built engine tuples (the trust predicate):")
    for nm,o in (("DoneEvent",DoneEvent(type="done.invoke.k",data={},src="k")),
                 ("AfterEvent",AfterEvent(type="after.1.x")),
                 ("Event",Event(type="done.invoke.k"))):
        print("   %-10s is_system_event=%s event_kind=%s"%(
            nm, is_system_event(o) if is_system_event else "n/a",
            event_kind(o) if event_kind else "n/a"))
    print("\nC) documented/correct way for a user to signal completion?")
    print("   DoneEvent is exported from the package root and documented in")
    print("   docs/api/index.md as a public NamedTuple with a constructor.")
asyncio.run(main())
