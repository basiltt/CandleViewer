"""Lifecycle contract for the ingestion module (M6).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. This ticket
(E02-T12) adds the *synthetic* feed path only (`CV_FEED=synthetic`): the real
Bybit ingestion path (`CV_FEED=live`) is scaffolded but not implemented until
E08 lands.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from candleviewer.exchange.base import Ticker, Trade
from candleviewer.ingestion.clock import ClockGuard
from candleviewer.ingestion.connection import ConnectionManager
from candleviewer.ingestion.instruments_refresh import InstrumentsRefreshScheduler
from candleviewer.ingestion.synthetic_feed import (
    SyntheticFeedGenerator,
    SyntheticFeedMetrics,
    load_sample_records,
)
from candleviewer.ingestion.ticker_stream import TickerStream
from candleviewer.observability.context import spawn
from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.observability.latency import StageRecorder
from candleviewer.settings import FeedMode

if TYPE_CHECKING:
    from candleviewer.app import AppContext

_QUEUE_MAXSIZE = 256
#: E08-T04: bounded raw-frame buffer between the WS reader and parsers (C-2.18).
#: Overflow policy: drop-newest and count (`ws_frames_dropped`); the
#: staleness watchdog recycles the socket if consumers fall behind for long.
WS_FRAME_QUEUE_MAXSIZE = 4096


class IngestionService:
    """M6 `ingestion` module lifecycle: synthetic feed only (E02-T12)."""

    def __init__(self) -> None:
        self._started = False
        self.queue: asyncio.Queue[Trade | Ticker] | None = None
        self._generator: SyntheticFeedGenerator | None = None
        #: E08-S01-2: the instrument catalogue scheduler, attached by the
        #: composition root only when a real exchange + Postgres are wired.
        self.instruments: InstrumentsRefreshScheduler | None = None
        #: E08-T04: public WS connection, attached only when
        #: `ingestion_ws_enabled` is on (composition root, `create_app`).
        self.ws: ConnectionManager | None = None
        self.ws_frames: asyncio.Queue[str] = asyncio.Queue(maxsize=WS_FRAME_QUEUE_MAXSIZE)
        self.ws_frames_dropped = 0
        #: E04-T06: stage-latency recorder + exchange clock-offset provider
        #: (ClockGuard's offset in ms once E08 wires it; None = unmeasured).
        self.latency: StageRecorder | None = None
        self.clock_offset_ms: Callable[[], int | None] = lambda: 0
        self.clock: ClockGuard | None = None
        self._closers: list[Callable[[], Awaitable[None]]] = []
        #: E08-S03: ticker demand/merge/publish, attached with the public WS.
        self.tickers: TickerStream | None = None
        self._pump: asyncio.Task[None] | None = None

    def attach_latency(
        self, recorder: StageRecorder, clock_offset_ms: Callable[[], int | None] | None = None
    ) -> None:
        """Wire the per-stage latency recorder into the publish path."""
        self.latency = recorder
        if clock_offset_ms is not None:
            self.clock_offset_ms = clock_offset_ms
        if self.ws is not None:
            self.ws.attach_latency(recorder, self._ws_clock_offset_ms)

    def attach_clock(self, guard: ClockGuard) -> None:
        """E04-T06: ClockGuard's measured exchange-local offset (REST
        `/v5/market/time`) feeds every `on_event`/`record` call."""
        self.clock = guard
        self.clock_offset_ms = guard.offset_ms_or_none

    def attach_closer(self, closer: Callable[[], Awaitable[None]]) -> None:
        """Resource (e.g. the clock REST client) to close on `stop()`."""
        self._closers.append(closer)

    def _ws_clock_offset_ms(self) -> int | None:
        # Real exchange frames: unmeasured offset => exchange stage unavailable.
        return self.clock.offset_ms_or_none() if self.clock is not None else None

    def offer_frame(self, frame: str) -> None:
        """Reader callback: never blocks the read loop (drop-newest on full)."""
        try:
            self.ws_frames.put_nowait(frame)
        except asyncio.QueueFull:
            self.ws_frames_dropped += 1

    def attach_ws(self, manager: ConnectionManager) -> None:
        """Hand this module ownership of the public WS connection lifecycle."""
        self.ws = manager

    def attach_tickers(self, stream: TickerStream) -> None:
        self.tickers = stream

    async def _pump_frames(self, stream: TickerStream) -> None:
        """Drain the bounded raw-frame queue into the ticker stream."""
        while True:
            await stream.handle_frame(await self.ws_frames.get())

    def attach_instruments(self, scheduler: InstrumentsRefreshScheduler) -> None:
        """Hand this module ownership of the catalogue scheduler's lifecycle."""
        self.instruments = scheduler

    async def start(self, ctx: AppContext) -> None:
        """Start the module.

        `CV_FEED=synthetic` (the dev/CI default) starts the replay generator
        against a bounded queue. `CV_FEED=live` is a scaffold no-op here —
        `Settings` already refuses to construct in that mode without
        credentials (fail-fast, acceptance criterion 3); the real adapter
        wiring is E08's.
        """
        settings = ctx.settings
        if settings.feed is FeedMode.SYNTHETIC:
            self.queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
            records = load_sample_records(Path(settings.feed_sample_path))
            metrics = SyntheticFeedMetrics(ctx.metrics)
            self._generator = SyntheticFeedGenerator(
                records=records,
                queue=self.queue,
                metrics=metrics,
                rate_hz=settings.feed_rate_hz,
                latency=self.latency,
                clock_offset_ms=lambda: self.clock_offset_ms(),
            )
            await self._generator.start()
        if self.instruments is not None:
            await self.instruments.start()
        if self.clock is not None:
            await self.clock.start()
        if self.ws is not None:
            await self.ws.start()
        if self.tickers is not None:
            await self.tickers.start()
            self._pump = spawn(self._pump_frames(self.tickers), name="ticker-frame-pump")
        self._started = True

    async def stop(self, grace_s: float) -> None:
        """Stop the module within `grace_s` seconds."""
        pump, self._pump = self._pump, None
        if pump is not None:
            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)
        if self.tickers is not None:
            await self.tickers.stop()
        if self.ws is not None:
            async with asyncio.timeout(grace_s):
                await self.ws.stop()
        if self.clock is not None:
            await self.clock.stop()
        for close in self._closers:
            await close()
        self._closers.clear()
        if self.instruments is not None:
            await self.instruments.stop(grace_s)
        if self._generator is not None:
            await self._generator.stop()
            self._generator = None
        self._started = False

    def health(self) -> HealthReport:
        """Report module health. `ok` once started (synthetic or scaffold)."""
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        return HealthReport(module="ingestion", status=status, detail="")
