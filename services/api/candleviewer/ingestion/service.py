"""Lifecycle contract for the ingestion module (M6).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. This ticket
(E02-T12) adds the *synthetic* feed path only (`CV_FEED=synthetic`): the real
Bybit ingestion path (`CV_FEED=live`) is scaffolded but not implemented until
E08 lands.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from candleviewer.exchange.base import Ticker, Trade
from candleviewer.ingestion.instruments_refresh import InstrumentsRefreshScheduler
from candleviewer.ingestion.synthetic_feed import (
    SyntheticFeedGenerator,
    SyntheticFeedMetrics,
    load_sample_records,
)
from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.settings import FeedMode

if TYPE_CHECKING:
    from candleviewer.app import AppContext

_QUEUE_MAXSIZE = 256


class IngestionService:
    """M6 `ingestion` module lifecycle: synthetic feed only (E02-T12)."""

    def __init__(self) -> None:
        self._started = False
        self.queue: asyncio.Queue[Trade | Ticker] | None = None
        self._generator: SyntheticFeedGenerator | None = None
        #: E08-S01-2: the instrument catalogue scheduler, attached by the
        #: composition root only when a real exchange + Postgres are wired.
        self.instruments: InstrumentsRefreshScheduler | None = None

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
            )
            await self._generator.start()
        if self.instruments is not None:
            await self.instruments.start()
        self._started = True

    async def stop(self, grace_s: float) -> None:
        """Stop the module within `grace_s` seconds."""
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
