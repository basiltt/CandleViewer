"""Budget evidence (perf label; C-13.9): engine work per print at the 5 000 prints/s budget #5.

US-MKT-006 allows the big-trade evaluation ≤ 2 ms p95 added to ingest→bus. One Bybit push is
evaluated as a batch, so the measured unit is a 50-print batch (a dense push) on a warm,
fully-configured engine (percentile mode + clustering = the most expensive path)."""

from __future__ import annotations

import random
import time
from decimal import Decimal

import pytest

from candleviewer.orderflow.bigtrade import BigTradeEngine
from candleviewer.orderflow.bigtrade_models import BigTradeConfig
from tests.unit.orderflow._bigtrade_helpers import TICK, trade

pytestmark = pytest.mark.perf


def test_perf_batch_p95_under_2ms_and_sustains_5000_prints_per_s() -> None:
    rng = random.Random(5)  # noqa: S311 - seeded, reproducible bench data
    cfg = BigTradeConfig(
        mode="percentile", value=Decimal("99"), cluster_window_ms=2000, cluster_tolerance_ticks=2
    )
    eng = BigTradeEngine("BTCUSDT", TICK, cfg)
    ts, batches = 0, []
    for _ in range(2000):  # 100 000 prints at 5 000 prints/s = 20 s of print time
        batch = []
        for _ in range(50):
            ts += 200
            px = f"{60000 + rng.randint(-50, 50) / 10:.1f}"
            batch.append(
                trade(ts, px, f"{rng.lognormvariate(-2, 1.5):.3f}", rng.choice(["buy", "sell"]))
            )
        batches.append(batch)
    for b in batches[:200]:
        eng.process(b)  # warm-up
    samples = []
    for b in batches[200:]:
        t0 = time.perf_counter()
        eng.process(b)
        samples.append(time.perf_counter() - t0)
    samples.sort()
    p95 = samples[int(len(samples) * 0.95)]
    per_s = 50 / (sum(samples) / len(samples))
    print(f"bigtrade batch(50) p95={p95 * 1e3:.3f} ms; throughput={per_s:,.0f} prints/s")
    assert p95 < 0.002
    assert per_s > 5000
