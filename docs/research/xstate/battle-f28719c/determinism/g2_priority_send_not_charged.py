"""G2 — external priority sends are never charged to the chain budget
(targets R7-02/#180). Fires many `send(priority=True)` events mid-chain
while a self-generated `always`-reenter chain is running; the external
priority sends must not be dropped/counted against maxIterations (only
engine completions + self-raised events count)."""
from __future__ import annotations
import asyncio, logging, sys
logging.disable(logging.CRITICAL)
LIB = "<workspace>/_ref/xstate-statemachine/src"
if LIB not in sys.path:
    sys.path.insert(0, LIB)
from xstate_statemachine import Event, Interpreter, MachineLogic, create_machine  # noqa: E402

CFG = {
    "id": "prio",
    "initial": "loop",
    "context": {"n": 0, "ext": 0},
    "states": {
        "loop": {
            "entry": ["bump"],
            "always": [{"target": "loop", "reenter": True}],
            "on": {"PING": {"actions": ["ext_bump"]}},
        }
    },
}


def bump(i, c, e, a=None):
    c["n"] = c.get("n", 0) + 1


def ext_bump(i, c, e, a=None):
    c["ext"] = c.get("ext", 0) + 1


async def main():
    logic = MachineLogic(actions={"bump": bump, "ext_bump": ext_bump})
    machine = create_machine(CFG, logic=logic)
    interp = Interpreter(machine, max_queue_size=100000)
    await interp.start()

    sent = 0
    errors = 0

    async def sender():
        nonlocal sent, errors
        for _ in range(300):
            try:
                await interp.send(Event("PING"), priority=True)
                sent += 1
            except Exception:
                errors += 1
            await asyncio.sleep(0.001)

    task = asyncio.create_task(sender())
    deadline = asyncio.get_event_loop().time() + 10.0
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.01)
        if interp.last_error is not None:
            break
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    print("sent (accepted, no exception):", sent)
    print("send errors:", errors)
    print("last_error:", interp.last_error)
    print("ctx:", interp.context)


if __name__ == "__main__":
    asyncio.run(main())
