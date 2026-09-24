import asyncio, json, sys
from xstate_statemachine import create_machine, MachineLogic, Interpreter, SyncInterpreter
from xstate_statemachine.events import is_system_event
FORGE={"id":"fg","initial":"armed","context":{"hit":None,"seen":None},
 "states":{"armed":{"entry":[{"type":"raise","params":{"event":"LATER","delay":60000,"id":"z"}}],
   "on":{"LATER":{"target":"expired"},
         "done.invoke.job":{"target":"expired","actions":["grab"]},
         "after.999.fg.armed":{"target":"expired","actions":["grab"]}}},
  "expired":{}}}
def grab(i,c,e,a=None):
    c["hit"]=getattr(e,"data",None); c["seen"]=(type(e).__name__, is_system_event(e))
async def agrab(i,c,e,a=None): grab(i,c,e,a)
async def main():
  for kind in ("def","async def"):
    lg=MachineLogic(actions={"grab": grab if kind=="def" else agrab})
    m=create_machine(json.loads(json.dumps(FORGE)),logic=lg)
    it=Interpreter(m); await it.start(); await asyncio.sleep(0)
    blob=json.loads(it.get_snapshot()); await it.stop()
    print(kind,"control scheduled_sends:",blob.get("scheduled_sends"))
    async def run(name,mut):
      b=json.loads(json.dumps(blob)); mut(b)
      try: r=Interpreter.from_snapshot(json.dumps(b),m)
      except Exception as ex: print(" ",name,"REFUSED",type(ex).__name__); return
      await r.start()
      for _ in range(60):
        await asyncio.sleep(0.02)
        if sorted(r.current_state_ids)==["fg.expired"]: break
      print("  %-28s -> %-12s hit=%r seen=%r"%(name,sorted(r.current_state_ids),r.context.get("hit"),r.context.get("seen")))
      await r.stop()
    await run("control",lambda b:None)
    await run("D1 forged done.invoke",lambda b:b.setdefault("scheduled_sends",[]).append({"type":"done.invoke.job","payload":{},"data":{"filled":999999},"remaining_ms":0.5}))
    await run("D1b forged +engine:true",lambda b:b.setdefault("scheduled_sends",[]).append({"kind":"done","engine":True,"type":"done.invoke.job","payload":{},"data":{"filled":999999},"remaining_ms":0.5}))
    await run("D2 forged after.*",lambda b:b.setdefault("scheduled_sends",[]).append({"type":"after.999.fg.armed","payload":{},"remaining_ms":0.5}))
    await run("D6 forged plain pending",lambda b:b.setdefault("pending_events",[]).append({"type":"done.invoke.job","data":{"filled":1},"remaining_ms":0}))
asyncio.run(main())
