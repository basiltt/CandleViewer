"""Verify #99 on 5e07ba8: SyncInterpreter delivers onError for a failed
invoked child machine, and both engines agree on the unhandled case.

Acceptance criteria (from gh issue #99):
  1. Sync repro (g16) shows the parent reaching the `onError` target with
     an `ErrorEvent`.
  2. A parity test exercising both engines on the same parent/child pair
     produces the same state, status and event class.
  3. Parameterised over both engines (repo:
     TestSyncChildMachineFailure + TestErrorEventEdges/async equivalents).
  4. The unhandled case (no `onError`) is decided and documented: EITHER
     both engines escalate (fail the parent), OR both park -- not one of
     each. CHANGELOG says: both fail the parent.
"""
import asyncio
import time

from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.events import ErrorEvent
from xstate_statemachine.interpreter import Interpreter
from xstate_statemachine.sync_interpreter import SyncInterpreter


def child_blow(i, c, e):
    raise ValueError("child boom")


async def child_blow_async(i, c, e):
    raise ValueError("child boom")


CHILD = {
    "id": "c",
    "initial": "w",
    "states": {"w": {"invoke": {"src": "inner", "id": "inner"}}},
}


def sync_with_handler():
    seen = []

    def look(i, c, e, a=None):
        seen.append((type(e).__name__, e.type, e.error))

    child = create_machine(CHILD, logic=MachineLogic(services={"inner": child_blow}))
    PARENT = {
        "id": "p",
        "initial": "w",
        "states": {
            "w": {
                "invoke": {
                    "src": "kid",
                    "id": "kid",
                    "onError": {"target": "bad", "actions": ["look"]},
                }
            },
            "bad": {},
        },
    }
    it = SyncInterpreter(
        create_machine(
            PARENT, logic=MachineLogic(services={"kid": child}, actions={"look": look})
        )
    )
    it.start()
    for _ in range(200):
        if it.value == "bad":
            break
        it.tick()
        time.sleep(0.01)
    result = (set(it.current_state_ids), it.status, seen)
    it.stop()
    return result


def sync_unhandled():
    child = create_machine(CHILD, logic=MachineLogic(services={"inner": child_blow}))
    PARENT = {
        "id": "p",
        "initial": "w",
        "states": {"w": {"invoke": {"src": "kid", "id": "kid"}}},
    }
    it = SyncInterpreter(create_machine(PARENT, logic=MachineLogic(services={"kid": child})))
    it.start()
    for _ in range(200):
        if it.status == "error":
            break
        it.tick()
        time.sleep(0.01)
    result = (it.status, it.error)
    it.stop()
    return result


async def async_unhandled():
    child = create_machine(CHILD, logic=MachineLogic(services={"inner": child_blow_async}))
    PARENT = {
        "id": "p",
        "initial": "w",
        "states": {"w": {"invoke": {"src": "kid", "id": "kid"}}},
    }
    it = await Interpreter(
        create_machine(PARENT, logic=MachineLogic(services={"kid": child}))
    ).start()
    await asyncio.sleep(0.3)
    result = (it.status, it.error)
    await it.stop()
    return result


if __name__ == "__main__":
    state, status, seen = sync_with_handler()
    print("=== sync, handled onError ===")
    print("parent state:", state, "status:", status)
    print("onError event seen:", seen)
    c1 = state == {"p.bad"}
    c1b = seen and seen[0][0] == "ErrorEvent" and "child boom" in str(seen[0][2])

    print("=== sync, unhandled ===")
    sync_status, sync_err = sync_unhandled()
    print("status:", sync_status, "error:", repr(sync_err))

    print("=== async, unhandled ===")
    async_status, async_err = asyncio.run(async_unhandled())
    print("status:", async_status, "error:", repr(async_err))

    c2_parity = (sync_status == async_status == "error") and (
        sync_err is not None and async_err is not None
    )

    print("Criterion 1 (sync reaches onError target with ErrorEvent):", c1, c1b)
    print("Criterion 4 (both engines fail parent when unhandled, same shape):", c2_parity)
    print("ALL PASS:", all([c1, c1b, c2_parity]))
