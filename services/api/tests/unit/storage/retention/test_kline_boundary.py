"""#2060: policy-driven klines hot boundary."""

from __future__ import annotations

import asyncio

from candleviewer.storage.models import StreamKind
from candleviewer.storage.retention.kline_boundary import (
    FALLBACK_HOT_DAYS,
    US_PER_DAY,
    KlineBoundaryRefreshTask,
    KlineHotBoundary,
    kline_hot_boundary_fallback_total,
)
from candleviewer.storage.retention.policy import RetentionPolicy, RetentionRule

NOW = 10**18


def _policy(days: int) -> RetentionPolicy:
    return RetentionPolicy([], [RetentionRule(StreamKind.KLINES, days, None)])


def _fallbacks() -> float:
    return kline_hot_boundary_fallback_total.labels("no_policy")._value.get()


def test_boundary_policy_30d_uses_policy() -> None:
    b = KlineHotBoundary(_policy(30), clock_us=lambda: NOW)
    assert b.boundary_us() == NOW - 30 * US_PER_DAY
    assert b.source == "policy"


def test_no_policy_falls_back_to_90d_and_counts_once_not_per_call() -> None:
    before = _fallbacks()
    b = KlineHotBoundary(None, clock_us=lambda: NOW)
    for _ in range(10):
        b.health_detail()
        assert b.boundary_us() == NOW - FALLBACK_HOT_DAYS * US_PER_DAY
    assert b.source == "fallback"
    assert _fallbacks() == before + 1


async def test_refresh_failure_keeps_last_value() -> None:
    async def boom() -> RetentionPolicy | None:
        raise OSError("db down")

    b = KlineHotBoundary(_policy(30), clock_us=lambda: NOW)
    await b.refresh(boom)
    await b.refresh(boom)
    assert b.boundary_us() == NOW - 30 * US_PER_DAY


async def test_refresh_loads_policy_and_detail() -> None:
    async def load() -> RetentionPolicy | None:
        return _policy(30)

    b = KlineHotBoundary(clock_us=lambda: NOW)
    await b.refresh(load)
    assert b.hot_days == 30
    assert "policy" in b.health_detail()


async def test_periodic_refresh_picks_up_edits_and_stops() -> None:
    days = [30]
    ticks: asyncio.Queue[None] = asyncio.Queue()

    async def load() -> RetentionPolicy | None:
        return _policy(days[0])

    async def sleep(_s: float) -> None:
        await ticks.get()

    b = KlineHotBoundary(_policy(30))
    task = KlineBoundaryRefreshTask(b, load, 600, sleep=sleep)
    task.start()
    days[0] = 14
    ticks.put_nowait(None)
    for _ in range(20):
        await asyncio.sleep(0)
    assert b.hot_days == 14
    await task.stop()
    await task.stop()  # idempotent
