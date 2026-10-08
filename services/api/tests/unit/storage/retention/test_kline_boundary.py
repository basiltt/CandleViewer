"""#2060: policy-driven klines hot boundary."""

from __future__ import annotations

from candleviewer.storage.models import StreamKind
from candleviewer.storage.retention.kline_boundary import (
    FALLBACK_HOT_DAYS,
    US_PER_DAY,
    KlineHotBoundary,
    kline_hot_boundary_fallback_total,
)
from candleviewer.storage.retention.policy import RetentionPolicy, RetentionRule

NOW = 10**18


def _policy(days: int) -> RetentionPolicy:
    return RetentionPolicy([], [RetentionRule(StreamKind.KLINES, days, None)])


def test_boundary_policy_30d_uses_policy() -> None:
    b = KlineHotBoundary(_policy(30), clock_us=lambda: NOW)
    assert b.boundary_us() == NOW - 30 * US_PER_DAY
    assert b.source == "policy"


def test_boundary_no_policy_falls_back_to_90d_and_warns_once(capsys) -> None:  # type: ignore[no-untyped-def]
    c = kline_hot_boundary_fallback_total.labels("no_policy")
    before = c._value.get()
    b = KlineHotBoundary(None, clock_us=lambda: NOW)
    assert b.boundary_us() == NOW - FALLBACK_HOT_DAYS * US_PER_DAY
    b.boundary_us()
    assert b.source == "fallback"
    assert c._value.get() == before + 2
    assert capsys.readouterr().out.count("kline_hot_boundary_no_policy_using_fallback") <= 1


async def test_refresh_failure_keeps_fallback() -> None:
    async def boom() -> RetentionPolicy | None:
        raise OSError("db down")

    b = KlineHotBoundary(_policy(30), clock_us=lambda: NOW)
    await b.refresh(boom)
    assert b.boundary_us() == NOW - 90 * US_PER_DAY


async def test_refresh_loads_policy() -> None:
    async def load() -> RetentionPolicy | None:
        return _policy(30)

    b = KlineHotBoundary(clock_us=lambda: NOW)
    await b.refresh(load)
    assert b.hot_days == 30
    assert "policy" in b.health_detail()
