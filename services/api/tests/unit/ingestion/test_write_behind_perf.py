"""#1918: eviction bookkeeping is O(1) per row on the WS reader path (C-2.18).

The claim is complexity, not a wall-clock number: CPU time for 10x the
evictions must grow ~10x (linear), never ~100x (the old per-row
CoverageIndex merge was quadratic). A generous absolute bound still fails a
pathological regression. Each size takes the min of repeated runs
(`perf_counter`; `process_time` ticks at ~15 ms on Windows), so load and
`--cov` tracing inflate both sizes alike and cancel in the ratio.
"""

from __future__ import annotations

import time

import pytest

from candleviewer.ingestion import write_behind as wb
from candleviewer.ingestion.kline_coverage import Range
from candleviewer.ingestion.metrics import trade_writes_dropped_total

_CAP = 1024


def _buf() -> wb.WriteBehindBuffer[tuple[str, int]]:
    buf: wb.WriteBehindBuffer[tuple[str, int]] = wb.WriteBehindBuffer(
        table="trades", maxsize=_CAP, dropped=trade_writes_dropped_total, key=lambda r: r
    )
    buf.failures = 1  # sustained outage
    return buf


def _evict_cpu_s(n: int) -> float:
    buf = _buf()
    rows = [("BTCUSDT", i) for i in range(n + _CAP)]
    for r in rows[:_CAP]:
        buf.put(r)
    start = time.perf_counter()
    for r in rows[_CAP:]:
        buf.put(r)
    elapsed = time.perf_counter() - start
    assert buf.evicted == n
    return elapsed


def test_write_behind_sustained_eviction_records_one_contiguous_lost_range() -> None:
    buf = _buf()
    for i in range(5000):
        buf.put(("BTCUSDT", i))
    assert buf.lost_ranges("BTCUSDT") == [Range(0, 5000 - _CAP)]


@pytest.mark.perf
def test_write_behind_evictions_scale_linearly() -> None:
    _evict_cpu_s(10_000)  # warm-up
    small = min(_evict_cpu_s(10_000) for _ in range(5))
    large = min(_evict_cpu_s(100_000) for _ in range(2))
    assert large < 2.0  # sanity: was ~29 s with the quadratic merge
    assert large / small < 20  # linear ~10, quadratic ~100
