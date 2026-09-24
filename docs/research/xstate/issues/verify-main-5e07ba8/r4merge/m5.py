import sys, inspect, json
sys.path.insert(0, r"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, SyncInterpreter, MachineLogic
from xstate_statemachine.base_interpreter import BaseInterpreter
print("PERS1 from_snapshot sig:", str(inspect.signature(BaseInterpreter.from_snapshot)))
# OBS-3: deferred replay folds into triggering receipt
m=create_machine({"id":"d","initial":"a","onUnhandled":"defer","states":{
  "a":{"on":{"ARM":"b"}},"b":{"on":{"LATE":"c"}},"c":{}}})
i=SyncInterpreter(m); i.start()
r0=i.send("LATE", wait=True); print("OBS3 LATE receipt:", r0)
r1=i.send("ARM", wait=True); print("OBS3 ARM receipt:", r1, "states now:", i.current_state_ids)
# OBS-5: strict_targets=False unresolved target -> no plugin hook
class P:
    def __init__(s): s.calls=[]
    def __getattr__(s,n):
        if n.startswith("on_"):
            def f(*a,**k): s.calls.append(n)
            return f
        raise AttributeError(n)
m2=create_machine({"id":"s","strict_targets":False,"initial":"a","states":{"a":{"on":{"GO":"nowhere"}}}})
p=P(); i2=SyncInterpreter(m2); i2.use(p); i2.start()
r=i2.send("GO", wait=True)
print("OBS5 receipt:", r, "last_error:", i2.last_error, "hooks:", sorted(set(p.calls)))
# OBS-7
m3=create_machine({"id":"v","initial":"a","states":{"a":{"invoke":{"src":"svc","id":"svc","onDone":"b"}},"b":{}}}, logic=MachineLogic(services={"svc":lambda c,e: 1}))
i3=SyncInterpreter(m3); i3.start(); snap=i3.get_persisted_snapshot()
i4=SyncInterpreter.from_snapshot(snap, m3, restart_services=True)
print("OBS7 before start: status=", i4.status, "dormant=", i4.has_dormant_invocations)
i4.start(); print("OBS7 after start: dormant=", i4.has_dormant_invocations)
