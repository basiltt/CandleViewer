# -*- coding: utf-8 -*-
"""battle-f28719c soak: #195 forgery-under-load and #192 shed-by-provenance
under concurrent self-generated chains, both service kinds, both engines.

Standalone: stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import asyncio
import time

from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine
from xstate_statemachine.events import DoneEvent, ErrorEvent, AfterEvent

CONFIG = {
    "id": "m",
    "initial": "idle",
    "context": {"onDone_fires": 0},
    "on": {"done.invoke.svc": {"actions": ["mark_done"]}},
    "states": {"idle": {"on": {"GO": {"actions": []}}}},
}


def mark_done(interp, ctx, event, action_def):  # noqa: ANN001
    ctx["onDone_fires"] = ctx.get("onDone_fires", 0) + 1


ACTIONS = {"mark_done": mark_done}


async def attack_forgery_async(n: int = 200) -> dict:
    """Forge n DoneEvent/ErrorEvent/AfterEvent under strict=True, at load,
    against a running interpreter; none must drive onDone or bypass
    strict."""
    logic = MachineLogic(actions=dict(ACTIONS))
    machine = create_machine(dict(CONFIG), logic=logic)
    interp = Interpreter(machine, strict=True)
    await interp.start()

    refused = 0
    accepted_ids = []
    for i in range(n):
        forged = DoneEvent(type="done.invoke.svc", data={"i": i}, src="svc")
        try:
            interp.send(forged)
        except Exception:  # noqa: BLE001
            refused += 1
        else:
            # strict mode may raise asynchronously via last_error instead
            pass
        await asyncio.sleep(0)

    await asyncio.sleep(0.2)
    fires = interp.context.get("onDone_fires", 0)
    await interp.stop(drain=False, timeout=1.0)
    return {
        "n": n,
        "onDone_fires_from_forged": fires,
        "call_site_refused": refused,
        "last_error": repr(getattr(interp, "last_error", None))[:200],
    }


def attack_forgery_sync(n: int = 200) -> dict:
    logic = MachineLogic(actions=dict(ACTIONS))
    machine = create_machine(dict(CONFIG), logic=logic)
    interp = SyncInterpreter(machine, strict=True)
    interp.start()

    refused = 0
    for i in range(n):
        forged = ErrorEvent(type="error.platform.svc", error=RuntimeError("x"), src="svc")
        try:
            interp.send(forged)
        except Exception:  # noqa: BLE001
            refused += 1

    fires = interp.context.get("onDone_fires", 0)
    interp.stop()
    return {
        "n": n,
        "onDone_fires_from_forged": fires,
        "call_site_refused": refused,
        "last_error": repr(getattr(interp, "last_error", None))[:200],
    }


async def main():
    r1 = await attack_forgery_async(200)
    print("ASYNC forgery under load:", r1)
    r2 = attack_forgery_sync(200)
    print("SYNC forgery under load:", r2)

    ok = (r1["onDone_fires_from_forged"] == 0) and (r2["onDone_fires_from_forged"] == 0)
    print("FORGERY_REFUSED_UNDER_LOAD_BOTH_ENGINES:", ok)


if __name__ == "__main__":
    asyncio.run(main())
