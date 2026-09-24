"""R12-03 refutation probe: which forgery vectors need PRIVATE access?
STANDALONE: stdlib + xstate_statemachine. Run from cwd C:/Users/basil."""
import sys, pickle, asyncio
sys.path.insert(0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
import xstate_statemachine as X
from xstate_statemachine import DoneEvent, Event, create_machine, MachineLogic, Interpreter
from xstate_statemachine.events import is_system_event, restore_event

print("public API exports _EngineDone?", "_EngineDone" in dir(X))
# V1: public class alone -> user traffic (fix holds)
print("V1 public DoneEvent is_system:", is_system_event(DoneEvent("done.invoke.svc", 1, "svc")))
# V1b: plain Event + object.__setattr__ private slot (same class of access)
e = Event("X"); 
import xstate_statemachine.events as ev
object.__setattr__(e, "_provenance", ev._ENGINE_MARK)
print("V1b private-slot poke is_system:", is_system_event(e))
# V2: _replace on a genuine engine event (retype)
genuine = ev.engine_done("done.invoke.svc", {"real": 1}, "svc")
retyped = genuine._replace(type="done.invoke.other", data={"forged": 1})
print("V2 _replace retype is_system:", is_system_event(retyped), retyped.type)
# V3: pickle round trip of genuine
print("V3 pickle roundtrip is_system:", is_system_event(pickle.loads(pickle.dumps(genuine))))
# V3b: crafted pickle naming the private class WITHOUT holding one
payload = pickle.dumps(ev._EngineDone("done.invoke.svc", {"forged": 1}, "svc"))
print("V3b crafted pickle bytes name private class:", b"_EngineDone" in payload)
# V4: documented serialization boundary (restore_event) with forged engine flag
rec = {"type": "done.invoke.svc", "kind": "done", "data": {"f": 1}, "src": "svc", "engine": True}
print("V4 restore_event(engine=True) is_system:", is_system_event(restore_event(rec)))
rec2 = dict(rec); rec2.pop("engine")
print("V4b restore_event(no engine flag) is_system:", is_system_event(restore_event(rec2)))
