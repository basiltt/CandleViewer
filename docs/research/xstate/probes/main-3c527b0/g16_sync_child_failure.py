"""G-16: SYNC engine -- an invoked CHILD MACHINE that fails.
Async converts it to ErrorEvent (interpreter.py:2028). Does sync?"""
from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.sync_interpreter import SyncInterpreter

def child_blow(i, c, e): raise ValueError("child boom")

seen = []
def look(i, c, e, a=None):
    seen.append((type(e).__name__, e.type, getattr(e, "error", getattr(e, "data", None))))

CHILD = {"id": "c", "initial": "w", "states": {
    "w": {"invoke": {"src": "inner", "id": "inner"}}}}
PARENT = {"id": "p", "initial": "w", "states": {
    "w": {"invoke": {"src": "kid", "id": "kid",
                     "onError": {"target": "bad", "actions": ["look"]}}},
    "bad": {}}}

child = create_machine(CHILD, logic=MachineLogic(services={"inner": child_blow}))
it = SyncInterpreter(create_machine(PARENT, logic=MachineLogic(
    services={"kid": child}, actions={"look": look})))
it.start()
for _ in range(50): it.tick()
print("parent state:", set(it.current_state_ids))
print("parent status:", it.status, "error:", repr(it.error))
print("onError event seen:", seen)
it.stop()
