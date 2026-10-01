"""E04-T06 perf: stage instrumentation overhead vs the E04-K01 budget (<=1 % CPU).

Amortised per-event cost of `StageRecorder.on_event` at the default
`CV_TELEMETRY_SAMPLE_N=100`, against a per-event budget for the busiest R0
feed. `@perf`: CPU-time budget, enforced in CI only.
"""

from __future__ import annotations

import time

import pytest

from candleviewer.observability.latency import STAGE_BUCKETS, StageRecorder, StageStamps
from candleviewer.observability.metrics import Metrics

#: Busiest R0 feed assumption: 3 symbols x ~1 000 msgs/s; 1 % of one core.
EVENTS_PER_S = 3_000
BUDGET_S_PER_EVENT = 0.01 / EVENTS_PER_S  # ~3.3 us


@pytest.mark.perf
def test_stage_recorder_overhead_within_one_percent_cpu() -> None:
    m = Metrics("demo")
    h = m.histogram("ingest_stage_seconds", "h", ("stage",), buckets=STAGE_BUCKETS, max_series=4)
    rec = StageRecorder(h, 100)
    s = StageStamps(1_000, 1_005, 1_006, 1_010, 1_012)
    n = 200_000
    for _ in range(1_000):
        rec.on_event(s, 0)
    t0 = time.process_time()
    for _ in range(n):
        rec.on_event(s, 0)
    per_event = (time.process_time() - t0) / n
    print(f"on_event per_event={per_event * 1e6:.3f}us budget={BUDGET_S_PER_EVENT * 1e6:.2f}us")
    assert per_event < BUDGET_S_PER_EVENT
