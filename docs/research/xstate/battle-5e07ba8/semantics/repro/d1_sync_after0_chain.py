"""D-semantics repro: SyncInterpreter `after: 0` chain advances one state
per `tick()` instead of settling.

Async settles the whole chain; sync needs N ticks for N links, and a caller
that ticks once per real-time poll silently lags behind.
"""

from __future__ import annotations

import logging
import time

logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

CFG = {
    "id": "m",
    "initial": "a",
    "states": {
        "a": {"after": {0: "b"}},
        "b": {"after": {0: "c"}},
        "c": {"after": {0: "d"}},
        "d": {},
    },
}


def main() -> None:
    m = create_machine(CFG, logic=MachineLogic())
    s = SyncInterpreter(m).start()
    print("sync after start      :", sorted(s.current_state_ids))
    for n in range(1, 6):
        time.sleep(0.05)
        s.tick()
        print(f"sync after tick #{n}   :", sorted(s.current_state_ids))
    s.stop()

    import asyncio

    async def _a() -> None:
        i = await Interpreter(
            create_machine(CFG, logic=MachineLogic())
        ).start()
        await asyncio.sleep(0.25)
        print("async after 0.25s     :", sorted(i.current_state_ids))
        await i.stop()

    asyncio.run(_a())


if __name__ == "__main__":
    main()
