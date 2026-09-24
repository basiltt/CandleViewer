"""Verify #97 on 5e07ba8: `escalate` delivers `ErrorEvent`.

Acceptance criteria (from gh issue #97):
  1. An escalated child failure delivers `isinstance(event, ErrorEvent)`
     with `.error` carrying the escalated payload -- or docs state the
     `escalate` shape separately and explicitly.
  2. Invoke-failure and `escalate` handlers can be written against ONE
     documented accessor (`event.error`).
  3. Test: `test_escalate_delivers_error_event` (repo names it
     `test_escalate_is_an_error_event`, tests/test_round3_findings.py).

Also checks the CHANGELOG's specific claim: `event.type` is unchanged
(still `xstate.error.actor.<parent-id>:<child-id>`), only the class/accessor
changed, so the "aside" about the exact-key `on` requirement is unaffected.
"""
import asyncio
from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.events import ErrorEvent
from xstate_statemachine.interpreter import Interpreter

seen = {}


def look(i, c, e, a=None):
    seen.update(
        cls=type(e).__name__,
        type=e.type,
        has_error_attr=hasattr(e, "error"),
        error=repr(getattr(e, "error", None)),
        payload=repr(getattr(e, "payload", None)),
    )


CHILD = {
    "id": "c",
    "initial": "w",
    "states": {
        "w": {
            "entry": [
                {"type": "escalate", "params": {"error": "child exploded"}}
            ]
        }
    },
}
PARENT = {
    "id": "p",
    "initial": "w",
    "states": {
        "w": {
            "invoke": {"src": "kid", "id": "kid"},
            "on": {
                "xstate.error.actor.p:kid": {
                    "target": "caught",
                    "actions": ["look"],
                }
            },
        },
        "caught": {},
    },
}


async def main():
    child = create_machine(CHILD, logic=MachineLogic())
    m = create_machine(
        PARENT,
        logic=MachineLogic(
            services={"kid": child}, actions={"look": look}
        ),
    )
    it = await Interpreter(m).start()
    await asyncio.sleep(0.3)
    state = set(it.current_state_ids)
    await it.stop()
    return state


if __name__ == "__main__":
    state = asyncio.run(main())
    print("parent state:", state)
    print("escalated event as seen by handler:", seen)
    c1 = seen.get("cls") == "ErrorEvent"
    c2 = seen.get("has_error_attr") is True
    c3 = "child exploded" in seen.get("error", "")
    c4 = seen.get("type") == "xstate.error.actor.p:kid"  # type unchanged
    print("Criterion 1 (isinstance ErrorEvent):", c1)
    print("Criterion 1b (.error carries payload):", c2, c3)
    print("Criterion 2 (type/key unchanged, same doc accessor):", c4)
    print("ALL PASS:", all([c1, c2, c3, c4]))
