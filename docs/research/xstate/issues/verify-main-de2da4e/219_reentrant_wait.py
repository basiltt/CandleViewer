"""VERIFY #219 on de2da4e (STANDALONE; stdlib + xstate_statemachine only).

Claim: an action awaiting send(wait=True) on its OWN interpreter raises
ReentrantWaitError instead of hanging start() forever. Sync engine refuses
the same shape too. A plain send() (wait=False, fire-and-forget) from
inside an action still works, and ensure_future()-then-await-later works.

Exit 0 = all cells pass. Exit 1 = any cell fails / hangs (bounded by
asyncio.wait_for so the script itself never hangs).
"""
import asyncio
import sys

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    ReentrantWaitError,
    SyncInterpreter,
    create_machine,
)

CFG = {
    "id": "dead",
    "initial": "x",
    "states": {
        "x": {"entry": ["act"], "on": {"GO": "y"}},
        "y": {},
    },
}


def _mk(logic):
    return create_machine(CFG, logic=logic)


async def cell_in_step_await_raises(kind):
    seen = []

    async def act_async(i, c, e, a):
        try:
            await i.send("GO", wait=True)
        except ReentrantWaitError as exc:
            seen.append(exc)
            raise

    def act_def(i, c, e, a):
        # a plain def cannot itself await; simulate the same call shape by
        # scheduling the coroutine and awaiting it synchronously via
        # asyncio (not possible from a true sync def) -- so for "def" we
        # instead confirm the guard fires even from a coroutine created
        # inside a def-wrapped action is not representable; skip def here.
        raise NotImplementedError

    logic = MachineLogic(actions={"act": act_async})
    m = _mk(logic)
    i = Interpreter(m)
    try:
        await asyncio.wait_for(i.start(), 5)
        hung = False
    except asyncio.TimeoutError:
        hung = True
    except ReentrantWaitError:
        pass
    if i.status == "running":
        await i.stop()
    ok = (not hung) and len(seen) == 1 and isinstance(seen[0], ReentrantWaitError)
    return ok, hung, [type(e).__name__ for e in seen]


async def cell_ensure_future_then_await_later():
    box = {}

    async def act(i, c, e, a):
        box["fut"] = asyncio.ensure_future(i.send("GO", wait=True))

    m = _mk(MachineLogic(actions={"act": act}))
    i = await Interpreter(m).start()
    r = await asyncio.wait_for(box["fut"], 5)
    v = i.value
    await i.stop()
    return r.error is None and v == "y"


async def cell_fire_and_forget_send_still_works(kind):
    if kind == "async":
        async def act(i, c, e, a):
            await i.send("GO")
    else:
        def act(i, c, e, a):
            i.send("GO")

    m = _mk(MachineLogic(actions={"act": act}))
    i = await Interpreter(m).start()
    await asyncio.sleep(0.05)
    v = i.value
    await i.stop()
    return v == "y"


def cell_sync_engine_refuses():
    seen = []

    def act(i, c, e, a):
        try:
            i.send("GO", wait=True)
        except ReentrantWaitError as exc:
            seen.append(exc)

    s = SyncInterpreter(_mk(MachineLogic(actions={"act": act}))).start()
    ok = len(seen) == 1 and s.value == "x"
    s.send("GO")
    ok = ok and s.value == "y"
    s.stop()
    return ok


def cell_sync_fire_and_forget_works():
    s = SyncInterpreter(
        _mk(MachineLogic(actions={"act": lambda i, c, e, a: i.send("GO")}))
    ).start()
    ok = s.value == "y"
    s.stop()
    return ok


def main():
    fail = False

    ok, hung, names = asyncio.run(cell_in_step_await_raises("async def"))
    print(f"[async in-step await raises] ok={ok} hung={hung} seen={names} {'OK' if ok else 'FAIL'}")
    fail = fail or not ok

    ok = asyncio.run(cell_ensure_future_then_await_later())
    print(f"[async ensure_future-then-await-later] {'OK' if ok else 'FAIL'}")
    fail = fail or not ok

    for kind in ("def", "async"):
        ok = asyncio.run(cell_fire_and_forget_send_still_works(kind))
        print(f"[async fire-and-forget send() from action kind={kind}] {'OK' if ok else 'FAIL'}")
        fail = fail or not ok

    ok = cell_sync_engine_refuses()
    print(f"[sync engine refuses in-step wait=True] {'OK' if ok else 'FAIL'}")
    fail = fail or not ok

    ok = cell_sync_fire_and_forget_works()
    print(f"[sync fire-and-forget send() from action] {'OK' if ok else 'FAIL'}")
    fail = fail or not ok

    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
