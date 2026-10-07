"""Regression (#2005, sweep of #1898/#1921/#2004): ingestion modules resolve their structlog logger
per emit. `cache_logger_on_first_use=True` pins a module-level logger to the processor chain live
at first use, so after `configure_logging()` re-runs, `capture_logs()` would miss its events."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

from structlog.testing import capture_logs

from candleviewer.bus.bus import Bus
from candleviewer.exchange.bybit.ticker import parse_ticker_frame, ticker_topic
from candleviewer.exchange.bybit.trades import parse_trade_frame, trade_topic
from candleviewer.ingestion import connection
from candleviewer.ingestion.dispatch import Lane
from candleviewer.ingestion.instruments_refresh import InstrumentsRefreshScheduler
from candleviewer.ingestion.kline_backfill import KlineBackfillError, KlineBackfillService
from candleviewer.ingestion.ticker_stream import TickerStream
from candleviewer.ingestion.trade_stream import TradeStream
from candleviewer.observability.logging import configure_logging


async def _survives(emit: Callable[[], Awaitable[None]], event: str) -> None:
    """First use binds the logger; reconfigure; the event must still be captured."""
    configure_logging(env="demo")
    await emit()
    configure_logging(env="demo")
    with capture_logs() as logs:
        await emit()
    assert event in [e["event"] for e in logs]


async def test_dispatch_overflow_log_survives_reconfiguration() -> None:
    async def emit() -> None:
        Lane(route=None)._drop()  # dropped == 0 -> logs

    await _survives(emit, "dispatch lane full; frame dropped, resync queued")


async def test_instruments_refresh_log_survives_reconfiguration() -> None:
    class _Repo:
        async def load_all(self) -> list[Any]:
            raise OSError("storage down")

    async def _fetch(_now: Callable[[], int]) -> Any:
        raise OSError("down")

    async def _sleep(delay: float) -> None:
        if delay > 1_000:
            await asyncio.Event().wait()

    async def emit() -> None:
        sched = InstrumentsRefreshScheduler(
            fetch_instruments_info=_fetch,
            repository=_Repo(),  # type: ignore[arg-type]
            publish=lambda _e: asyncio.sleep(0),
            now_us=lambda: 1,
            sleep=_sleep,
            random_fn=lambda: 0.0,
        )
        try:
            await sched.start()
        finally:
            await sched.stop(grace_s=1.0)

    await _survives(emit, "instruments_startup_load_failed")


async def test_kline_backfill_log_survives_reconfiguration() -> None:
    async def _boom(*_a: Any, **_k: Any) -> Any:
        raise OSError("down")

    async def _cache_read(*_a: Any, **_k: Any) -> list[Any]:
        return []

    async def emit() -> None:
        svc = KlineBackfillService(
            fetch_klines=_boom,
            cache=None,  # type: ignore[arg-type]
            max_retries=1,
            sleep=lambda _s: asyncio.sleep(0),
        )
        try:
            await svc._fetch_page_with_retry("BTCUSDT", "1", 0, 60_000_000)
        except KlineBackfillError:
            pass

    await _survives(emit, "kline_backfill_page_failed")


async def test_ticker_stream_log_survives_reconfiguration() -> None:
    class _Writer:
        async def write_ticker(self, _e: Any) -> None:
            raise OSError("down")

    async def emit() -> None:
        stream = TickerStream(
            bus=Bus(),
            env="live",
            set_desired=lambda _d: None,
            parse_frame=parse_ticker_frame,
            topic_for=ticker_topic,
            is_listed=lambda _s: True,
            touch=lambda _t: None,
            clock=lambda: 0.0,
            now_us=lambda: 1,
            writer=_Writer(),
        )
        stream._writes.put_nowait(type("E", (), {"symbol": "BTCUSDT"})())
        task = asyncio.create_task(stream._write_loop())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        task.cancel()

    await _survives(emit, "ticker write-behind failed")


async def test_trade_stream_log_survives_reconfiguration() -> None:
    class _Writer:
        async def write_trades(self, _b: Any) -> None:
            raise OSError("down")

    async def _noop_backoff() -> None:
        return None

    async def emit() -> None:
        stream = TradeStream(
            bus=Bus(),
            env="live",
            set_desired=lambda _d: None,
            parse_frame=parse_trade_frame,
            topic_for=trade_topic,
            is_listed=lambda _s: True,
            touch=lambda _t: None,
            fetch_recent=None,
            tick_size=lambda _s: Decimal("0.10"),
            clock=lambda: 0.0,
            now_us=lambda: 1,
            writer=_Writer(),
        )
        stream._writes.backoff = _noop_backoff  # type: ignore[method-assign]
        stream._writes.put(type("E", (), {})())
        await stream.drain_writes()

    await _survives(emit, "trade write-behind failed; requeued")


def test_connection_has_no_module_level_logger() -> None:
    """connection.py emits nothing today; guard against re-adding a cached module-level logger."""
    assert not hasattr(connection, "logger")
    assert not hasattr(connection, "structlog")
