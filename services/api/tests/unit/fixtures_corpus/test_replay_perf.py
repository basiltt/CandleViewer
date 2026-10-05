"""E08-T05: replay harness throughput budget (>= 20 000 events/s).

Wall-clock assertion -> `perf` marker (C-13.9; run in CI, deselected by the
orchestrator's shared-laptop gate, see pyproject markers).
"""

from __future__ import annotations

import time

import coverage
import pytest

from tests._corpus import frames, replay

pytestmark = pytest.mark.perf


async def test_replay_harness_sustains_20k_events_per_second() -> None:
    raw = frames("ws/clean_publicTrade_BTCUSDT.jsonl") * 20
    await replay(raw[:50])  # warm imports/caches
    best = float("inf")
    events: list[object] = []
    cov = coverage.Coverage.current()  # time the harness, not the coverage tracer
    if cov is not None:
        cov.stop()
    try:
        for _ in range(3):  # best-of-3: robust to a noisy neighbour; budget unchanged
            start = time.perf_counter()
            events = await replay(raw)
            best = min(best, time.perf_counter() - start)
    finally:
        if cov is not None:
            cov.start()
    rate = len(events) / best
    print(f"replay harness: {len(events)} events in {best:.3f}s = {rate:,.0f} events/s")
    assert rate >= 20_000
