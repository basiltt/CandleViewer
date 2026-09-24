"""#98 makes strict REJECT a user-sent `after.party`. But a v1 snapshot record
restores it with ENGINE provenance -> it is exempt from strict/onUnhandled.
A restore launders exactly the events #98 was added to reject."""
import sys, asyncio, json
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter, SyncInterpreter
from xstate_statemachine.exceptions import UnknownEventError
CFG={"id":"m","strict":True,"initial":"a","onUnhandled":"error","states":{"a":{"on":{"GO":"b"}},"b":{}}}
i=SyncInterpreter(create_machine(CFG, logic=MachineLogic()), strict=True); i.start()
try:
    i.send("after.party"); print("live send: ACCEPTED (unexpected)")
except UnknownEventError: print("live send 'after.party'  -> UnknownEventError (correct, #98)")
snap=i.get_persisted_snapshot()
snap["version"]=1
snap["pending_events"]=[{"type":"after.party","payload":{}}]   # a v1 record
i.stop()
i2=SyncInterpreter.from_snapshot(json.dumps(snap), create_machine(CFG, logic=MachineLogic()))
from xstate_statemachine.events import is_system_event
q=list(i2._event_queue)
print("restored from v1 record  -> system provenance:", is_system_event(q[0]), "type:", type(q[0]).__name__)
print("VERDICT: the same name rejected live is engine-exempt after a restore.")
