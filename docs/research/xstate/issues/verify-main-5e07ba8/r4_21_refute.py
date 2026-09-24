import asyncio, logging, sys
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine
from xstate_statemachine.clock import SimulatedClock
CFG={"id":"d8","initial":"idle","context":{"ok":0,"cancel":0},
 "states":{"idle":{"on":{"GO":{"target":"busy"}}},
  "busy":{"invoke":{"id":"s","src":"work","onDone":{"target":"idle","actions":["ok"]}},
   "on":{"CANCEL":{"target":"idle","actions":["cancel"]}}}}}
def logic():
    def ok(i,c,e,a): c["ok"]+=1
    def cancel(i,c,e,a): c["cancel"]+=1
    def work(i,c,e): return 1
    return MachineLogic(actions={"ok":ok,"cancel":cancel},services={"work":work})
def build(): return create_machine(CFG,logic=logic())
N=10
async def a_wait():
    i=Interpreter(build(),clock=SimulatedClock()); await i.start()
    for _ in range(N):
        await i.send("GO",wait=True)
        await i.send("CANCEL",wait=True)
    for _ in range(200): await asyncio.sleep(0)
    out=dict(i.context); await i.stop(); return out
def s_wait():
    i=SyncInterpreter(build(),clock=SimulatedClock()); i.start()
    for _ in range(N):
        i.send("GO",wait=True); i.send("CANCEL",wait=True)
    out=dict(i.context); i.stop(); return out
# also: async-style service on SYNC engine is impossible -> check what sync does w/ slow svc
print("sync  wait=True:",s_wait())
print("async wait=True:",asyncio.run(a_wait()))
