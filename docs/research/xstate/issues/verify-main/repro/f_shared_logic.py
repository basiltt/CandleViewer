from xstate_statemachine import create_machine, MachineLogic
def impl(i,c,e,a): pass
logic=MachineLogic(actions={"store_user":impl})
m1=create_machine({"id":"m1","initial":"a","states":{"a":{"entry":["storeUser"]}}}, logic=logic)
print("after m1, keys:", sorted(logic.actions))
# a second machine that references a DIFFERENT camel name
m2=create_machine({"id":"m2","initial":"a","states":{"a":{"entry":["STOREUSER"]}}}, logic=logic)
print("after m2, keys:", sorted(logic.actions))
