"""STANDALONE: `last_error` is the ONLY surface a chain trip reaches
(#212/R10-13) and a later benign event CLEARS it.

Both engines, both action kinds.  The trip is a silent, self-healing
signal: `interpreter.error` stays None, `status` stays "running", and
one unrelated send() erases the only evidence.
"""

import asyncio
import time

from xstate_statemachine import create_machine, Interpreter, MachineLogic
from xstate_statemachine.sync_interpreter import SyncInterpreter

CFG = {
    "id": "z", "initial": "a", "context": {"n": 0}, "maxIterations": 12,
    "states": {
        "a": {"entry": [{"type": "inc"},
                        {"type": "raise", "params": {"event": "P"}}],
              "on": {"P": {"target": "b"}, "NOOP": {}}},
        "b": {"entry": [{"type": "inc"},
                        {"type": "raise", "params": {"event": "P"}}],
              "on": {"P": {"target": "a"}, "NOOP": {}}},
    },
}


def inc(i, c, e, a):
    c["n"] = c.get("n", 0) + 1


async def inc_a(i, c, e, a):
    c["n"] = c.get("n", 0) + 1


def name(x):
    return type(x).__name__ if x is not None else None


def sync_case(kind):
    m = create_machine(dict(CFG), logic=MachineLogic(actions={"inc": inc}))
    it = SyncInterpreter(m).start()
    before = name(getattr(it, "last_error", None))
    err = name(it.error)
    st = it.status
    it.send("NOOP")
    after = name(getattr(it, "last_error", None))
    it.stop()
    print("SYNC/%s  last_error@trip=%s  interpreter.error=%s status=%s  "
          "last_error after ONE benign send()=%s"
          % (kind, before, err, st, after), flush=True)


async def async_case(kind):
    impl = inc if kind == "def" else inc_a
    m = create_machine(dict(CFG), logic=MachineLogic(actions={"inc": impl}))
    it = await Interpreter(m).start()
    await asyncio.sleep(0.15)
    before = name(getattr(it, "last_error", None))
    err = name(it.error)
    st = it.status
    await it.send("NOOP")
    await asyncio.sleep(0.05)
    after = name(getattr(it, "last_error", None))
    await it.stop()
    print("ASYNC/%s last_error@trip=%s  interpreter.error=%s status=%s  "
          "last_error after ONE benign send()=%s"
          % (kind, before, err, st, after), flush=True)


# hooks: does ANY hook observe the trip?
class Spy:
    def __init__(self):
        self.calls = []

    def __getattr__(self, n):
        if n.startswith("on_"):
            def f(*a, **k):
                self.calls.append(n)
            return f
        raise AttributeError(n)


async def hook_case():
    spy = Spy()
    m = create_machine(dict(CFG), logic=MachineLogic(actions={"inc": inc}))
    it = Interpreter(m)
    try:
        it.use(spy)
    except Exception as exc:  # noqa: BLE001
        print("hook attach failed:", exc, flush=True)
    await it.start()
    await asyncio.sleep(0.15)
    print("HOOKS fired on a chain trip:", sorted(set(spy.calls)), flush=True)
    await it.stop()


if __name__ == "__main__":
    sync_case("def")
    asyncio.run(async_case("def"))
    asyncio.run(async_case("async"))
    asyncio.run(hook_case())
