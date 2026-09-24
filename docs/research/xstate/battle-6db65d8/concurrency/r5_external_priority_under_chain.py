"""R5 - external priority sends at high rate DURING self-generated chains,
both service kinds. #180: "external `send(priority=True)` is never charged"
-- accounting is by WHO issued it, not by WHEN it landed. So ZERO external
events may be shed as `chain_budget`.

The machine runs a self-feeding `always` cycle armed by an invoked service
(so the chain is live on the completion lane #179 rewired), while an
external producer hammers `send(priority=True)` from another thread.

Invariants:
  * 0 external events dropped for reason `chain_budget`;
  * every external event is either APPLIED or dropped for an honest
    backpressure reason (`queue_full`, `not_running`);
  * identical on `def` and `async def`.
"""

from __future__ import annotations

import asyncio
import threading
import time

from common2 import (
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
    emit,
    make_service,
)

TARGET_RATE = 10_000
SECONDS = 4.0


class Watch(PluginBase):
    def __init__(self) -> None:
        self.dropped = {}
        self.applied = 0

    def on_event_dropped(self, i, e, reason=None, **kw):  # noqa: ANN001
        t = getattr(e, "type", "?")
        self.dropped.setdefault(str(reason), {}).setdefault(t, 0)
        self.dropped[str(reason)][t] += 1

    def on_transition(self, i, f, t, e):  # noqa: ANN001
        if getattr(e, "type", None) == "EXT":
            self.applied += 1


LAPS = {"n": 0}


def act(i, ctx, e, ad):  # noqa: ANN001
    LAPS["n"] += 1


def ext(i, ctx, e, ad):  # noqa: ANN001
    ctx["ext"] = ctx.get("ext", 0) + 1


CFG = {
    "id": "r5",
    "initial": "ver",
    "context": {"n": 0, "ext": 0},
    "maxIterations": 200,
    "states": {
        "ver": {
            "invoke": {
                "src": "s",
                "onDone": {"target": "arm", "actions": ["act"]},
                "onError": {"target": "arm"},
            },
            "on": {"EXT": {"actions": ["ext"]}},
        },
        "arm": {
            "always": {"target": "ver", "actions": ["act"]},
            "on": {"EXT": {"actions": ["ext"]}},
        },
    },
}


def mk(kind: str):
    return create_machine(
        CFG,
        logic=MachineLogic(
            actions={"act": act, "ext": ext},
            services={"s": make_service(kind)},
        ),
    )


async def case(kind: str) -> dict:
    LAPS["n"] = 0
    w = Watch()
    itp = Interpreter(mk(kind), service_pool_size=4).use(w)
    await asyncio.wait_for(itp.start(), 10)

    sent = [0]
    errs = {}
    stop = threading.Event()

    def producer() -> None:
        period = 1.0 / TARGET_RATE
        nxt = time.perf_counter()
        while not stop.is_set():
            try:
                itp.send_threadsafe("EXT", priority=True)
                sent[0] += 1
            except Exception as exc:  # noqa: BLE001
                n = type(exc).__name__
                errs[n] = errs.get(n, 0) + 1
            nxt += period
            d = nxt - time.perf_counter()
            if d > 0:
                time.sleep(d)
            else:
                nxt = time.perf_counter()

    th = threading.Thread(target=producer, daemon=True)
    th.start()
    await asyncio.sleep(SECONDS)
    stop.set()
    th.join(timeout=5)
    # let the backlog drain
    for _ in range(60):
        await asyncio.sleep(0.05)
        if itp.queue_depth == 0:
            break
    applied = itp.context.get("ext", 0)
    depth = itp.queue_depth
    await asyncio.wait_for(itp.stop(), 20)
    chain_budget_drops = w.dropped.get("chain_budget", {})
    return {
        "service_kind": kind,
        "target_rate_per_s": TARGET_RATE,
        "seconds": SECONDS,
        "external_sent": sent[0],
        "external_applied": applied,
        "achieved_rate_per_s": round(sent[0] / SECONDS),
        "callsite_errors": errs,
        "drops_by_reason": w.dropped,
        "external_dropped_as_chain_budget": sum(chain_budget_drops.values()),
        "residual_queue_depth": depth,
        "cycle_laps": LAPS["n"],
        "unaccounted": sent[0]
        - applied
        - sum(sum(v.values()) for v in w.dropped.values())
        - sum(errs.values())
        - depth,
    }


async def main() -> int:
    rows = [await case(k) for k in ("def", "async def")]
    bad = [r for r in rows if r["external_dropped_as_chain_budget"]]
    emit(
        "r5_external_priority_under_chain",
        {
            "rows": rows,
            "rows_shedding_external_as_chain_budget": bad,
            "result": "FAIL" if bad else "PASS",
        },
    )
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
