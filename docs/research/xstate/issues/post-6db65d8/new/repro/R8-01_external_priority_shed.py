"""D8-semantics-1 repro: an EXTERNAL `send(priority=True)` is still shed as
`chain_budget` when a plain-`def` service's self-generated chain is running.

#180 says accounting is "by WHO issued it": only engine completions and
self-raised events are charged.  The charge site honours that -- but the
SHED site does not.  `_deliver_priority` increments `_raise_depth` only for
engine completions, yet once `_raise_depth` is over the budget, the guard
drops whatever it next pulls off the PRIORITY QUEUE, which is a FIFO holding
external sends and engine completions side by side.  So an external send that
happens to sit behind a tripped chain is destroyed.

`send(...)` RESOLVES OK for these events (accepted=2000, refused=0) and
`last_error` is None: the loss is silent, on the order path.

Run:  python d8_s1_priority_shed.py     (exit 1 == reproduced)
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter
from typing import Any, Dict

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)

CFG: Dict[str, Any] = {
    "id": "pp",
    "initial": "idle",
    "maxIterations": 50,
    "states": {
        "idle": {"on": {"GO": "a", "EXT": {"actions": "count_ext"}}},
        "a": {
            "invoke": {"src": "svc", "onDone": "b"},
            "on": {"EXT": {"actions": "count_ext"}},
        },
        "b": {
            "invoke": {"src": "svc", "onDone": "a"},
            "on": {"EXT": {"actions": "count_ext"}},
        },
    },
}


class Spy(PluginBase):
    def __init__(self) -> None:
        self.dropped: Counter = Counter()

    def on_event_dropped(self, i, e, reason):  # noqa: ANN001
        if reason == "chain_budget":
            self.dropped[getattr(e, "type", "?")] += 1


async def run(kind: str) -> Dict[str, Any]:
    fired = {"n": 0}

    def count_ext(i_, ctx, e, ad):  # noqa: ANN001
        fired["n"] += 1

    def svc_sync(i_, ctx, e):  # noqa: ANN001
        return 1

    async def svc_async(i_, ctx, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return 1

    m = create_machine(
        CFG,
        logic=MachineLogic(
            actions={"count_ext": count_ext},
            services={"svc": svc_async if kind == "async" else svc_sync},
        ),
    )
    spy = Spy()
    i = await Interpreter(m).use(spy).start()
    await i.send("GO")  # ignite the bounded self-generated cycle

    N = 2000
    accepted = 0
    for _ in range(N):
        await i.send("EXT", priority=True)  # EXTERNAL: never chargeable (#180)
        accepted += 1
        await asyncio.sleep(0)
    await asyncio.sleep(0.4)
    last_err = type(i.last_error).__name__ if i.last_error else None
    await i.stop()
    return {
        "kind": kind,
        "external_sent": N,
        "send_accepted_no_raise": accepted,
        "external_applied": fired["n"],
        "external_LOST": N - fired["n"],
        "chain_budget_drops_by_type": dict(spy.dropped),
        "last_error": last_err,
    }


async def main() -> int:
    bad = False
    for kind in ("plain", "async"):
        r = await run(kind)
        lost_ext = r["chain_budget_drops_by_type"].get("EXT", 0)
        r["VERDICT"] = (
            "REPRODUCED: external sends shed as chain_budget"
            if lost_ext
            else "clean"
        )
        bad = bad or bool(lost_ext)
        print(r)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
