"""Lap-parity probe: the invoke ping-pong (ver -> arm -> ver) must trip at the
SAME lap count on both engines. Async trips AFTER send(wait=True) returns.
"""

from __future__ import annotations

import asyncio
import logging

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

logging.disable(logging.CRITICAL)

CFG = {
    "id": "f", "initial": "idle",
    "states": {
        "idle": {"on": {"GO": "ver"}},
        "ver": {"invoke": {"src": "svc", "onDone": "arm"}},
        "arm": {"invoke": {"src": "svc", "onDone": "ver"}},
    },
}
laps = {"n": 0}


def L() -> MachineLogic:
    def svc(i_, c, e):  # noqa: ANN001
        laps["n"] += 1
        return 1

    return MachineLogic(services={"svc": svc})


class S(PluginBase):
    def __init__(self) -> None:
        self.d = []

    def on_event_dropped(self, i, e, r):  # noqa: ANN001
        self.d.append(r)


async def amain() -> None:
    laps["n"] = 0
    sp = S()
    i = await Interpreter(create_machine(CFG, logic=L())).use(sp).start()
    await asyncio.wait_for(i.send("GO", wait=True), 20)
    print(f"async at send() return : laps={laps['n']} drops={sp.d}")
    await asyncio.sleep(3.0)
    print(f"async +3s              : laps={laps['n']} drops={sp.d} "
          f"err={type(i.last_error).__name__ if i.last_error else None}")
    await i.stop()

    laps["n"] = 0
    sp2 = S()
    s = SyncInterpreter(create_machine(CFG, logic=L())).use(sp2).start()
    s.send("GO")
    print(f"sync                   : laps={laps['n']} drops={sp2.d} "
          f"err={type(s.last_error).__name__ if s.last_error else None}")
    s.stop()


if __name__ == "__main__":
    asyncio.run(amain())
