import sys, asyncio, json
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter, SyncInterpreter, PluginBase
from xstate_statemachine.clock import SimulatedClock

CFG = {
 "id":"m","initial":"idle","context":{"n":0},
 "states":{
  "idle":{"on":{"GO":{"target":"work","actions":["bump"]}}},
  "work":{"entry":[{"type":"raise","params":{"event":"TICK"}}],
          "after":{"100":{"target":"idle","actions":["bump"]}},
          "on":{"TICK":{"actions":["bump"]},"STOP":{"target":"idle"}}},
 }}

def bump(i,c,e,a): c["n"] = c["n"]+1

async def main():
    clock = SimulatedClock()
    m = create_machine(CFG, logic=MachineLogic(actions={"bump":bump}))
    i = await Interpreter(m, clock=clock).start()
    r = await i.send("GO", wait=True)
    print("receipt", r)
    await clock.increment(150)
    print("state", i.current_state_ids, i.context)
    snap = i.get_persisted_snapshot()
    print("snapkeys", sorted(snap.keys()))
    await i.stop()

asyncio.run(main())

clock = SimulatedClock()
m = create_machine(CFG, logic=MachineLogic(actions={"bump":bump}))
s = SyncInterpreter(m, clock=clock).start()
print("sync receipt", s.send("GO", wait=True))
clock.increment(150)
print("sync", s.current_state_ids, s.context)
s.stop()
