"""#1919: `IngestionService.health()` degrades with stable reasons (C-13.6 #1, SCR-152).

Chaos `tests/chaos/ingestion/test_visible_degradation.py::
test_unrecovered_fault_reports_degraded_health` (PR #1921) is xfail until this
lands; promote it (drop the xfail) once both are on main.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from candleviewer.ingestion.connection import PHASE_CONNECTING, PHASE_OPEN
from candleviewer.ingestion.instruments import InstrumentCatalogueCache
from candleviewer.ingestion.service import (
    PUMP_BREAKER_TRIPS,
    PUMP_BREAKER_WINDOW_S,
    REASON_BOOK,
    REASON_CATALOGUE,
    REASON_PUMP,
    REASON_TRADE_GAP,
    REASON_WS,
    WS_GRACE_S,
    IngestionService,
)
from candleviewer.observability.health import HealthStatus


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class _Ws:
    def __init__(self, clock: _Clock) -> None:
        self._clock, self.phase, self.since = clock, PHASE_OPEN, clock()

    def set(self, phase: str) -> None:
        self.phase, self.since = phase, self._clock()

    def state(self) -> str:
        return self.phase

    def phase_since(self) -> float:
        return self.since


class _Books:
    def __init__(self) -> None:
        self.bad: tuple[str, ...] = ()
        self.slo: float | None = None

    def out_of_live(self, slo_s: float = 30.0) -> tuple[str, ...]:
        self.slo = slo_s
        return self.bad


class _Trades:
    def __init__(self) -> None:
        self.gaps: dict[str, tuple[int, str]] = {}

    def open_gaps(self) -> dict[str, tuple[int, str]]:
        return dict(self.gaps)


class _Instruments:
    def __init__(self) -> None:
        self.cache = InstrumentCatalogueCache(ttl_seconds=100.0)


def _svc(clock: _Clock) -> IngestionService:
    s = IngestionService(clock=clock, now_us=lambda: int(clock() * 1_000_000))
    s._started = True
    return s


def _reason(s: IngestionService) -> tuple[HealthStatus, str]:
    h = s.health()
    return h.status, h.detail


def test_stopped_service_is_stopped_not_degraded() -> None:
    s = IngestionService()
    assert s.health().status is HealthStatus.STOPPED


def test_no_signals_attached_is_ok() -> None:
    assert _reason(_svc(_Clock())) == (HealthStatus.OK, "")


def test_ws_not_open_degrades_only_past_grace_and_recovers() -> None:
    clock = _Clock()
    s, ws = _svc(clock), _Ws(clock)
    s.ws = cast(Any, ws)
    ws.set(PHASE_CONNECTING)
    clock.t += WS_GRACE_S  # boundary: exactly the grace is still OK
    assert s.health().status is HealthStatus.OK
    clock.t += 0.001
    assert _reason(s) == (HealthStatus.DEGRADED, REASON_WS)
    ws.set(PHASE_OPEN)
    assert s.health().status is HealthStatus.OK


def test_book_out_of_live_degrades_and_recovers() -> None:
    clock = _Clock()
    s, books = _svc(clock), _Books()
    s.books = cast(Any, books)
    assert s.health().status is HealthStatus.OK
    books.bad = ("BTCUSDT",)
    assert _reason(s) == (HealthStatus.DEGRADED, REASON_BOOK)
    books.bad = ()
    assert s.health().status is HealthStatus.OK


def test_book_slo_override_is_forwarded() -> None:
    clock = _Clock()
    s, books = IngestionService(clock=clock, book_slo_s=7.0), _Books()
    s._started, s.books = True, cast(Any, books)
    s.health()
    assert books.slo == 7.0


def test_unrecovered_trade_gap_degrades_and_recovers() -> None:
    clock = _Clock()
    s, trades = _svc(clock), _Trades()
    s.trades = cast(Any, trades)
    trades.gaps["BTCUSDT"] = (1, "frame_loss")
    assert _reason(s) == (HealthStatus.DEGRADED, REASON_TRADE_GAP)
    trades.gaps.clear()
    assert s.health().status is HealthStatus.OK


def test_stale_catalogue_degrades() -> None:
    clock = _Clock()
    s, inst = _svc(clock), _Instruments()
    s.instruments = cast(Any, inst)
    assert _reason(s) == (HealthStatus.DEGRADED, REASON_CATALOGUE)  # never loaded
    from candleviewer.ingestion.instruments import CatalogueSnapshot

    fetched = int(clock() * 1_000_000)
    inst.cache.swap(CatalogueSnapshot(by_symbol={}, fetched_at_us=fetched))
    assert s.health().status is HealthStatus.OK
    clock.t += 101.0
    assert _reason(s) == (HealthStatus.DEGRADED, REASON_CATALOGUE)


async def test_pump_breaker_trip_degrades_for_window_then_recovers() -> None:
    clock = _Clock()
    s = _svc(clock)

    async def boom(frame: str) -> bool:
        return False

    s._dispatch = boom  # type: ignore[method-assign]  # test seam, #1919
    tripped = asyncio.Event()
    real = s._resync_all

    async def resync(reason: str) -> None:
        await real(reason)
        tripped.set()

    s._resync_all = resync  # type: ignore[method-assign]  # test seam, #1919
    for _ in range(PUMP_BREAKER_TRIPS):
        s.ws_frames.put_nowait("x")
    task = asyncio.create_task(s._pump_frames())
    await asyncio.wait_for(tripped.wait(), timeout=5)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert _reason(s) == (HealthStatus.DEGRADED, REASON_PUMP)
    clock.t += PUMP_BREAKER_WINDOW_S + 0.001
    assert s.health().status is HealthStatus.OK


def test_multiple_reasons_are_comma_joined_in_stable_order() -> None:
    clock = _Clock()
    s, ws, trades = _svc(clock), _Ws(clock), _Trades()
    s.ws, s.trades = cast(Any, ws), cast(Any, trades)
    ws.set(PHASE_CONNECTING)
    clock.t += WS_GRACE_S + 1
    trades.gaps["X"] = (1, "r")
    assert s.health().detail == f"{REASON_WS},{REASON_TRADE_GAP}"


def test_health_never_queries_a_gateway_or_interpreter() -> None:
    clock = _Clock()
    s = _svc(clock)

    class _Strict(_Ws):
        def __getattr__(self, name: str) -> Any:
            pytest.fail(f"health() touched {name}")

    s.ws = cast(Any, _Strict(clock))
    assert s.health().status is HealthStatus.OK
