"""P2 (#206): does the new charging cut a LEGITIMATE timer-paced heartbeat?

#206 makes a `raise(delay=)` to self a debt of the arming step and charges
its firing as engine work, so a 1 ms ping-pong now trips `maxIterations`.
That is the intended fix. The risk is the legitimate shape that looks
identical to the accounting: a self re-arming HEARTBEAT / poller on a real
delay, with no external traffic to reset the chain depth.

Q1: async engine, a 30 ms self re-arming heartbeat, maxIterations=8 --
    does it run forever or get cut as `chain_budget`? def + async def.
Q2: the same chart on SyncInterpreter driven by tick() -- parity?
Q3: does interleaved EXTERNAL traffic rescue the async heartbeat?

Compare 19cb1f1 against f28719c by passing that tree's src as argv[1].

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import json
import sys
import time

SRC = sys.argv[1] if len(sys.argv) > 1 else (
    r"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref"
    r"/xstate-statemachine/src"
)
sys.path.insert(0, SRC)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

HB = 30  # ms: a real delay, well above any zero-delay cycle
CFG = {
    "id": "hb",
    "initial": "up",
    "maxIterations": 8,
    "context": {"n": 0},
    "states": {
        "up": {
            "entry": [
                "beat",
                {"type": "raise", "params": {"event": "TICK", "delay": HB}},
            ],
            "on": {"TICK": "down", "X": {}},
        },
        "down": {
            "entry": [
                "beat",
                {"type": "raise", "params": {"event": "TICK", "delay": HB}},
            ],
            "on": {"TICK": "up", "X": {}},
        },
    },
}


class _Drops(PluginBase):
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, interp, event, reason):
        self.dropped.append((event.type, reason))


def _beat(kind):
    def beat(i, c, e, a):
        c["n"] = c["n"] + 1

    async def abeat(i, c, e, a):
        beat(i, c, e, a)

    return abeat if kind == "async def" else beat


def _mk(kind):
    return create_machine(
        json.loads(json.dumps(CFG)),
        logic=MachineLogic(actions={"beat": _beat(kind)}),
    )


async def q_async(kind, external=False):
    d = _Drops()
    i = Interpreter(_mk(kind)).use(d)
    await i.start()
    for n in range(24):  # ~1.2 s, well under the 120 s bound
        await asyncio.sleep(0.05)
        if external and n % 4 == 3:
            i.send("X")
        if d.dropped:
            break
    out = (i.context["n"], [r for _, r in d.dropped][:2], type(i.last_error))
    await i.stop()
    return out


def q_sync():
    d = _Drops()
    i = SyncInterpreter(_mk("def")).use(d)
    i.start()
    deadline = time.monotonic() + 1.2
    while time.monotonic() < deadline and not d.dropped:
        time.sleep(0.02)
        i.tick()
    return i.context["n"], [r for _, r in d.dropped][:2], type(i.last_error)


def _run(c):
    return asyncio.new_event_loop().run_until_complete(c)


if __name__ == "__main__":
    print("SRC:", SRC)
    for k in ("def", "async def"):
        print(f"Q1 async heartbeat [{k:9}] :", _run(q_async(k)))
    print("Q2 sync tick() heartbeat    :", q_sync())
    print("Q3 async + external traffic :", _run(q_async("def", True)))
