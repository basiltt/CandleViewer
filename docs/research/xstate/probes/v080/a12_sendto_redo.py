"""A12-redo: sendTo a child that SURVIVES the failing transition.

The first attempt put the `invoke` on the source state, so exiting it
stopped the child before the sendTo could land -- the control showed zero
hits too, making the "rolled back" result meaningless. Here the invoke
lives on a parent state that both `a` and `b` are children of, so the
child is alive across the transition.
"""

from __future__ import annotations

import asyncio
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Probe  # noqa: E402

from xstate_statemachine import Interpreter, MachineLogic, create_machine  # noqa: E402

warnings.simplefilter("ignore", DeprecationWarning)
P = Probe("A12-redo — sendTo rollback with a surviving child")

CFG = {
    "id": "st2",
    "initial": "up",
    "context": {},
    "states": {
        "up": {
            "initial": "a",
            "invoke": {"id": "kid", "src": "kidm"},
            "states": {
                "a": {
                    "on": {
                        "GO": {
                            "target": "b",
                            "actions": [
                                {
                                    "type": "sendTo",
                                    "params": {
                                        "to": "kid",
                                        "event": {"type": "HIT"},
                                    },
                                },
                                "maybe_boom",
                            ],
                        }
                    }
                },
                "b": {},
            },
        }
    },
}

KID = {
    "id": "kidm",
    "initial": "idle",
    "context": {"hits": 0},
    "states": {"idle": {"on": {"HIT": {"actions": ["hit"]}}}},
}


class Boom(RuntimeError):
    pass


async def run(fail: bool, policy: str = "rollback"):
    hits = {"n": 0}

    def hit(i, c, e, a):
        hits["n"] += 1

    def maybe_boom(i, c, e, a):
        if fail:
            raise Boom("after the sendTo")

    kid = create_machine(KID, logic=MachineLogic(actions={"hit": hit}))
    cfg = dict(CFG)
    cfg["actionErrorPolicy"] = policy
    m = create_machine(
        cfg,
        logic=MachineLogic(
            actions={"maybe_boom": maybe_boom}, services={"kidm": kid}
        ),
    )
    i = await Interpreter(m).start()
    await asyncio.sleep(0.05)
    await i.send("GO")
    await asyncio.sleep(0.15)
    n, st = hits["n"], set(i.current_state_ids)
    await i.stop()
    return n, st


async def main():
    n_ok, st_ok = await run(fail=False)
    P.check(
        "A12c2",
        "control: sendTo reaches live child",
        n_ok == 1,
        f"hits={n_ok} states={st_ok}",
    )
    n_bad, st_bad = await run(fail=True)
    P.check(
        "A12r",
        "rollback undoes the delivered sendTo",
        n_bad == 0,
        f"hits={n_bad} states={st_bad} (expected 0 if the side effect is undone)",
    )
    P.report()


if __name__ == "__main__":
    asyncio.run(main())
