import asyncio, json
from xstate_statemachine import Interpreter, MachineLogic, create_machine
CFG={"id":"t","initial":"a","context":{},"states":{"a":{"on":{"GO":{"target":"b","actions":["slow"]}}},"b":{}}}
async def slow(i,c,e,a): await asyncio.sleep(0.4)
async def main():
    i=Interpreter(create_machine(CFG,logic=MachineLogic(actions={"slow":slow})))
    await i.start()
    t=i.send("GO")
    await asyncio.sleep(0.15)
    snap=i.get_persisted_snapshot()
    d=snap if isinstance(snap,dict) else json.loads(snap)
    print("state_ids",d.get("state_ids"),"configuration",d.get("configuration"),"status",d.get("status"))
    await t; await asyncio.sleep(0.1)
    r=Interpreter.from_snapshot(json.dumps(snap) if isinstance(snap,dict) else snap,create_machine(CFG,logic=MachineLogic(actions={"slow":slow})))
    await r.start()
    rec=await r.send("PING",wait=True)
    print("restored cfg",r.current_state_ids,"status",r.status,"dormant",r.has_dormant_invocations,"receipt",rec)
    print("TORN" if not d.get("state_ids") else "NOT-TORN")
    await r.stop(); await i.stop()
asyncio.run(main())
