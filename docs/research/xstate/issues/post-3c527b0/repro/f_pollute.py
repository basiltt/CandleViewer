from xstate_statemachine import create_machine, MachineLogic
def store_user(i,c,e,a): pass
def storeUser(i,c,e,a): pass
logic=MachineLogic(actions={"store_user":store_user})
m1=create_machine({"id":"m1","initial":"a","states":{"a":{"entry":["storeUser"]}}}, logic=logic)
print("m1 ok, registry now:", sorted(logic.actions))
# Later, the app registers the real camelCase impl -> now AMBIGUOUS for a 3rd machine
logic.actions["STOREUSER"]=storeUser
try:
    m2=create_machine({"id":"m2","initial":"a","states":{"a":{"entry":["Store_User"]}}}, logic=logic)
    print("m2 bound to:", m2.logic.actions["Store_User"].__name__)
except Exception as e:
    print("m2 ERR:", type(e).__name__, str(e)[:160])
