from xstate_statemachine import SyncInterpreter, Interpreter, MachineLogic, create_machine
import asyncio
CFG={"id":"m","initial":"a","states":{"a":{"always":"#m"}}}
s=SyncInterpreter(create_machine(CFG,logic=MachineLogic()))
s.start()
print("SYNC ids",s.current_state_ids,"value",s.current_state_value if hasattr(s,'current_state_value') else None,"status",s.status)
s.send("X"); print("after X:",s.current_state_ids,s.status)
CFG2={"id":"m","initial":"a","states":{"a":{"on":{"GO":"#m"}},"b":{}}}
s2=SyncInterpreter(create_machine(CFG2,logic=MachineLogic())); s2.start()
print("ev-variant start",s2.current_state_ids); s2.send("GO"); print("after GO",s2.current_state_ids,s2.status)
async def m():
    i=Interpreter(create_machine(CFG,logic=MachineLogic())); await i.start()
    print("ASYNC ids",i.current_state_ids,"status",i.status)
    import json; snap=i.get_persisted_snapshot()
    d=snap if isinstance(snap,dict) else json.loads(snap)
    print("snap state_ids",d.get("state_ids"),"configuration",d.get("configuration"))
    await i.stop()
asyncio.run(m())
