"""E40-K01 alert-placement benchmark harness (reused by E40-Q02).

Compares (A) alerts as degenerate rules in E35's ``Evaluator`` against (B) a lightweight
notify-only evaluator reusing E35's ``evaluate`` nodes + ``SnapshotBuilder``, both fed by the same
deterministic tick stream. Pure stdlib + candleviewer; no network. The delivery "commit" is an
in-memory sqlite INSERT+COMMIT (stand-in for ``alert_deliveries``; Postgres cost is NOT measured).
"""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
import time
import tracemalloc
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from candleviewer.rules.evaluator import Evaluator, MetricValue, SnapshotBuilder
from candleviewer.rules.evaluator.nodes import (
    EvalContext,
    InstanceState,
    evaluate,
    referenced_metrics,
)
from candleviewer.rules.ir.models import MetricRef, Rule

SYMBOLS = [f"SYM{i:02d}USDT" for i in range(20)]
RID = str(uuid.UUID(int=40))


class Clock:
    def __init__(self) -> None:
        self.t = 1_700_000_000_000

    def __call__(self) -> int:
        return self.t


class TickSource:
    """Memoised metric source: random-walk price per symbol, ``reads`` counts computations."""

    def __init__(self, clock: Clock, seed: int) -> None:
        self.clock = clock
        self.rng = random.Random(seed)
        self.price = {s: Decimal(100) for s in SYMBOLS}
        self.reads = 0

    def step(self, symbol: str) -> None:
        self.price[symbol] = self.price[symbol] + Decimal(self.rng.gauss(0, 0.2)).quantize(
            Decimal("0.01")
        )

    def read(self, ref: MetricRef) -> MetricValue:
        self.reads += 1
        return MetricValue(self.price[ref.symbol or SYMBOLS[0]], self.clock(), 0)


def condition(symbol: str, threshold: int) -> dict[str, Any]:
    return {
        "node_id": "c1",
        "op": "crosses_above",
        "left": {"metric": "price", "symbol": symbol},
        "right": {"const": threshold},
    }


def condition_hash(cond: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(cond, sort_keys=True).encode()).hexdigest()


def make_rule(cond: dict[str, Any]) -> Rule:
    return Rule.model_validate({
        "rule_id": RID, "version": 1, "name": "alert", "enabled": True, "mode": "armed",
        "scope": {"level": "symbol", "symbols": [cond["left"]["symbol"]]},
        "trigger": {"type": "on_price_update"}, "conditions": cond,
        "actions": [{"node_id": "a1", "type": "send_notification", "params": {}}],
        "limits": {"cooldown_ms": 0, "max_fires_per_hour": 10**6, "max_fires_per_day": 10**6},
    })  # fmt: skip


def corpus(n_alerts: int, n_distinct: int, seed: int = 1) -> list[dict[str, Any]]:
    """``n_alerts`` alerts over 20 symbols sharing exactly ``n_distinct`` distinct conditions."""
    rng = random.Random(seed)
    distinct = [
        condition(SYMBOLS[i % len(SYMBOLS)], 99 + rng.randint(0, 3)) for i in range(n_distinct)
    ]
    return [distinct[i % n_distinct] for i in range(n_alerts)]


class Sink:
    """Stand-in for alert_deliveries: one INSERT + COMMIT per delivery."""

    def __init__(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.execute("create table d(alert int, ts int)")
        self.count = 0

    def commit(self, alert: int, ts: int) -> None:
        self.db.execute("insert into d values (?,?)", (alert, ts))
        self.db.commit()
        self.count += 1


@dataclass
class Result:
    name: str
    lat_ms: list[float] = field(default_factory=list)
    evals: int = 0
    deliveries: int = 0
    subscriptions: int = 0
    computations: int = 0
    cpu_s: float = 0.0
    peak_kib: float = 0.0
    wall_s: float = 0.0

    def pct(self, p: float) -> float:
        xs = sorted(self.lat_ms)
        return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else 0.0

    def row(self) -> dict[str, Any]:
        return {
            "option": self.name,
            "p50_ms": round(self.pct(0.5), 4),
            "p95_ms": round(self.pct(0.95), 4),
            "p99_ms": round(self.pct(0.99), 4),
            "cpu_s": round(self.cpu_s, 3),
            "peak_kib": round(self.peak_kib),
            "subscriptions": self.subscriptions,
            "metric_computations": self.computations,
            "evaluations": self.evals,
            "deliveries": self.deliveries,
        }


def run_option(name: str, alerts: list[dict[str, Any]], ticks: int, seed: int = 7) -> Result:
    """name: shared (A, one Evaluator per alert) | shared_dedup (A') | separate (B)."""
    clk = Clock()
    src = TickSource(clk, seed)
    builder = SnapshotBuilder(src)
    sink = Sink()
    res = Result(name)
    by_symbol: dict[str, list[tuple[int, Any]]] = {s: [] for s in SYMBOLS}
    hashes = [condition_hash(a) for a in alerts]
    if name == "shared":
        for i, a in enumerate(alerts):
            by_symbol[a["left"]["symbol"]].append((i, Evaluator(make_rule(a), builder, clk, clk)))
        res.subscriptions = len(alerts)
    else:
        first: dict[str, int] = {}
        for i, (a, h) in enumerate(zip(alerts, hashes, strict=True)):
            if name == "shared_dedup":
                if h not in first:
                    first[h] = i
                    by_symbol[a["left"]["symbol"]].append(
                        (i, Evaluator(make_rule(a), builder, clk, clk))
                    )
            else:
                if h not in first:
                    first[h] = i
                    cond = make_rule(a).conditions
                    by_symbol[a["left"]["symbol"]].append(
                        (i, (cond, referenced_metrics(cond), InstanceState()))
                    )
        res.subscriptions = len(first)
    members: dict[str, list[int]] = {}
    for i, h in enumerate(hashes):
        members.setdefault(h, []).append(i)
    fan = name != "shared"
    rng = random.Random(seed)
    tracemalloc.start()
    c0, w0 = time.process_time(), time.perf_counter()
    for _ in range(ticks):
        sym = SYMBOLS[rng.randrange(len(SYMBOLS))]
        clk.t += 5
        src.step(sym)
        builder.new_tick()
        for idx, ev in by_symbol[sym]:
            t0 = time.perf_counter()
            res.evals += 1
            if name == "separate":
                cond, refs, state = ev
                snap = builder.build(refs, clk.t)
                fired = evaluate(cond, EvalContext(snap, state, clk.t, lambda: None))
            else:
                fired = ev.on_trigger(f"{sym}@*", "on_price_update").fired
            if fired:
                for a_idx in (members[hashes[idx]] if fan else [idx]):
                    sink.commit(a_idx, clk.t)
                    res.deliveries += 1
                    res.lat_ms.append((time.perf_counter() - t0) * 1000)
    res.cpu_s, res.wall_s = time.process_time() - c0, time.perf_counter() - w0
    res.peak_kib = tracemalloc.get_traced_memory()[1] / 1024
    tracemalloc.stop()
    res.computations = src.reads
    return res
