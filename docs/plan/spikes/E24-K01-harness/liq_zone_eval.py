"""E24-K01 offline harness: liquidation-zone methods vs a chance baseline.

Inputs are SEEDED SYNTHETIC symbol-days (no recorded liquidations exist in-repo yet, and
this spike must not hit the network). Numbers therefore validate the harness and the
decision rule only; they are NOT evidence about Bybit. See ../E24-K01.md section 2.
Run: python liq_zone_eval.py  (deterministic, stdlib only)
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass

TICK = 0.5
TIERS = (10, 25, 50, 100)
MMR = 0.005  # assumed maintenance margin rate (ASSUMED, not exchange-published here)
N_TICKS = 40  # hit tolerance in ticks
M_MIN = 60  # look-ahead window in minutes


@dataclass(frozen=True)
class Day:
    name: str
    ref: float  # reference price
    oi: float
    liqs: tuple[tuple[int, float], ...]  # (minute, price)


def make_day(
    name: str, seed: int, cascade: bool, mix_levs: tuple[int, ...] = (15, 30, 75)
) -> Day:
    rng = random.Random(seed)
    ref = 60000.0 + rng.random() * 1000
    liqs: list[tuple[int, float]] = []
    # hidden truth: leverage mix differs from the assumed uniform one
    weights = (
        (0.5, 0.3, 0.2)
        if len(mix_levs) == 3
        else tuple(1 / len(mix_levs) for _ in mix_levs)
    )
    mix = list(zip(mix_levs, weights))
    for _ in range(300 if not cascade else 900):
        lev = rng.choices([m[0] for m in mix], [m[1] for m in mix])[0]
        side = rng.choice((-1, 1))
        px = ref * (1 + side * (1 / lev - MMR) * rng.uniform(0.6, 1.4))
        liqs.append((rng.randrange(1440), round(px / TICK) * TICK))
    if cascade:
        for _ in range(600):
            liqs.append(
                (
                    600 + rng.randrange(20),
                    round(ref * (1 - 0.03 + rng.gauss(0, 0.002)) / TICK) * TICK,
                )
            )
    liqs.sort()
    return Day(name, ref, 1e9, tuple(liqs))


def zones_a(day: Day) -> list[float]:
    out = []
    for lev in TIERS:
        d = day.ref * (1 / lev - MMR)
        out += [day.ref - d, day.ref + d]
    return out


def zones_b(day: Day, upto: int) -> list[float]:
    """Realised-liquidation histogram: top-5 price buckets seen before `upto`."""
    h: dict[float, int] = {}
    for m, p in day.liqs:
        if m < upto:
            b = round(p / (TICK * 20)) * TICK * 20
            h[b] = h.get(b, 0) + 1
    return [p for p, _ in sorted(h.items(), key=lambda kv: -kv[1])[:5]]


def zones_chance(day: Day, rng: random.Random) -> list[float]:
    return [day.ref * (1 + rng.uniform(-0.05, 0.05)) for _ in range(8)]


def score(day: Day, zones: list[float], start: int) -> tuple[int, int]:
    hits = 0
    for z in zones:
        if any(
            start <= m < start + M_MIN and abs(p - z) <= N_TICKS * TICK
            for m, p in day.liqs
        ):
            hits += 1
    return hits, len(zones)


def evaluate(days: list[Day]) -> dict[str, dict[str, float]]:
    res: dict[str, list[int]] = {
        k: [0, 0] for k in ("a_oi_buckets", "b_realised_hist", "chance")
    }
    rng = random.Random(7)
    for d in days:
        for start in range(120, 1440 - M_MIN, 60):
            for k, z in (
                ("a_oi_buckets", zones_a(d)),
                ("b_realised_hist", zones_b(d, start)),
                ("chance", zones_chance(d, rng)),
            ):
                h, n = score(d, z, start)
                res[k][0] += h
                res[k][1] += n
    return {
        k: {
            "hit_rate": round(h / n, 4),
            "false_positive_rate": round(1 - h / n, 4),
            "zones": n,
        }
        for k, (h, n) in res.items()
    }


def cost_ms(day: Day, reps: int = 2000) -> float:
    """Method (a) cost (descoped; kept for comparison)."""
    t = time.perf_counter()
    for _ in range(reps):
        zones_a(day)
    return (time.perf_counter() - t) / reps * 1000


def cost_ms_b(day: Day, reps: int = 200) -> dict[str, float]:
    """Method (b) cost, the chosen method: full recompute from the whole day's liquidations
    (worst case, ~1200-1500 events) and the incremental path (O(1) bucket update + top-5)."""
    t = time.perf_counter()
    for _ in range(reps):
        zones_b(day, 1440)
    full = (time.perf_counter() - t) / reps * 1000
    width = TICK * 20
    h: dict[float, int] = {}
    for m, p in day.liqs:
        b = round(p / width) * width
        h[b] = h.get(b, 0) + 1
    n = 0
    t = time.perf_counter()
    for _ in range(reps):
        for m, p in day.liqs[:50]:
            b = round(p / width) * width
            h[b] = h.get(b, 0) + 1
            n += 1
        sorted(h.items(), key=lambda kv: -kv[1])[:5]
    inc = (time.perf_counter() - t) / reps * 1000 / 50
    return {
        "full_recompute_ms": round(full, 5),
        "incremental_ms_per_liq_plus_top5": round(inc, 5),
        "events": len(day.liqs),
        "buckets": len(h),
    }


def main() -> None:
    days = [
        make_day("syn-calm-1", 1, False),
        make_day("syn-calm-2", 2, False),
        make_day("syn-cascade-3", 3, True),
    ]
    # Sensitivity: hidden mix == assumed tiers (removes the built-in mismatch bias against (a)).
    matched = [make_day("syn-matched-%d" % i, 10 + i, i == 2, TIERS) for i in range(3)]
    out = {
        "synthetic": True,
        "results_matched_mix_sensitivity": evaluate(matched),
        "cost_ms_method_b_cascade_day": cost_ms_b(days[2]),
        "params": {"tiers": TIERS, "mmr": MMR, "n_ticks": N_TICKS, "m_min": M_MIN},
        "results": evaluate(days),
        "cost_ms_per_update_method_a_pure_python": round(cost_ms(days[0]), 5),
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
