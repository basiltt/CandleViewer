from xstate_statemachine import create_machine, MachineLogic
log=[]
def store_user(i,c,e,a): log.append("snake-impl")
# Config legitimately declares TWO DIFFERENT actions whose names normalise equal.
cfg={"id":"m","initial":"a","states":{"a":{"entry":["storeUser","store_user"]}}}
m=create_machine(cfg, logic=MachineLogic(actions={"store_user":store_user}))
print("registry:", {k:v.__name__ for k,v in m.logic.actions.items()})
