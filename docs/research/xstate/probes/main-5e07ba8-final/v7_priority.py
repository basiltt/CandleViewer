import asyncio,json
from xstate_statemachine import Interpreter, MachineLogic, create_machine
CFG={"id":"m","initial":"a","states":{"a":{"entry":["slow"],"on":{"URGENT":"b","A":"a"}},"b":{}}}
async def slow(i,c,e,a): await asyncio.sleep(0.6)
async def main():
    i=Interpreter(create_machine(CFG,logic=MachineLogic(actions={"slow":slow})))
    st=asyncio.ensure_future(i.start()) if asyncio.iscoroutine(i.start()) else None
    await asyncio.sleep(0.1)
    await i.send("URGENT",priority=True)
    snap=i.get_persisted_snapshot(); d=snap if isinstance(snap,dict) else json.loads(snap)
    print("status",i.status,"queue_depth",i.queue_depth,"pending_events",i.pending_events,
          "drain",i.drain_pending() if hasattr(i,'drain_pending') else None,
          "snap pending_events",d.get("pending_events"))
    await asyncio.sleep(1.0); await i.stop()
asyncio.run(main())
