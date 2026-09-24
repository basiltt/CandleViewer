"""R4-06 -- external `send()` made during a macrostep is charged to the
self-raised chain budget and silently dropped.

Exits 1 while the defect is present, 0 once fixed.
"""

import asyncio
import logging
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase

logging.disable(logging.CRITICAL)

CFG = {
    "id": "m",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {
            "on": {
                "T": {"actions": ["inc"]},
                "SLOW": {"actions": ["slow"]},
            }
        }
    },
}

def inc(i, c, e, a):
    c["n"] += 1

async def slow(i, c, e, a):
    # A realistic awaiting action: a DB write, an HTTP call to a broker.
    await asyncio.sleep(0.5)

class DropSpy(PluginBase):
    def __init__(self):
        self.drops = []

    def on_event_dropped(self, interp, event, reason):
        self.drops.append((getattr(event, "type", event), reason))

async def run(burst: int):
    spy = DropSpy()
    machine = create_machine(
        CFG, logic=MachineLogic(actions={"inc": inc, "slow": slow})
    )
    interp = Interpreter(machine)
    interp.use(spy)
    await interp.start()

    # Kick off the long-running action, then push external traffic at the
    # interpreter from OUTSIDE while that macrostep is still in flight.
    interp.send("SLOW")
    await asyncio.sleep(0.05)
    for _ in range(burst):
        await interp.send("T")
    await asyncio.sleep(1.2)

    applied = interp.context["n"]
    lost = burst - applied
    print(
        f"  burst={burst:<5} accepted={burst:<5} applied={applied:<5} "
        f"LOST={lost}  drops={len(spy.drops)} "
        f"reasons={sorted({r for _, r in spy.drops})} "
        f"last_transition_ok={interp.last_transition_ok}"
    )
    await interp.stop()
    return lost

async def main() -> int:
    print("OBSERVED:")
    control = await run(999)  # below the default maxIterations=1000
    lost_1500 = await run(1500)
    lost_3000 = await run(3000)

    print("\nEXPECTED: LOST=0 for every burst. External events accepted by")
    print("  `await send()` are never self-raised work and must not be")
    print("  charged to the chained-`raise` budget (maxIterations=1000).")

    bad = control != 0 or lost_1500 != 0 or lost_3000 != 0
    print("\nRESULT:", "DEFECT PRESENT" if bad else "OK")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
