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


import pytest  # noqa: E402


@pytest.mark.parametrize("days", [0, -1, 10000])
def test_invalid_hot_days_fall_back_and_count(days: int) -> None:
    c = kline_hot_boundary_fallback_total.labels("invalid_policy")
    before = c._value.get()
    b = KlineHotBoundary(_policy(days), clock_us=lambda: NOW)
    assert b.boundary_us() == NOW - FALLBACK_HOT_DAYS * US_PER_DAY
    assert c._value.get() == before + 1


async def test_failed_and_timed_out_load_count_and_keep_last() -> None:
    c = kline_hot_boundary_fallback_total.labels("load_failed")
    before = c._value.get()

    async def boom() -> RetentionPolicy | None:
        raise OSError("down")

    async def hang() -> RetentionPolicy | None:
        await asyncio.sleep(10)
        return None

    b = KlineHotBoundary(_policy(30), clock_us=lambda: NOW, load_timeout_s=0.05)
    await b.refresh(boom)
    await b.refresh(hang)
    assert c._value.get() == before + 2
    assert b.hot_days == 30


async def test_loader_explicit_rule_vs_repository_default() -> None:
    from candleviewer.app import kline_policy_loader

    class Repo:
        def __init__(self, days: int | None) -> None:
            self.days = days

        async def explicit_policy_days(self, symbol: str, stream: str) -> int | None:
            return self.days

    explicit = await kline_policy_loader(Repo(30))()  # type: ignore[arg-type]
    assert explicit is not None
    b = KlineHotBoundary(explicit)
    assert b.hot_days == 30 and b.source == "policy"
    assert await kline_policy_loader(Repo(None))() is None  # no explicit rule -> fallback 90 d
    assert KlineHotBoundary(None).hot_days == 90
