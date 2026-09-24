import sys
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
CFG={"id":"m","initial":"a","onUnhandled":"defer","deferLimit":1,"states":{"a":{"on":{"GO":{"target":"a"}}}}}
i=SyncInterpreter(create_machine(CFG, logic=MachineLogic())); i.start()
for n in range(50000): i.send(f"NOPE{n}")
print("SYNC _deferred_this_step:", len(i._deferred_this_step), "bytes:", sys.getsizeof(i._deferred_this_step))
i.stop()
