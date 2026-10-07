import sys, asyncio
sys.path.insert(0,"<workspace>/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter, SyncInterpreter
CFG={"id":"m","initial":"a","onUnhandled":"defer","states":{
 "a":{"on":{"GO":{"target":"b"}}},
 "b":{"on":{"WORK":{"target":"a"}}}}}
async def amain():
    i=Interpreter(create_machine(CFG, logic=MachineLogic())); await i.start()
    r=await i.send("WORK", wait=True)   # unhandled in a -> deferred
    print("ASYNC deferred-event receipt:", r)
    r2=await i.send("NOPE_UNKNOWN", wait=True)
    print("ASYNC 2nd deferred receipt  :", r2)
    r3=await i.send("GO", wait=True)
    print("ASYNC handled receipt       :", r3)
    await i.stop()
asyncio.run(amain())
i=SyncInterpreter(create_machine(CFG, logic=MachineLogic())); i.start()
print("SYNC  deferred receipt      :", i.send("WORK", wait=True))
print("SYNC  handled receipt       :", i.send("GO", wait=True))
i.stop()
