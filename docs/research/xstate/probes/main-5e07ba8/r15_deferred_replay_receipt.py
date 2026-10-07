"""When a deferred event is later REPLAYED and actually handled, does the
caller's receipt reflect the replay, or is it stuck at the deferred answer?"""
import sys, asyncio
sys.path.insert(0,"<workspace>/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter
CFG={"id":"m","initial":"a","onUnhandled":"defer","states":{
 "a":{"on":{"GO":{"target":"b"}}},
 "b":{"on":{"WORK":{"target":"c"}}},"c":{}}}
async def main():
    i=Interpreter(create_machine(CFG, logic=MachineLogic())); await i.start()
    r=await i.send("WORK", wait=True)     # deferred in 'a'
    print("receipt at defer time:", r)
    await i.send("GO")                     # -> b, replays WORK -> c
    await asyncio.sleep(0.3)
    print("final state:", i.current_state_ids, "(WORK DID run)")
    print("=> the caller's ONLY receipt reported changed=False and state 'm.a';")
    print("   there is no second receipt for the replay. Receipts left:", len(i._receipts))
    await i.stop()
asyncio.run(main())
