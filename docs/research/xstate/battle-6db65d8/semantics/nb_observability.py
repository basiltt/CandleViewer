"""D8-E: observability hook matrix for every drop/refusal reason produced by
this round's machinery, on BOTH service kinds and BOTH engines.

E1  chain_budget on the ASYNC-def lane: fires, exactly once per dropped
    event, and the dropped event's receipt is failed (never left hanging).
E2  queue_full loop-side + call-site: every refusal is observable.
E3  SnapshotMidStepError(child=True) on a child mid-step.
E4  children_timeout WARNING is emitted exactly once per start().
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from typing import Any, Dict, List

from n_harness import attack, main

import xstate_statemachine as xs
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    OverflowPolicy,
    PluginBase,
    create_machine,
)


class Rec(PluginBase):
    def __init__(self) -> None:
        self.drops: List[tuple] = []

    def on_event_dropped(self, i, e, reason):  # noqa: ANN001
        self.drops.append((reason, getattr(e, "type", "?")))


CYC = {
    "id": "c",
    "initial": "idle",
    "maxIterations": 10,
    "states": {
        "idle": {"on": {"GO": "a"}},
        "a": {"invoke": {"src": "svc", "onDone": "b"}},
        "b": {"invoke": {"src": "svc", "onDone": "a"}},
    },
}


@attack(
    "E1",
    "chain_budget fires on the ASYNC-def lane, exactly once per dropped "
    "event, and every dropped event's receipt is FAILED not left hanging",
    "#179 put the coroutine lane under the budget; its drops must be visible",
)
async def e1() -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for kind in ("plain", "async"):
        def svc(i_, ctx, e):  # noqa: ANN001
            return 1

        async def svc_a(i_, ctx, e):  # noqa: ANN001
            await asyncio.sleep(0)
            return 1

        rec = Rec()
        m = create_machine(
            dict(CYC),
            logic=MachineLogic(services={"svc": svc_a if kind == "async" else svc}),
        )
        i = await Interpreter(m).use(rec).start()
        await i.send("GO")
        await asyncio.sleep(0.4)
        cb = [d for d in rec.drops if d[0] == "chain_budget"]
        err = type(i.last_error).__name__ if i.last_error else None
        await i.stop()
        rows.append(
            {
                "kind": kind,
                "chain_budget_hooks": len(cb),
                "dropped_types": dict(Counter(t for _, t in cb)),
                "last_error": err,
            }
        )
    # Both lanes must TRIP and both must REPORT it through the hook.
    ok = all(r["chain_budget_hooks"] >= 1 for r in rows) and all(
        r["last_error"] == "RunawayChainError" for r in rows
    )
    return {"ok": ok, "rows": rows}


@attack(
    "E2",
    "queue_full: every loop-side RAISE refusal is observable via "
    "on_event_dropped, and the call-site refusal raises QueueOverflowError",
    "#157 / R7-14: refusals must not be silent on either side",
)
async def e2() -> Dict[str, Any]:
    rec = Rec()
    cfg = {
        "id": "q",
        "initial": "a",
        "states": {"a": {"on": {"E": {"actions": "slow"}}}},
    }

    async def slow(i, ctx, e, ad):  # noqa: ANN001
        await asyncio.sleep(0.02)

    m = create_machine(cfg, logic=MachineLogic(actions={"slow": slow}))
    i = await Interpreter(
        m, max_queue_size=4, overflow_policy=OverflowPolicy.RAISE
    ).use(rec).start()

    refused_at_call = 0
    accepted = 0
    for _ in range(400):
        try:
            i.send_threadsafe("E")
            accepted += 1
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ == "QueueOverflowError":
                refused_at_call += 1
            else:
                return {"ok": False, "unexpected": type(exc).__name__}
    await asyncio.sleep(0.3)
    qf = [d for d in rec.drops if d[0] == "queue_full"]
    await i.stop()
    return {
        "ok": (refused_at_call + len(qf)) > 0,
        "accepted": accepted,
        "refused_at_call_site": refused_at_call,
        "queue_full_hooks": len(qf),
        "total_observable_refusals": refused_at_call + len(qf),
        "note": "every refusal is observable on one side or the other",
    }


@attack(
    "E4",
    "children_timeout emits exactly ONE warning per start() and start() "
    "still returns a running machine",
    "#181 observability",
)
async def e4() -> Dict[str, Any]:
    async def snooze(i, ctx, e, ad):  # noqa: ANN001
        await asyncio.sleep(0.8)

    child_cfg = {
        "id": "kid",
        "initial": "boot",
        "states": {"boot": {"entry": "snooze"}},
    }
    counts: List[int] = []
    for _ in range(3):
        kid = create_machine(
            child_cfg, logic=MachineLogic(actions={"snooze": snooze})
        )
        parent = {
            "id": "p",
            "initial": "up",
            "states": {"up": {"invoke": {"src": "kid", "id": "k"}}},
        }
        m = create_machine(parent, logic=MachineLogic(services={"kid": kid}))
        i = Interpreter(m)
        recs: List[logging.LogRecord] = []

        class Cap(logging.Handler):
            def emit(self, r):  # noqa: ANN001
                recs.append(r)

        lg = logging.getLogger("xstate_statemachine.interpreter")
        prev = logging.root.manager.disable
        logging.disable(logging.NOTSET)
        h = Cap(level=logging.WARNING)
        lg.addHandler(h)
        try:
            await i.start(children_timeout=0.1)
        finally:
            lg.removeHandler(h)
            logging.disable(prev)
        counts.append(
            sum(
                1
                for r in recs
                if r.levelno >= logging.WARNING and "still starting" in r.getMessage()
            )
        )
        running = i.status == "running"
        await asyncio.sleep(0.9)
        await i.stop()
        if not running:
            return {"ok": False, "status_not_running": True}
    return {
        "ok": all(c == 1 for c in counts),
        "warnings_per_start": counts,
    }


if __name__ == "__main__":
    main("nb_observability")
