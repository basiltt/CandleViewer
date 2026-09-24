# -*- coding: utf-8 -*-
"""U1 -- is `get_persisted_snapshot()` after `await send()` ALWAYS accepted?

STANDALONE (stdlib + xstate_statemachine).

The library's contract for the mid-step guard is "snapshot it once the step
settles (await send(..., wait=True), or from on_transition)".  A caller who
follows that advice must never see `SnapshotMidStepError`, because there is
no later window they can wait for: `send()` has already returned.

This probe hammers exactly that window -- N iterations of
`await send(ev)` immediately followed by `get_persisted_snapshot()` -- on a
parallel machine with an invoke whose `onDone` moves it, for BOTH service
kinds, and additionally with `wait=True`.  It counts refusals.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import SnapshotMidStepError

KIND = os.environ.get("XS_SVC", "async")

SPEC = {
    "id": "det",
    "type": "parallel",
    "states": {
        "r0": {
            "initial": "a",
            "states": {
                "a": {
                    "entry": ["bump"],
                    "invoke": [{"id": "k", "src": "svc",
                                "onDone": {"target": "b",
                                           "actions": ["bump"]}}],
                    "on": {"GO": "b"},
                },
                "b": {"entry": ["bump"], "on": {"BACK": "a"}},
            },
        },
        "r1": {
            "initial": "x",
            "states": {"x": {"on": {"GO": "y"}}, "y": {"on": {"BACK": "x"}}},
        },
    },
}

SEQ = ["GO", "BACK", "GO", "GO", "BACK"]


def build():
    def bump(i, c, e, a):  # noqa: ANN001
        c["n"] = c.get("n", 0) + 1

    def svc_def(i, c, e):  # noqa: ANN001
        return {"ok": 1}

    async def svc_async(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return {"ok": 1}

    return create_machine(
        json.loads(json.dumps(SPEC)),
        logic=MachineLogic(
            actions={"bump": bump},
            services={"svc": svc_def if KIND == "def" else svc_async},
        ),
    )


async def one(wait: bool) -> str:
    """Returns '' on success or the refusal text."""
    i = Interpreter(build(), clock=SimulatedClock())
    await i.start(children_timeout=1.0)
    await asyncio.sleep(0.02)
    try:
        for ev in SEQ:
            if wait:
                await i.send(ev, wait=True)
            else:
                await i.send(ev)
        i.get_persisted_snapshot()
        return ""
    except SnapshotMidStepError as exc:
        return f"{type(exc).__name__}"
    finally:
        try:
            await i.stop()
        except Exception:  # noqa: BLE001
            pass


async def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    print(f"=== U1 snapshot-after-send window [{KIND}] n={n} per mode ===")
    fails = []
    for wait in (False, True):
        refused = 0
        for _ in range(n):
            r = await one(wait)
            if r:
                refused += 1
        mode = "await send(ev, wait=True)" if wait else "await send(ev)"
        print(f"  {mode:<28} refused {refused}/{n}")
        if refused:
            fails.append(f"{mode}: {refused}/{n} refused SnapshotMidStepError")

    print()
    print("FAILURES:", fails or "none")
    print("VERDICT:", "FAIL" if fails else "PASS")


if __name__ == "__main__":
    asyncio.run(main())
