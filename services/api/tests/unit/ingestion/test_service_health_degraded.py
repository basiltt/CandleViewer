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
from candleviewer.ingestion.instruments import CatalogueSnapshot, InstrumentCatalogueCache
from candleviewer.ingestion.service import (
    PUMP_BREAKER_TRIPS,
    PUMP_BREAKER_WINDOW_S,
    WS_GRACE_S,
    HealthReason,
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
    assert _reason(s) == (HealthStatus.DEGRADED, HealthReason.WS_NOT_OPEN)
    ws.set(PHASE_OPEN)
    assert s.health().status is HealthStatus.OK


def test_book_out_of_live_degrades_and_recovers() -> None:
    clock = _Clock()
    s, books = _svc(clock), _Books()
    s.books = cast(Any, books)
    assert s.health().status is HealthStatus.OK
    books.bad = ("BTCUSDT",)
    assert _reason(s) == (HealthStatus.DEGRADED, HealthReason.BOOK_OUT_OF_LIVE)
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
    assert _reason(s) == (HealthStatus.DEGRADED, HealthReason.TRADE_GAP_UNRECOVERED)
    trades.gaps.clear()
    assert s.health().status is HealthStatus.OK


def test_stale_catalogue_degrades() -> None:
    clock = _Clock()
    s, inst = _svc(clock), _Instruments()
    s.instruments = cast(Any, inst)
    assert _reason(s) == (HealthStatus.DEGRADED, HealthReason.CATALOGUE_STALE)  # never loaded
    fetched = int(clock() * 1_000_000)
    inst.cache.swap(CatalogueSnapshot(by_symbol={}, fetched_at_us=fetched))
    assert s.health().status is HealthStatus.OK
    clock.t += 101.0
    assert _reason(s) == (HealthStatus.DEGRADED, HealthReason.CATALOGUE_STALE)


class _Boom:
    """Parser that always faults; `mark_gap` fires only from the breaker's resync."""

    def __init__(self) -> None:
        self.resynced = asyncio.Event()

    async def handle_frame(self, frame: str) -> None:
        raise RuntimeError("parser fault")

    def mark_gap(self, reason: str, symbol: str | None = None) -> None:
        self.resynced.set()

    def open_gaps(self) -> dict[str, tuple[int, str]]:
        return {}


async def _trip(s: IngestionService) -> None:
    boom = _Boom()
    s.trades = cast(Any, boom)
    for _ in range(PUMP_BREAKER_TRIPS):
        s.ws_frames.put_nowait("{}")
    task = asyncio.create_task(s._pump_frames())
    try:
        await asyncio.wait_for(boom.resynced.wait(), timeout=5)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_pump_breaker_trip_degrades_for_window_then_recovers() -> None:
    clock = _Clock()
    s = _svc(clock)
    await _trip(s)
    assert s.pump_breaker_trips == 1
    s.trades = None
    clock.t += PUMP_BREAKER_WINDOW_S  # exact boundary: still open
    assert _reason(s) == (HealthStatus.DEGRADED, HealthReason.PUMP_BREAKER_OPEN)
    clock.t += 0.001
    assert s.health().status is HealthStatus.OK


def test_multiple_reasons_are_comma_joined_in_stable_order() -> None:
    clock = _Clock()
    s, ws, trades = _svc(clock), _Ws(clock), _Trades()
    s.ws, s.trades = cast(Any, ws), cast(Any, trades)
    ws.set(PHASE_CONNECTING)
    clock.t += WS_GRACE_S + 1
    trades.gaps["X"] = (1, "r")
    assert s.health().detail == f"{HealthReason.WS_NOT_OPEN},{HealthReason.TRADE_GAP_UNRECOVERED}"


def test_health_reads_only_plain_phase_signals_never_the_interpreter() -> None:
    clock = _Clock()
    s = _svc(clock)
    calls: list[str] = []

    class _Gateway:
        @property
        def _interp(self) -> Any:
            pytest.fail("health() touched the interpreter")

        def state(self) -> str:
            calls.append("state")
            return PHASE_OPEN

        def phase_since(self) -> float:
            calls.append("phase_since")
            return clock()

        def __getattr__(self, name: str) -> Any:
            pytest.fail(f"health() touched {name}")

    s.ws = cast(Any, _Gateway())
    assert s.health().status is HealthStatus.OK
    assert set(calls) <= {"state", "phase_since"}
