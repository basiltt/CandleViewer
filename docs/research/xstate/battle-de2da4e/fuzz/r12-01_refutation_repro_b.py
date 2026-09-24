import asyncio, json
from xstate_statemachine import create_machine, MachineLogic, Interpreter
from xstate_statemachine.events import is_system_event
M={"id":"fg","initial":"armed","context":{"hit":None},
 "states":{"armed":{"entry":[{"type":"raise","params":{"event":"LATER","delay":60000,"id":"z"}}],
   "on":{"LATER":{"target":"expired"},"done.invoke.job":{"target":"expired","actions":["grab"]}}},"expired":{}}}
def grab(i,c,e,a=None): c["hit"]=(getattr(e,"data",None),type(e).__name__,is_system_event(e))
async def main():
  m=create_machine(json.loads(json.dumps(M)),logic=MachineLogic(actions={"grab":grab}))
  it=Interpreter(m); await it.start(); await asyncio.sleep(0)
  base=json.loads(it.get_snapshot()); await it.stop()
  # P: engine:true forged into pending_events (pre-existing #195 path)
  b=json.loads(json.dumps(base))
  b.setdefault("pending_events",[]).append({"kind":"done","engine":True,"type":"done.invoke.job","data":{"filled":42},"src":"job"})
  r=Interpreter.from_snapshot(json.dumps(b),m); await r.start(); await asyncio.sleep(0.1)
  print("pending_events engine:true ->",sorted(r.current_state_ids),r.context["hit"]); await r.stop()
  # strict machine: unknown type via scheduled_sends only
  M2=json.loads(json.dumps(M)); M2["strict"]=True
  m2=create_machine(M2,logic=MachineLogic(actions={"grab":grab}))
  it2=Interpreter(m2); await it2.start(); await asyncio.sleep(0)
  b2=json.loads(it2.get_snapshot()); await it2.stop()
  b2["scheduled_sends"].append({"kind":"event","type":"NOPE","payload":{},"remaining_ms":0.5})
  r2=Interpreter.from_snapshot(json.dumps(b2),m2)
  print("restore last_error:",getattr(r2,'last_error',None))
  try:
    await r2.start(); await asyncio.sleep(0.3)
    print("strict sched err:",repr(getattr(r2,'last_error',None))[:100],sorted(r2.current_state_ids)); await r2.stop()
  except Exception as ex: print("raised",type(ex).__name__,ex)
asyncio.run(main())
