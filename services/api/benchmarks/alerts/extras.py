"""Q3-Q5 helpers: storm histogram, once_per_bar key, notify-only IR guard (E40-K01)."""

from __future__ import annotations

import random
import time
from collections import Counter
from typing import Any

TF_MS = {"s": 1_000, "m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}
SUPPORTED_TF = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "1w"]
WEEK_EPOCH_MS = 4 * 86_400_000  # 1970-01-01 is a Thursday; weekly bars open Monday 00:00 UTC


def bar_open(ts_ms: int, tf: str) -> int:
    """Deterministic bar-open key from event time; late ticks map to the same bar (Q4)."""
    n, unit = int(tf[:-1]), tf[-1]
    size = n * TF_MS[unit]
    if unit == "w":
        return ((ts_ms - WEEK_EPOCH_MS) // size) * size + WEEK_EPOCH_MS
    return (ts_ms // size) * size


def storm_histogram(
    users: int = 50, minutes: int = 240, seed: int = 3, burst_p: float = 0.02
) -> dict[str, Any]:
    """SYNTHETIC detector-heavy stream (no recorded E25 window exists yet): per user per minute
    a Poisson-ish count with occasional bursts. Returns per-60s-window delivery distribution."""
    rng = random.Random(seed)
    counts: list[int] = []
    for _ in range(users * minutes):
        n = sum(1 for _ in range(20) if rng.random() < 0.08)  # baseline ~1.6/min
        if rng.random() < burst_p:
            n += rng.randint(15, 80)  # stacked-imbalance burst
        counts.append(n)
    xs = sorted(counts)

    def q(p: float) -> int:
        return xs[min(len(xs) - 1, int(p * len(xs)))]

    hist = Counter(min(c, 40) // 5 * 5 for c in counts)
    return {
        "windows": len(xs),
        "p50": q(0.5),
        "p95": q(0.95),
        "p99": q(0.99),
        "p999": q(0.999),
        "max": xs[-1],
        "histogram_bucket5": dict(sorted(hist.items())),
    }


ACTION_FREE_OK = {"send_notification"}


def notify_only(ir: dict[str, Any]) -> list[str]:
    """Reject action-bearing IR: every action must be send_notification (Q5)."""
    return [
        a.get("type", "?") for a in ir.get("actions", []) if a.get("type") not in ACTION_FREE_OK
    ]


def guard_cost(n: int = 2000) -> dict[str, float]:
    from benchmarks.alerts.harness import condition, make_rule

    ir = make_rule(condition("SYM00USDT", 100)).model_dump(mode="json")
    t = []
    for _ in range(n):
        t0 = time.perf_counter()
        notify_only(ir)
        t.append((time.perf_counter() - t0) * 1000)
    t.sort()
    return {"p50_ms": t[n // 2], "p99_ms": t[int(n * 0.99)]}
