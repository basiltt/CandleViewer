"""#91 shadowed near-duplicates warn; #93 logic_modules ambiguity."""
import sys, warnings
sys.path.insert(0,"<workspace>/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic
CFG={"id":"m","initial":"a","states":{"a":{"entry":["storeUser"]}}}
a=lambda i,c,e,ad: "A"; b=lambda i,c,e,ad: "B"
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    m=create_machine(CFG, logic=MachineLogic(actions={"storeUser":a,"store_user":b}))
    print("warnings:", [str(x.message)[:90] for x in w])
    print("which callable runs:", "A" if m.logic.actions["storeUser"] is a else "B")
