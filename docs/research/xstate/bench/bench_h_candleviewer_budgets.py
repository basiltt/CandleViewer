# -----------------------------------------------------------------------------
# bench_h_candleviewer_budgets.py — direct test of the three stated budgets
# -----------------------------------------------------------------------------
"""Benchmarks shaped like CandleViewer's actual budgets rather than synthetic
throughput.

Budget 1 — order submit -> ack p95 < 300 ms.
    Measures the state-machine contribution only (no network): time from
    `send(SUBMIT)` to the machine being observably in `submitted`, and
    SUBMIT->ACK->open, while 500 other order machines are live.

Budget 2 — rule evaluation: ~100 rules x ~10 symbols at up to 2,000 events/s.
    1,000 rule machines, each fed the market-tick stream. Reports the
    achievable tick rate and the implied CPU headroom at 2k events/s.

Budget 3 — 500 concurrently open order machines.
    Steady-state memory and per-event latency at that population.
"""

from __future__ import annotations

import asyncio
import gc
import time
from typing import Any, Dict, List

import common
from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine


def rss_mb() -> float:
    import psutil

    return psutil.Process().memory_info().rss / 1024**2


# -----------------------------------------------------------------------------
# Budget 1 — submit -> ack latency under a live population
# -----------------------------------------------------------------------------
async def budget_submit_ack(background: int, samples: int) -> Dict[str, Any]:
    bg = [Interpreter(common.oms_machine()) for _ in range(background)]
    await asyncio.gather(*(i.start() for i in bg))

    # keep the background population actually busy, like a live book
    stop = asyncio.Event()
    cycle = common.oms_event_cycle(10)

    async def churn(i: Any) -> None:
        while not stop.is_set():
            for e in cycle:
                if stop.is_set():
                    return
                await i.send(e)
            await asyncio.sleep(0.005)  # ~throttled, not a busy spin

    tasks = [asyncio.create_task(churn(i)) for i in bg]
    await asyncio.sleep(0.2)  # let the load settle

    submit_ms: List[float] = []
    ack_ms: List[float] = []
    full_ms: List[float] = []

    for _ in range(samples):
        interp = await Interpreter(common.oms_machine()).start()
        t0 = time.perf_counter()
        await interp.send({"type": "SUBMIT", "qty": 1000.0})
        while "order.submitted" not in interp.current_state_ids:
            await asyncio.sleep(0)
        t1 = time.perf_counter()
        await interp.send({"type": "ACK", "order_id": "x"})
        while "order.open" not in interp.current_state_ids:
            await asyncio.sleep(0)
        t2 = time.perf_counter()
        submit_ms.append((t1 - t0) * 1000)
        ack_ms.append((t2 - t1) * 1000)
        full_ms.append((t2 - t0) * 1000)
        await interp.stop()

    stop.set()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await asyncio.gather(*(i.stop() for i in bg))

    return {
        "background_order_machines": background,
        "samples": samples,
        "submit_to_submitted_ms": common.summarize(submit_ms),
        "ack_to_open_ms": common.summarize(ack_ms),
        "submit_to_open_total_ms": common.summarize(full_ms),
        "budget_ms": 300,
        "p95_total_ms": common.pct(full_ms, 95),
        "within_budget": common.pct(full_ms, 95) < 300,
        "budget_headroom_x": 300 / max(common.pct(full_ms, 95), 1e-9),
    }


# -----------------------------------------------------------------------------
# Budget 2 — rule evaluation, 100 rules x 10 symbols
# -----------------------------------------------------------------------------
RULE_CFG = {
    "id": "rule",
    "initial": "armed",
    "context": {"hits": 0, "last": 0.0, "threshold": 0.0, "ticks": 0},
    "states": {
        "armed": {
            "on": {
                "TICK": [
                    {
                        "target": "triggered",
                        "cond": "crosses",
                        "actions": ["note", "fire"],
                    },
                    {"target": "armed", "actions": ["note"]},
                ]
            }
        },
        "triggered": {
            "on": {
                "RESET": "armed",
                "TICK": {"target": "triggered", "actions": ["note"]},
            }
        },
    },
}


def rule_machine(threshold: float, sync: bool = False):
    import json

    cfg = json.loads(json.dumps(RULE_CFG))
    cfg["context"]["threshold"] = threshold

    def crosses(ctx, e):
        return float(e.payload.get("px", 0.0)) > ctx["threshold"]

    def note(i, ctx, e, a):
        ctx["ticks"] += 1
        ctx["last"] = float(e.payload.get("px", 0.0))

    def fire(i, ctx, e, a):
        ctx["hits"] += 1

    return create_machine(
        cfg,
        logic=MachineLogic(
            actions={"note": note, "fire": fire}, guards={"crosses": crosses}
        ),
    )


async def budget_rules_async(
    n_rules: int, n_symbols: int, ticks_per_symbol: int
) -> Dict[str, Any]:
    """Each symbol's tick is fanned out to the rules watching that symbol."""
    per_symbol = n_rules // n_symbols
    rules = {
        s: [
            Interpreter(rule_machine(50_000 + k * 10))
            for k in range(per_symbol)
        ]
        for s in range(n_symbols)
    }
    flat = [r for rs in rules.values() for r in rs]
    await asyncio.gather(*(r.start() for r in flat))

    gc.collect()
    base = rss_mb()
    t0 = time.perf_counter()
    for t in range(ticks_per_symbol):
        px = 49_000.0 + (t % 200) * 10
        for s in range(n_symbols):
            for r in rules[s]:
                await r.send("TICK", px=px, sym=s)
    target = ticks_per_symbol
    deadline = time.perf_counter() + 300
    while any(r.context["ticks"] < target for r in flat):
        if time.perf_counter() > deadline:
            break
        await asyncio.sleep(0.001)
    dt = time.perf_counter() - t0
    peak = rss_mb()

    evaluations = ticks_per_symbol * n_symbols * per_symbol
    market_events = ticks_per_symbol * n_symbols
    await asyncio.gather(*(r.stop() for r in flat))

    return {
        "engine": "async Interpreter",
        "rule_machines": len(flat),
        "symbols": n_symbols,
        "rules_per_symbol": per_symbol,
        "market_events": market_events,
        "rule_evaluations": evaluations,
        "wall_s": dt,
        "rule_evaluations_per_sec": evaluations / dt,
        "market_events_per_sec": market_events / dt,
        "budget_market_events_per_sec": 2000,
        "meets_2k_events_per_sec": market_events / dt >= 2000,
        "rss_growth_mb": peak - base,
    }


def budget_rules_sync(
    n_rules: int, n_symbols: int, ticks_per_symbol: int
) -> Dict[str, Any]:
    """Same workload on SyncInterpreter — the realistic rule-engine engine."""
    per_symbol = n_rules // n_symbols
    rules = {
        s: [
            SyncInterpreter(rule_machine(50_000 + k * 10)).start()
            for k in range(per_symbol)
        ]
        for s in range(n_symbols)
    }
    flat = [r for rs in rules.values() for r in rs]
    gc.collect()
    base = rss_mb()
    t0 = time.perf_counter()
    for t in range(ticks_per_symbol):
        px = 49_000.0 + (t % 200) * 10
        for s in range(n_symbols):
            for r in rules[s]:
                r.send("TICK", px=px, sym=s)
    dt = time.perf_counter() - t0
    peak = rss_mb()
    evaluations = ticks_per_symbol * n_symbols * per_symbol
    market_events = ticks_per_symbol * n_symbols
    for r in flat:
        r.stop()
    return {
        "engine": "SyncInterpreter",
        "rule_machines": len(flat),
        "symbols": n_symbols,
        "rules_per_symbol": per_symbol,
        "market_events": market_events,
        "rule_evaluations": evaluations,
        "wall_s": dt,
        "rule_evaluations_per_sec": evaluations / dt,
        "market_events_per_sec": market_events / dt,
        "budget_market_events_per_sec": 2000,
        "meets_2k_events_per_sec": market_events / dt >= 2000,
        "rss_growth_mb": peak - base,
    }


# -----------------------------------------------------------------------------
# Budget 3 — 500 open order machines, steady state
# -----------------------------------------------------------------------------
async def budget_500_orders() -> Dict[str, Any]:
    gc.collect()
    base = rss_mb()
    interps = [Interpreter(common.oms_machine()) for _ in range(500)]
    await asyncio.gather(*(i.start() for i in interps))
    # bring each to `open`
    for i in interps:
        await i.send({"type": "SUBMIT", "qty": 1_000_000.0})
        await i.send({"type": "ACK"})
    await asyncio.sleep(0.5)
    resident = rss_mb()
    open_count = sum(
        1 for i in interps if "order.open" in i.current_state_ids
    )

    # latency of a single fill while all 500 are resident and idle
    lat: List[float] = []
    for k in range(200):
        tgt = interps[k % 500]
        before = tgt.context["fills"]
        t0 = time.perf_counter()
        await tgt.send({"type": "FILL", "qty": 0.5, "px": 100.0})
        while tgt.context["fills"] == before:
            await asyncio.sleep(0)
        lat.append((time.perf_counter() - t0) * 1000)

    await asyncio.gather(*(i.stop() for i in interps))
    gc.collect()
    after = rss_mb()
    return {
        "orders": 500,
        "all_reached_open": open_count == 500,
        "rss_baseline_mb": base,
        "rss_with_500_open_orders_mb": resident,
        "rss_cost_of_500_orders_mb": resident - base,
        "kb_per_open_order": (resident - base) * 1024 / 500,
        "fill_latency_ms": common.summarize(lat),
        "rss_after_teardown_mb": after,
        "retained_after_teardown_mb": after - base,
    }


async def main() -> None:
    common.report("machine_specs", common.machine_specs())
    out: Dict[str, Any] = {}
    out["budget1_submit_ack_latency"] = await budget_submit_ack(500, 200)
    out["budget2_rules_async_1000x10"] = await budget_rules_async(
        1000, 10, 200
    )
    out["budget2_rules_sync_1000x10"] = budget_rules_sync(1000, 10, 200)
    out["budget3_500_open_orders"] = await budget_500_orders()
    common.report("h_candleviewer_budgets", out)


if __name__ == "__main__":
    asyncio.run(main())
