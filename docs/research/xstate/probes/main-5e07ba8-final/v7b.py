import asyncio,json
from xstate_statemachine import Interpreter, MachineLogic, create_machine
CFG={"id":"m","initial":"a","states":{"a":{"on":{"W":{"actions":["slow"]},"URGENT":"b","A":{"actions":[]},"B":{"actions":[]}}},"b":{}}}
async def slow(i,c,e,a): await asyncio.sleep(0.6)
async def main():
    i=Interpreter(create_machine(CFG,logic=MachineLogic(actions={"slow":slow})))
    await i.start()
    i.send("W"); await asyncio.sleep(0.08)
    await i.send("A"); await i.send("B")
    await i.send("URGENT",priority=True)
    snap=i.get_persisted_snapshot(); d=snap if isinstance(snap,dict) else json.loads(snap)
    dp=await i.drain_pending()
    print("status",i.status,"queue_depth",i.queue_depth,"pending_events",[getattr(e,'type',e) for e in i.pending_events])
    print("snap pending_events",d.get("pending_events"))
    print("drain_pending",[getattr(e,'type',e) for e in dp])
    await asyncio.sleep(0.9); await i.stop()
asyncio.run(main())
