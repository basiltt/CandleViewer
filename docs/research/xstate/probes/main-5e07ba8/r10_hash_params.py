import sys
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic
from xstate_statemachine.persistence import structure_hash, SNAPSHOT_VERSION
def cfg(amt):
    return {"id":"pay","initial":"a","states":{"a":{"on":{"GO":{"target":"b","actions":[{"type":"assign","params":{"amount":amt}}]}}},"b":{}}}
h1=structure_hash(create_machine(cfg(1), logic=MachineLogic()))
h2=structure_hash(create_machine(cfg(1000000), logic=MachineLogic()))
print("SNAPSHOT_VERSION:", SNAPSHOT_VERSION)
print("hash(amount=1)      :", h1)
print("hash(amount=1000000):", h2)
print("action PARAMS still ignored by machine_hash:", h1==h2)
