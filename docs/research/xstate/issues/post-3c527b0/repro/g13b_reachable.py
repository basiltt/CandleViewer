"""G-13b: end-to-end reachability of the ErrorEvent->payload=exception bug.
Idiom: an onError handler forwards the triggering event to the parent /
raises it onward via a callable event spec `lambda a: a["event"]`."""
import asyncio, warnings, json
from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.interpreter import Interpreter

async def blow(i, c, e): raise ValueError("boom")

PARENT = {"id": "p", "initial": "w", "states": {
    "w": {"invoke": {"src": "kid", "id": "kid"},
          "on": {"error.platform.svc": {"target": "caught", "actions": ["look"]}}},
    "caught": {}}}
CHILD = {"id": "c", "initial": "w", "states": {
    "w": {"invoke": {"src": "svc", "id": "svc",
                     "onError": {"target": "bad", "actions": [
                         {"type": "sendParent", "params": {"event": {"_lambda": True}}}]}}},
    "bad": {"type": "final"}}}

seen = {}
def look(i, c, e, a=None):
    seen["type"] = e.type
    seen["payload"] = repr(e.payload)
    seen["is_dict"] = isinstance(e.payload, dict)

async def main():
    # build the child with a real callable spec
    cfg = json.loads(json.dumps(CHILD))
    cfg["states"]["w"]["invoke"]["onError"]["actions"][0]["params"]["event"] = (
        lambda a: a["event"])            # forward the ErrorEvent upward
    child = create_machine(cfg, logic=MachineLogic(services={"svc": blow}))
    m = create_machine(PARENT, logic=MachineLogic(
        services={"kid": child}, actions={"look": look}))
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        it = await Interpreter(m).start()
        await asyncio.sleep(0.3)
        deps = [x for x in w if issubclass(x.category, DeprecationWarning)]
    print("parent state:", set(it.current_state_ids))
    print("forwarded event seen by parent:", seen)
    print("engine-internal DeprecationWarnings:",
          [f"{x.filename.split(chr(92))[-1]}:{x.lineno}" for x in deps])
    await it.stop()

asyncio.run(main())
