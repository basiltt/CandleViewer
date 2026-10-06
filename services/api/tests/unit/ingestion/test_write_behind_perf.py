"""#1918 r2: eviction bookkeeping is O(1) per row on the WS reader path (C-2.18).

The wall-clock budget is `perf`-marked (C-13.9); the no-sort assertion is
structural and always runs.
"""

from __future__ import annotations

import time

import pytest

from candleviewer.ingestion import write_behind as wb
from candleviewer.ingestion.kline_coverage import Range
from candleviewer.ingestion.metrics import trade_writes_dropped_total


def _buf() -> wb.WriteBehindBuffer[tuple[str, int]]:
    return wb.WriteBehindBuffer(
        table="trades", maxsize=1024, dropped=trade_writes_dropped_total, key=lambda r: r
    )


def test_write_behind_put_eviction_never_sorts_or_merges_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("put() must not sort or merge a coverage index")

    monkeypatch.setattr(wb, "sorted", boom, raising=False)
    monkeypatch.setattr("candleviewer.ingestion.kline_coverage.CoverageIndex.mark_covered", boom)
    buf = _buf()
    buf.failures = 1
    for i in range(5000):
        buf.put(("BTCUSDT", i))
    assert buf.lost_ranges("BTCUSDT") == [Range(0, 5000 - 1024)]


@pytest.mark.perf
def test_write_behind_100k_evictions_under_100ms() -> None:
    buf = _buf()
    buf.failures = 1  # sustained outage
    rows = [("BTCUSDT", i) for i in range(101_024)]
    for r in rows[:1024]:
        buf.put(r)
    start = time.perf_counter()
    for r in rows[1024:]:
        buf.put(r)
    elapsed = time.perf_counter() - start
    assert buf.evicted == 100_000
    # ~100 ms on the dev laptop (was ~29 s with per-row CoverageIndex merges);
    # 2x headroom for shared CI runners.
    assert elapsed < 0.2
