"""E04-T06 perf: stage instrumentation overhead vs the E04-K01 budget (<=1 % CPU).

Amortised per-event cost of `StageRecorder.on_event` at the default
`CV_TELEMETRY_SAMPLE_N=100`, against a per-event budget for the busiest R0
feed. `@perf`: CPU-time budget, enforced in CI only.
"""

from __future__ import annotations

import gc
import time

import pytest

from candleviewer.observability.latency import STAGE_BUCKETS, StageRecorder, StageStamps
from candleviewer.observability.metrics import Metrics

#: Busiest R0 feed assumption: 3 symbols x ~1 000 msgs/s; 1 % of one core.
EVENTS_PER_S = 3_000
BUDGET_S_PER_EVENT = 0.01 / EVENTS_PER_S  # ~3.3 us
#: Fastest-of-N: host load only ever adds time, so the minimum is the least-contended estimate.
ROUNDS = 7
EVENTS_PER_ROUND = 200_000  # ~0.4 s/round: the budget spans >> 10 ticks of any OS clock


@pytest.mark.perf
def test_stage_recorder_overhead_within_one_percent_cpu() -> None:
    m = Metrics("demo")
    h = m.histogram("ingest_stage_seconds", "h", ("stage",), buckets=STAGE_BUCKETS, max_series=4)
    rec = StageRecorder(h, 100)
    s = StageStamps(1_000, 1_005, 1_006, 1_010, 1_012)
    for _ in range(1_000):
        rec.on_event(s, 0)
    best_ns = float("inf")
    gc.collect()
    gc.disable()  # a GC pause inside one timed loop would skew the sample
    try:
        for _ in range(ROUNDS):
            t0 = time.perf_counter_ns()  # ns resolution; process_time ticks at ~15.6 ms on Windows
            for _ in range(EVENTS_PER_ROUND):
                rec.on_event(s, 0)
            best_ns = min(best_ns, (time.perf_counter_ns() - t0) / EVENTS_PER_ROUND)
    finally:
        gc.enable()
    best = best_ns / 1e9
    print(f"on_event per_event={best * 1e6:.3f}us budget={BUDGET_S_PER_EVENT * 1e6:.2f}us")
    assert best > 0, "clock quantised the measurement to zero; the budget check would be vacuous"
    assert best < BUDGET_S_PER_EVENT
