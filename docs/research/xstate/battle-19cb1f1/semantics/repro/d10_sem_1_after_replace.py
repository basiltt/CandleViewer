"""D10-semantics-1 -- an `after` transition's own action is handed a genuine
engine-minted `AfterEvent`; `_replace` re-types it into ANY OTHER `after`
descriptor and fires that timer instantly, defeating #203.

Standalone: stdlib + xstate_statemachine only. Both service kinds.
Exit 1 == reproduced.
"""

from __future__ import annotations

import asyncio
import copy
import logging

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.events import is_system_event

logging.disable(logging.CRITICAL)

# A 5 ms settle timer whose action runs, and a 24-HOUR margin-call timer
# that must not be reachable for a day.
OMS = {
    "id": "oms",
    "strict": True,
    "type": "parallel",
    "states": {
        "settle": {
            "initial": "waiting",
            "states": {
                "waiting": {
                    "after": {5: {"target": "done", "actions": "relay"}},
                    "on": {"E": "done"},
                },
                "done": {},
            },
        },
        "margin": {
            "initial": "healthy",
            "states": {
                "healthy": {
                    "after": {86400000: {"target": "called",
                                         "actions": "call"}}
                },
                "called": {},
            },
        },
    },
}


async def run(kind: str) -> dict:
    called = []
    seen = {"system": None}

    def relay(i, c, e, a):  # noqa: ANN001
        # `e` is the genuine engine-minted AfterEvent for the 5 ms timer.
        forged = e._replace(type="after.86400000.oms.margin.healthy")
        seen["system"] = is_system_event(forged)
        i.send(forged)

    async def relay_a(i, c, e, a):  # noqa: ANN001
        forged = e._replace(type="after.86400000.oms.margin.healthy")
        seen["system"] = is_system_event(forged)
        i.send(forged)

    def call(i, c, e, a):  # noqa: ANN001
        called.append(e.type)

    async def call_a(i, c, e, a):  # noqa: ANN001
        called.append(e.type)

    lg = MachineLogic(
        actions={
            "relay": relay_a if kind == "async" else relay,
            "call": call_a if kind == "async" else call,
        }
    )
    it = await Interpreter(
        create_machine(copy.deepcopy(OMS), logic=lg)
    ).start()
    await asyncio.sleep(0.25)
    out = {
        "kind": kind,
        "forged_is_system_event": seen["system"],
        "state": sorted(it.current_state_ids),
        "margin_call_fired_early": called,
        "last_error": type(it.last_error).__name__ if it.last_error else None,
    }
    await it.stop()
    out["REPRODUCED"] = "oms.margin.called" in out["state"]
    return out


async def main() -> int:
    bad = 0
    for kind in ("plain", "async"):
        r = await run(kind)
        print(r)
        bad |= r["REPRODUCED"]
    print("VERDICT:", "REPRODUCED" if bad else "not reproduced")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
