from xstate_statemachine import create_machine, MachineLogic
def f(i,c,e,a): pass
logic=MachineLogic(actions={"store_user":f})
cfg={"id":"m","initial":"a","states":{"a":{"entry":["storeUser"]}}}
import copy
for n in range(3):
    create_machine(copy.deepcopy(cfg), logic=logic)
print("keys:", sorted(logic.actions))
