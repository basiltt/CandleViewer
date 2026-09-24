import sys
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
CFG={"id":"m","initial":"a","onUnhandled":"defer","states":{"a":{"on":{"GO":{"target":"a"}}}}}
i=SyncInterpreter(create_machine(CFG, logic=MachineLogic())); i.start()
for n in range(20000):
    i.send(f"NOPE{n%50}")       # deferred, fire-and-forget -> ids accumulate
i._deferred_events.clear()
print("stale ids retained:", len(i._deferred_this_step))
hits=0; trials=20000
for _ in range(trials):
    if i.send("GO", wait=True).deferred: hits+=1
print(f"HANDLED 'GO' reported deferred=True: {hits}/{trials}")
print("VERDICT:", "DEFECT REPRODUCED" if hits else "miss")
i.stop()
