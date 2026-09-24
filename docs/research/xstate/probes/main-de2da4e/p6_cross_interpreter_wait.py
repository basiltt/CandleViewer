"""P6 (#219 follow-up): cross-interpreter send(wait=True) is NOT refused.

The #219 guard keys on `_ACTIVE_ACTION_OWNER.get() is self`, i.e. the
receipt's OWN interpreter. A child actor's action awaiting
parent.send(..., wait=True) is a DIFFERENT interpreter, so it is allowed.
This probe asks whether that shape is safe (does the parent's loop advance
while the child action is parked?) on both engines.

Non-final parent target, so nothing is cancelled by an auto-stop.

STANDALONE: stdlib + xstate_statemachine only.
"""
import asyncio
import sys

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

PARENT = {
    "id": "p",
    "initial": "run",
    "states": {
        "run": {
            "invoke": {"id": "kid", "src": "kid"},
            "initial": "s1",
            "states": {"s1": {"on": {"FROM_KID": "s2"}}, "s2": {}},
        },
    },
}
CHILD = {"id": "k", "initial": "a", "states": {"a": {"entry": ["ping"]}}}


async def _async():
    out = {}
    box = {}

    async def ping(i, c, e, a):
        try:
            r = await asyncio.wait_for(
                box["p"].send("FROM_KID", wait=True), 3
            )
            out["res"] = f"receipt changed={getattr(r, 'changed', '?')}"
        except BaseException as exc:  # noqa: BLE001
            out["res"] = f"{type(exc).__name__}"

    child = create_machine(CHILD, logic=MachineLogic(actions={"ping": ping}))
    p = Interpreter(create_machine(PARENT, logic=MachineLogic(services={"kid": child})))
    box["p"] = p
    await asyncio.wait_for(p.start(), 5)
    await asyncio.sleep(1.0)
    v = p.value
    await p.stop()
    return out.get("res", "<never ran>"), v


def _sync():
    out = {}
    box = {}

    def ping(i, c, e, a):
        try:
            r = box["p"].send("FROM_KID", wait=True)
            out["res"] = f"receipt changed={getattr(r, 'changed', '?')}"
        except BaseException as exc:  # noqa: BLE001
            out["res"] = f"{type(exc).__name__}"

    child = create_machine(CHILD, logic=MachineLogic(actions={"ping": ping}))
    p = SyncInterpreter(
        create_machine(PARENT, logic=MachineLogic(services={"kid": child}))
    )
    box["p"] = p
    p.start()
    v = p.value
    p.stop()
    return out.get("res", "<never ran>"), v


def main():
    print("async child->parent wait=True (child NOT torn down):", asyncio.run(_async()))
    print("sync  child->parent wait=True (child NOT torn down):", _sync())


if __name__ == "__main__":
    sys.exit(main())
