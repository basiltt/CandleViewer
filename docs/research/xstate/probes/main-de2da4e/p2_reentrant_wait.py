"""P2 (#219): ReentrantWaitError -- exact detection surface.

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.

Cases
  A  async action awaits its own send(wait=True)        -> expect refusal
  B  sync  action calls  its own send(wait=True)        -> expect refusal
  C  documented idiom: ensure_future(send(wait=True)),
     awaited after the action returned                  -> expect OK
  C2 same, but the loop is busy so the receipt is NOT
     resolved when the wrapper task first runs          -> ? (contextvar
     copy still carries the action owner)
  D  a task spawned INSIDE the action that awaits the
     receipt after the action returned                  -> ?
  E  async: a CHILD actor's action awaits PARENT
     .send(wait=True)                                   -> ? (cross-machine)
  F  sync : a CHILD actor's action calls PARENT
     .send(wait=True)                                   -> ? (parity)
"""
import asyncio
import sys

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import ReentrantWaitError

CFG = {
    "id": "m",
    "initial": "x",
    "states": {
        "x": {"entry": ["act"], "on": {"GO": "y"}},
        "y": {},
    },
}


def _mk(actions):
    return create_machine(CFG, logic=MachineLogic(actions=actions))


def _label(exc):
    return "OK" if exc is None else f"{type(exc).__name__}"


# --------------------------------------------------------------------- A / C
async def _case_a():
    seen = []

    async def act(i, c, e, a):
        try:
            await i.send("GO", wait=True)
        except BaseException as exc:  # noqa: BLE001
            seen.append(exc)

    i = Interpreter(_mk({"act": act}))
    try:
        await asyncio.wait_for(i.start(), 5)
    except BaseException as exc:  # noqa: BLE001
        seen.append(exc)
    await asyncio.sleep(0.05)
    v = i.value
    if i.status == "running":
        await i.stop()
    return _label(seen[0] if seen else None), v


async def _case_c():
    box = {}

    async def act(i, c, e, a):
        box["fut"] = asyncio.ensure_future(i.send("GO", wait=True))

    i = await asyncio.wait_for(Interpreter(_mk({"act": act})).start(), 5)
    try:
        r = await asyncio.wait_for(box["fut"], 3)
        out = _label(getattr(r, "error", None))
    except BaseException as exc:  # noqa: BLE001
        out = _label(exc)
    v = i.value
    await i.stop()
    return out, v


async def _case_c2():
    """Same idiom, but a slow follow-up action keeps the loop inside the
    action context long enough that the wrapper task runs first."""
    box = {}

    async def act(i, c, e, a):
        box["fut"] = asyncio.ensure_future(i.send("GO", wait=True))
        await asyncio.sleep(0.05)  # yield: the wrapper task runs NOW

    i = Interpreter(_mk({"act": act}))
    try:
        await asyncio.wait_for(i.start(), 5)
    except BaseException:  # noqa: BLE001
        pass
    try:
        r = await asyncio.wait_for(box["fut"], 3)
        out = _label(getattr(r, "error", None))
    except BaseException as exc:  # noqa: BLE001
        out = _label(exc)
    v = i.value
    if i.status == "running":
        await i.stop()
    return out, v


async def _case_d():
    """A helper task spawned inside the action, awaiting after a yield."""
    box = {}

    async def act(i, c, e, a):
        async def helper():
            await asyncio.sleep(0.02)
            return await i.send("GO", wait=True)

        box["fut"] = asyncio.ensure_future(helper())

    i = Interpreter(_mk({"act": act}))
    try:
        await asyncio.wait_for(i.start(), 5)
    except BaseException:  # noqa: BLE001
        pass
    try:
        r = await asyncio.wait_for(box["fut"], 3)
        out = _label(getattr(r, "error", None))
    except BaseException as exc:  # noqa: BLE001
        out = _label(exc)
    v = i.value
    if i.status == "running":
        await i.stop()
    return out, v


# ------------------------------------------------------------------------- B
def _case_b():
    seen = []

    def act(i, c, e, a):
        try:
            i.send("GO", wait=True)
        except BaseException as exc:  # noqa: BLE001
            seen.append(exc)

    s = SyncInterpreter(_mk({"act": act})).start()
    v = s.value
    s.stop()
    return _label(seen[0] if seen else None), v


# ----------------------------------------------------------------- E / F
PARENT = {
    "id": "p",
    "initial": "run",
    "states": {
        "run": {
            "invoke": {"id": "kid", "src": "kid"},
            "on": {"FROM_KID": "done"},
        },
        "done": {"type": "final"},
    },
}
CHILD = {
    "id": "k",
    "initial": "a",
    "states": {"a": {"entry": ["ping"]}},
}


async def _case_e():
    seen = []
    parent_box = {}

    async def ping(i, c, e, a):
        try:
            await parent_box["p"].send("FROM_KID", wait=True)
        except BaseException as exc:  # noqa: BLE001
            seen.append(exc)

    child = create_machine(CHILD, logic=MachineLogic(actions={"ping": ping}))
    p = Interpreter(create_machine(PARENT, logic=MachineLogic(services={"kid": child})))
    parent_box["p"] = p
    try:
        await asyncio.wait_for(p.start(), 5)
        await asyncio.sleep(0.2)
    except BaseException as exc:  # noqa: BLE001
        seen.append(exc)
    v = p.value
    if p.status == "running":
        await p.stop()
    return _label(seen[0] if seen else None), v


def _case_f():
    seen = []
    parent_box = {}

    def ping(i, c, e, a):
        try:
            parent_box["p"].send("FROM_KID", wait=True)
        except BaseException as exc:  # noqa: BLE001
            seen.append(exc)

    child = create_machine(CHILD, logic=MachineLogic(actions={"ping": ping}))
    p = SyncInterpreter(
        create_machine(PARENT, logic=MachineLogic(services={"kid": child}))
    )
    parent_box["p"] = p
    p.start()
    v = p.value
    p.stop()
    return _label(seen[0] if seen else None), v


def main():
    print("A  async self-await        ->", asyncio.run(_case_a()))
    print("B  sync  self-call         ->", _case_b())
    print("C  ensure_future idiom     ->", asyncio.run(_case_c()))
    print("C2 ensure_future + yield   ->", asyncio.run(_case_c2()))
    print("D  helper task in action   ->", asyncio.run(_case_d()))
    try:
        print("E  child->parent async     ->", asyncio.run(_case_e()))
    except Exception as exc:  # noqa: BLE001
        print("E  child->parent async     -> HARNESS", type(exc).__name__, exc)
    try:
        print("F  child->parent sync      ->", _case_f())
    except Exception as exc:  # noqa: BLE001
        print("F  child->parent sync      -> HARNESS", type(exc).__name__, exc)
    print("ReentrantWaitError:", ReentrantWaitError.__name__)


if __name__ == "__main__":
    sys.exit(main())
