"""#90: send() from an action now routes to the INTERNAL queue.
Q1: does `await interp.send(..., wait=True)` inside an action deadlock?
Q2: ordering -- does a self-send now jump ahead of already-queued external events?"""
import sys, asyncio
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter
order=[]
CFG={"id":"m","initial":"a","states":{"a":{"on":{
  "START":{"actions":["self_send"]},"SELF":{"actions":["note_self"]},"EXT":{"actions":["note_ext"]}}}}}
async def self_send(i,c,e,a): await i.send("SELF")
def note_self(i,c,e,a): order.append("SELF")
def note_ext(i,c,e,a): order.append("EXT")
async def main():
    i=Interpreter(create_machine(CFG, logic=MachineLogic(actions={"self_send":self_send,"note_self":note_self,"note_ext":note_ext})))
    await i.start()
    await i.send("START"); await i.send("EXT")
    await asyncio.sleep(0.2)
    print("ORDER (self-send vs already-queued external):", order)
    await i.stop()
asyncio.run(main())

# Q1: wait=True from inside an action
res={}
async def self_send_wait(i,c,e,a):
    try:
        res["r"]=await asyncio.wait_for(i.send("SELF", wait=True), timeout=1.5)
    except asyncio.TimeoutError:
        res["r"]="DEADLOCK (timed out)"
async def main2():
    i=Interpreter(create_machine(CFG, logic=MachineLogic(actions={"self_send":self_send_wait,"note_self":note_self,"note_ext":note_ext})))
    await i.start(); await i.send("START"); await asyncio.sleep(2.0)
    print("await send(wait=True) inside an action ->", res.get("r"))
    await i.stop()
asyncio.run(main2())
