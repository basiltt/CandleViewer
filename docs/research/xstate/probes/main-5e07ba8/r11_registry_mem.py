import sys, tracemalloc
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic
acts={f"a{i}":(lambda i,c,e,a: None) for i in range(200)}
guards={f"g{i}":(lambda c,e: True) for i in range(200)}
logic=MachineLogic(actions=acts, guards=guards)
CFG={"id":"m","initial":"a","states":{"a":{"entry":["a0"],"on":{"GO":{"target":"a","guard":"g0"}}}}}
tracemalloc.start()
base=tracemalloc.get_traced_memory()[0]
ms=[create_machine(CFG, logic=logic) for _ in range(1000)]
peak=tracemalloc.get_traced_memory()[0]
print(f"1000 machines from ONE MachineLogic(200 actions,200 guards): {(peak-base)/1024/1024:.2f} MiB")
print("per machine:", f"{(peak-base)/1000/1024:.1f} KiB")
print("registries shared?", ms[0].logic.actions is ms[1].logic.actions, "| caller untouched?", logic.actions is not ms[0].logic.actions)
print("callable identity preserved:", ms[0].logic.actions["a0"] is logic.actions["a0"])
