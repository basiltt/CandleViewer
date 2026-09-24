"""L-2 probe: #171 makes start() await invoked-child bring-up. Can a child
whose own start() never returns hang the parent's await start() for ever?

_await_actor_bringups() gathers the bring-up tasks with no timeout. The
bring-up coroutine _start_invoked_actor awaits child.start(); an entry
action on the child that awaits (a lock, a socket, a slow resolver) is
user code, and before #171 start() returned regardless.
"""

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CHILD = {
    "id": "kid",
    "initial": "boot",
    "states": {"boot": {"entry": ["slow_entry"], "on": {"GO": {}}}},
}

PARENT = {
    "id": "p2",
    "initial": "up",
    "states": {
        "up": {
            "invoke": {"src": "kid", "id": "kid"},
            "on": {"POKE": {}},
        }
    },
}


async def slow_entry(interp, ctx, ev, action_def):  # noqa: ANN001
    await asyncio.sleep(30)  # stands in for any blocking user entry action


async def main() -> None:
    child = create_machine(
        CHILD, logic=MachineLogic(actions={"slow_entry": slow_entry})
    )
    parent = create_machine(PARENT, logic=MachineLogic(services={"kid": child}))
    interp = Interpreter(parent)
    t0 = asyncio.get_running_loop().time()
    try:
        await asyncio.wait_for(interp.start(), timeout=8.0)
        print(f"start() returned in {asyncio.get_running_loop().time()-t0:.2f}s")
        print("VERDICT: start() does not hang")
    except asyncio.TimeoutError:
        print(f"start() still not returned after 8s (child entry sleeps 30s)")
        print(f"status={interp.status}")
        print("VERDICT: START() HANGS ON A SLOW INVOKED CHILD (no timeout)")
    finally:
        try:
            await asyncio.wait_for(interp.stop(), timeout=3)
        except Exception as exc:  # noqa: BLE001
            print(f"stop() also blocked: {type(exc).__name__}")


asyncio.run(main())
