"""G-15: `escalate` is the one failure path #80 did NOT convert. It still
delivers a plain `Event` with the exception under `payload['error']`, so the
`isinstance(event, ErrorEvent)` / `event.error` contract the CHANGELOG
advertises does not hold for escalated failures."""
import asyncio
from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.events import ErrorEvent
from xstate_statemachine.interpreter import Interpreter

seen = {}
def look(i, c, e, a=None):
    seen.update(cls=type(e).__name__, type=e.type,
                has_error_attr=hasattr(e, "error"),
                payload=repr(getattr(e, "payload", None)))

CHILD = {"id": "c", "initial": "w", "states": {"w": {"entry": [
    {"type": "escalate", "params": {"error": "child exploded"}}]}}}
PARENT = {"id": "p", "initial": "w", "states": {
    "w": {"invoke": {"src": "kid", "id": "kid"},
          "on": {"xstate.error.actor.p:kid": {"target": "caught", "actions": ["look"]}}},
    "caught": {}}}

async def main():
    child = create_machine(CHILD, logic=MachineLogic())
    m = create_machine(PARENT, logic=MachineLogic(services={"kid": child},
                                                  actions={"look": look}))
    it = await Interpreter(m).start()
    await asyncio.sleep(0.3)
    print("parent state:", set(it.current_state_ids))
    print("escalated event as seen by the handler:", seen)
    print("isinstance(ErrorEvent)?", seen.get("cls") == "ErrorEvent")
    await it.stop()

asyncio.run(main())
