"""#92 claim: create_machine() no longer mutates the caller's MachineLogic.
But the duck-typed branch still calls setattr on the CALLER'S object."""
import sys
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic
CFG={"id":"m","initial":"a","states":{"a":{"entry":["storeUser"]}}}
class DuckLogic:                       # documented as supported ("duck-typed by contract")
    def __init__(self):
        self.actions={"store_user": lambda i,c,e,a: None}
        self.guards={}; self.services={}
d=DuckLogic(); before=dict(d.actions); before_obj=d.actions
create_machine(CFG, logic=d)
print("duck-typed caller's .actions object REPLACED:", d.actions is not before_obj)
print("duck-typed caller's keys mutated:", sorted(d.actions) != sorted(before), "->", sorted(d.actions))
print()
ml=MachineLogic(actions={"store_user": lambda i,c,e,a: None})
keys_before=sorted(ml.actions)
create_machine(CFG, logic=ml)
print("MachineLogic caller keys after 1st machine:", sorted(ml.actions), "(unchanged:", sorted(ml.actions)==keys_before, ")")
