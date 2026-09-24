import sys, gc
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
CFG={"id":"m","initial":"a","onUnhandled":"defer","states":{
 "a":{"on":{"GO":{"target":"b"}}},
 "b":{"on":{"WORK":{"target":"a"},"GO":{"target":"b"}}}}}
i=SyncInterpreter(create_machine(CFG, logic=MachineLogic())); i.start()
false_pos=0
for n in range(3000):
    i.send("WORK")            # deferred, fire-and-forget -> id never discarded
    i.send("GO")              # handled; replays the deferred WORK
print("len(_deferred_this_step) after 3000 fire-and-forget defers:", len(i._deferred_this_step))
print("len(_deferred_events)               :", len(i._deferred_events))
# now a handled event whose id may collide with a freed deferred event's id
for n in range(2000):
    r=i.send("GO", wait=True)
    if r.deferred:
        false_pos+=1
print("FALSE deferred=True on handled sends:", false_pos, "of 2000")
i.stop()
