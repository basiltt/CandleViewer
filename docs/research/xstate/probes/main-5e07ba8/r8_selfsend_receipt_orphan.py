"""#90: a self-send with wait=True is rerouted to the INTERNAL queue.
Internal events are drained by _process_event_and_transient_transitions, which
never calls _resolve_receipt. Does the receipt EVER resolve, even after the
action returns and the machine is idle?"""
import sys, asyncio
sys.path.insert(0,"<workspace>/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter
CFG={"id":"m","initial":"a","states":{"a":{"on":{
  "START":{"actions":["fire"]},"SELF":{"target":"b"}}},"b":{}}}
box={}
async def fire(i,c,e,a):
    box["fut"]=i.send("SELF", wait=True)   # do NOT await here
async def main():
    i=Interpreter(create_machine(CFG, logic=MachineLogic(actions={"fire":fire})))
    await i.start(); await i.send("START"); await asyncio.sleep(0.3)
    print("state after macrostep:", i.current_state_ids, "(SELF WAS processed)")
    try:
        r=await asyncio.wait_for(box["fut"], timeout=2.0)
        print("receipt resolved:", r)
    except asyncio.TimeoutError:
        print("RECEIPT NEVER RESOLVES -> caller hangs forever. DEFECT")
    print("pending receipts left in map:", len(i._receipts))
    await i.stop()
asyncio.run(main())
