"""D9-SEC-1 repro: the #195 engine-provenance marker is re-typable.

`_EngineDone` is a NamedTuple subclass, so `_replace` PRESERVES the subclass.
Any user action that receives a GENUINE engine completion -- the ordinary
`onDone` / `onError` handler, which is the documented place user code touches
these objects -- holds an engine-minted instance and can re-type it into ANY
other completion name. `is_system_event` stays True, so the result bypasses
`strict` and `onUnhandled` and drives a real `onDone` while the genuine
service is still running: exactly the failure #195 states it closes.

Standalone: stdlib + xstate_statemachine only.
Exit 1 == reproduced.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import sys
from typing import Any, Dict, List

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.events import is_system_event

logging.disable(logging.CRITICAL)

OMS = {
    "id": "oms",
    "strict": True,
    "initial": "idle",
    "states": {
        "idle": {"on": {"GO": "working"}},
        "working": {
            "invoke": [
                {"src": "ping", "id": "ping",
                 "onDone": {"actions": "attacker"}},
                {"src": "fill", "id": "fill",
                 "onDone": {"target": "settled", "actions": "book"}},
            ]
        },
        "settled": {},
    },
}


async def run(kind: str) -> Dict[str, Any]:
    booked: List[Any] = []
    forged_is_system = {"v": None}

    def ping_sync(i, c, e):  # noqa: ANN001
        return "pong"

    async def ping_async(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return "pong"

    def fill_sync(i, c, e):  # noqa: ANN001
        import time

        time.sleep(3.0)          # genuine venue fill, still outstanding
        return {"qty": 100}

    async def fill_async(i, c, e):  # noqa: ANN001
        await asyncio.sleep(3.0)
        return {"qty": 100}

    def attacker(i, c, e, a):  # noqa: ANN001
        # `e` is the GENUINE done.invoke.ping completion the engine minted.
        ev = e._replace(
            type="done.invoke.fill", data={"qty": 999999}, src="fill"
        )
        forged_is_system["v"] = is_system_event(ev)
        i.send(ev)

    def book(i, c, e, a):  # noqa: ANN001
        booked.append((e.type, e.data))

    logic = MachineLogic(
        actions={"attacker": attacker, "book": book},
        services={
            "ping": ping_async if kind == "async" else ping_sync,
            "fill": fill_async if kind == "async" else fill_sync,
        },
    )
    itp = await Interpreter(
        create_machine(copy.deepcopy(OMS), logic=logic)
    ).start()
    await itp.send("GO")
    await asyncio.sleep(0.6)
    out = {
        "kind": kind,
        "forged_is_system_event": forged_is_system["v"],
        "state": sorted(itp.current_state_ids),
        "booked": booked,
        "last_error": type(itp.last_error).__name__
        if itp.last_error else None,
    }
    out["REPRODUCED"] = bool(booked) and "oms.settled" in out["state"]
    await itp.stop()
    return out


async def main() -> int:
    bad = 0
    for kind in ("plain", "async"):
        r = await run(kind)
        print(r)
        bad += r["REPRODUCED"]
    print("VERDICT:", "REPRODUCED" if bad else "clean")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
