import asyncio, logging; logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, MachineLogic, Interpreter
def boom(i,c,e,a): raise RuntimeError("boom")
def mutate(i,c,e,a): c["n"]=99
# Transition itself has no actions; the entered state has no entry/exit either.
# But the entered state has an `always` transition whose ACTIONS run and fail.
cfg={"id":"m","actionErrorPolicy":"rollback","initial":"a","context":{"n":0},
 "states":{"a":{"on":{"T":{"target":"b"}}},
           "b":{"always":{"target":"c","actions":["mutate","boom"]}},
           "c":{}}}
async def main():
    i=await Interpreter(create_machine(cfg, logic=MachineLogic(actions={"boom":boom,"mutate":mutate}))).start()
    await i.send("T"); await asyncio.sleep(0.2)
    print("state:", i.current_state_ids, "context n =", i.context["n"], "(rollback should restore 0)")
    await i.stop()
asyncio.run(main())
