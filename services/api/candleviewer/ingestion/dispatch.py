"""Per-topic frame dispatch lanes behind the WS frame pump (#1916, #1905).

`06-performance-and-load-standard.md` §6.1 requires per-symbol task isolation:
a burst or a stall on one symbol must not starve another. The pump only
routes each raw frame (`FrameRoute`, injected by the adapter — C-2.2) and
touches the staleness watchdog (venue freshness); every topic (one stream x
one symbol) then has its own bounded queue drained by its own worker task.
A slow `NEVER_DROP` consumer on `BTCUSDT` book (#1916) or a trade-gap REST
backfill on one symbol (#1905) now only holds that one lane.

Overflow policy (C-2.18), per lane: the newest frame is dropped and counted
(`ingest_dispatch_overflow_total{stream}`; symbol is deliberately not a label,
the log line carries it, rate-limited per lane). Dropping is a discontinuity,
so the lane enqueues a resync marker ahead of the next frame it accepts: the
worker then calls `on_overflow(route)` (book -> resync that symbol from a
snapshot, trade -> open a gap so the REST backfill heals it) *before* any later
frame is applied. Drop-oldest is never used: it would silently splice a
delta stream. Plain code, never a statechart (C-2.20).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Final, NamedTuple

import structlog

from candleviewer.ingestion.metrics import ingest_dispatch_overflow_total
from candleviewer.observability.context import spawn

logger = structlog.get_logger(__name__)

#: Frames buffered per lane (~2 s of a busy book topic at 50 ms pushes x 20).
LANE_MAXSIZE: Final[int] = 1024
#: Hard cap on lanes; further topics share one fallback lane (hostile topics
#: cannot create unbounded tasks).
MAX_LANES: Final[int] = 1024
FALLBACK_KEY: Final[str] = "_shared"
#: At most one overflow log line per lane per this many dropped frames.
_LOG_EVERY: Final[int] = 1000


class FrameRoute(NamedTuple):
    """Venue-neutral routing key for one raw frame."""

    topic: str  # the venue topic, as the watchdog watches it
    stream: str  # "book" | "trade" | "ticker" | other
    symbol: str


class _Resync:
    """Queue marker: frames were dropped right before this point."""

    __slots__ = ()


RESYNC: Final = _Resync()


@dataclass(slots=True)
class Lane:
    route: FrameRoute | None
    queue: asyncio.Queue[str | _Resync] = field(
        default_factory=lambda: asyncio.Queue(maxsize=LANE_MAXSIZE)
    )
    pending_resync: bool = False
    dropped: int = 0

    def offer(self, frame: str) -> bool:
        """Never blocks. False when the frame was dropped (lane full)."""
        q = self.queue
        need = 2 if self.pending_resync else 1
        if q.maxsize - q.qsize() < need:
            self._drop()
            return False
        if self.pending_resync:
            q.put_nowait(RESYNC)
            self.pending_resync = False
        q.put_nowait(frame)
        return True

    def _drop(self) -> None:
        self.pending_resync = True
        stream = self.route.stream if self.route is not None else "unrouted"
        ingest_dispatch_overflow_total.labels(stream=stream).inc()
        if self.dropped % _LOG_EVERY == 0:
            logger.warning(
                "dispatch lane full; frame dropped, resync queued",
                stream=stream,
                symbol=self.route.symbol if self.route is not None else None,
                dropped=self.dropped + 1,
            )
        self.dropped += 1


class LaneSet:
    """Owns the lanes and their worker tasks (every task tracked, C-2.18;
    `aclose()` cancels and awaits them all). Stop policy: queued frames are
    discarded — the socket is closing and every stream resyncs on restart."""

    def __init__(
        self,
        handle: Callable[[str], Awaitable[bool]],
        on_overflow: Callable[[FrameRoute], Awaitable[None]],
        on_breaker: Callable[[FrameRoute | None], Awaitable[None]],
        breaker_trips: Callable[[], int],
    ) -> None:
        self._handle = handle
        self._tasks: set[asyncio.Task[None]] = set()
        self._on_overflow, self._on_breaker = on_overflow, on_breaker
        self._breaker_trips = breaker_trips
        self.lanes: dict[str, Lane] = {}

    def lane_for(self, route: FrameRoute | None) -> Lane:
        key = route.topic if route is not None else FALLBACK_KEY
        lane = self.lanes.get(key)
        if lane is None:
            if len(self.lanes) >= MAX_LANES and key != FALLBACK_KEY:
                return self.lane_for(None)
            lane = Lane(route)
            self.lanes[key] = lane
            task = spawn(self._work(lane), name=f"ws-dispatch:{key[:64]}")
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return lane

    async def aclose(self) -> None:
        """Cancel every lane worker and wait for each to finish."""
        tasks = list(self._tasks)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    async def _resync(self, lane: Lane) -> None:
        if lane.route is None:
            return
        try:
            await self._on_overflow(lane.route)
        except asyncio.CancelledError:
            raise
        except Exception:  # resync is best effort; frames keep flowing
            logger.exception("dispatch overflow resync failed")

    async def _work(self, lane: Lane) -> None:
        """Drain one lane forever; never raises (a raise would cancel the
        pump's lanes). Per-frame isolation as in #1889."""
        consecutive = 0
        while True:
            if lane.pending_resync and lane.queue.empty():
                # Drops happened after everything already applied and no frame
                # has been accepted since: resync now, not on the next frame.
                lane.pending_resync = False
                await self._resync(lane)
                continue
            item = await lane.queue.get()
            if isinstance(item, _Resync):
                await self._resync(lane)
                continue
            if await self._handle(item):
                consecutive = 0
                continue
            consecutive += 1
            if consecutive >= self._breaker_trips():
                consecutive = 0
                await self._on_breaker(lane.route)  # scoped to this lane's symbol


__all__ = ["FALLBACK_KEY", "LANE_MAXSIZE", "MAX_LANES", "FrameRoute", "Lane", "LaneSet"]
