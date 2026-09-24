"""P7 (#219 false positive): the guard keys on the TASK'S CONTEXT COPY, not
on "the action is still running".

`asyncio.ensure_future(...)` copies the current contextvars, so a task
created inside an action keeps `_ACTIVE_ACTION_OWNER is self` FOR EVER --
long after the action has returned. The guard fires when that task awaits
the receipt before the loop has processed the event:

    if _ACTIVE_ACTION_OWNER.get() is self and not receipt.done():
        raise ReentrantWaitError

No deadlock is possible in that window (the action returned; the loop is
free to advance), so this is a refusal of a legal shape -- and it is the
very "hand the receipt out and await it later" idiom the 0.8.1 docs
recommend, which works only when the task happens to be scheduled AFTER
the loop drained the event.

STANDALONE: stdlib + xstate_statemachine only.
"""
import asyncio
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {
    "id": "m",
    "initial": "x",
    "states": {"x": {"entry": ["act"], "on": {"GO": "y"}}, "y": {}},
}


async def run(mode):
    """mode: 'inside'  -> helper task born inside the action (context copied)
    'outside' -> the same await, from a task born before the action."""
    box = {}
    done = asyncio.Event()

    async def helper(aw):
        try:
            r = await asyncio.wait_for(aw, 3)
            box["res"] = f"OK changed={getattr(r, 'changed', '?')}"
        except BaseException as exc:  # noqa: BLE001
            box["res"] = type(exc).__name__
        finally:
            done.set()

    async def act(i, c, e, a):
        aw = i.send("GO", wait=True)  # receipt created inside the action
        box["action_returned"] = True
        if mode == "inside":
            asyncio.ensure_future(helper(aw))
        else:
            # same receipt, awaited from a task whose context was copied
            # BEFORE any action ran
            ctx_free = asyncio.get_running_loop().create_task(
                helper(aw), context=None
            ) if sys.version_info >= (3, 11) else asyncio.ensure_future(helper(aw))
            box["task"] = ctx_free
        # the action returns immediately: no deadlock is possible after this

    i = Interpreter(create_machine(CFG, logic=MachineLogic(actions={"act": act})))
    try:
        await asyncio.wait_for(i.start(), 5)
    except BaseException as exc:  # noqa: BLE001
        box.setdefault("res", f"start:{type(exc).__name__}")
    try:
        await asyncio.wait_for(done.wait(), 3)
    except asyncio.TimeoutError:
        box.setdefault("res", "TIMEOUT")
    v = i.value
    if i.status == "running":
        await i.stop()
    return box.get("res"), v


BG_CFG = {
    "id": "bg",
    "initial": "x",
    "states": {"x": {"entry": ["act"], "on": {"GO": "y"}}, "y": {}},
}


async def background_send():
    """The clearest false positive: a background task SPAWNED by an action
    issues its own `send(wait=True)` LONG after that action returned and the
    machine went idle. Nothing can deadlock -- the loop is not in a step --
    but the task inherited `_ACTIVE_ACTION_OWNER` from the action that
    created it, so the guard fires."""
    box = {}
    done = asyncio.Event()

    async def worker(i):
        await asyncio.sleep(0.3)          # machine is long idle by now
        try:
            r = await asyncio.wait_for(i.send("GO", wait=True), 3)
            box["res"] = f"OK changed={getattr(r, 'changed', '?')}"
        except BaseException as exc:      # noqa: BLE001
            box["res"] = type(exc).__name__
        finally:
            done.set()

    async def act(i, c, e, a):
        asyncio.ensure_future(worker(i))  # long-lived helper, docs' pattern

    i = await asyncio.wait_for(
        Interpreter(
            create_machine(BG_CFG, logic=MachineLogic(actions={"act": act}))
        ).start(),
        5,
    )
    try:
        await asyncio.wait_for(done.wait(), 3)
    except asyncio.TimeoutError:
        box["res"] = "TIMEOUT"
    v = i.value
    await i.stop()
    return box.get("res"), v


async def slow_action():
    """Docs' own `ensure_future` idiom, but the action yields afterwards, so
    the wrapper task runs while the action is still on the stack. The await
    WOULD have completed ~50 ms later (the action returns, the loop drains
    GO); it is refused instead."""
    box = {}

    async def act(i, c, e, a):
        box["fut"] = asyncio.ensure_future(i.send("GO", wait=True))
        await asyncio.sleep(0.05)

    i = Interpreter(create_machine(CFG, logic=MachineLogic(actions={"act": act})))
    try:
        await asyncio.wait_for(i.start(), 5)
    except BaseException:  # noqa: BLE001
        pass
    try:
        r = await asyncio.wait_for(box["fut"], 3)
        box["res"] = f"OK changed={getattr(r, 'changed', '?')}"
    except BaseException as exc:  # noqa: BLE001
        box["res"] = type(exc).__name__
    v = i.value
    if i.status == "running":
        await i.stop()
    return box["res"], v


def main():
    print("helper task born INSIDE the action :", asyncio.run(run("inside")))
    print("helper with a FRESH context        :", asyncio.run(run("outside")))
    print("bg task sends 300 ms after idle    :", asyncio.run(background_send()))
    print("docs idiom + action yields         :", asyncio.run(slow_action()))
    print(
        "\nA 'ReentrantWaitError' on any line above, with the action already "
        "returned, is a refusal of a shape that cannot deadlock."
    )


if __name__ == "__main__":
    sys.exit(main())
