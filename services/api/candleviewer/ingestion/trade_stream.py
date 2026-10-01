"""Live trade tape: subscribe once, normalise, dedupe by trade id, gap-backfill (E08-S04).

Every derived view (bars, footprint, CVD, bubbles) is a cache over this stream
(`24-internal-schemas.md` §13), so a duplicate or a hole changes delta. Rules:

* **Exactly once** — a bounded per-symbol `DedupeRing` (deque + set) drops any
  trade id already published; memory never grows with uptime.
* **Gaps are never hidden** — on reconnect (`resubscribing`/`degraded`) or a
  lost raw frame the window opens at the last published print. The first live
  batch after it closes the window: a REST recent-trade backfill is merged with
  that batch in `(ts_event, trade_id)` order, deduped, and published *before*
  any later print (no consumer sees time move backwards). A `GapEvent` with
  explicit bounds and a text label is published either way; `recovered=False`
  when the backfill failed or did not reach back to the gap start.
* **Never drop** — prints go to the bus with `NEVER_DROP` subscribers, so a slow
  consumer back-pressures this reader (`ingest_queue_full_total{class}`).

Plain code, never a statechart (catalogue §1.2 hot-path exclusion). Venue
parsing and REST are injected (C-2.2): this module sees only `TradePrint`s.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

import structlog

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, Topic, TopicPattern
from candleviewer.domain.primitives import EventId
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.exchange.base.trade_print import TradePrint
from candleviewer.ingestion.metrics import (
    ingest_events_total,
    ingest_lag_seconds,
    questdb_write_queue_depth,
    trade_backfill_rows_total,
    trade_duplicates_suppressed_total,
    trade_gaps_total,
    trade_prints_rejected_total,
    trade_writes_dropped_total,
)
from candleviewer.ingestion.planner import DEFAULT_GRACE_S, DemandTracker
from candleviewer.ingestion.ticker_stream import UnknownSymbolError, uuid7
from candleviewer.ingestion.watchdog import FeedHealthEvent
from candleviewer.observability.context import spawn

logger = structlog.get_logger(__name__)

#: Per-symbol recent-id capacity: 5 000 prints/s x a 10 s reconnect window,
#: rounded up; well past a 1 000-row backfill page.
DEDUPE_CAPACITY = 50_000
WRITE_QUEUE_MAXSIZE = 8192
BACKFILL_TIMEOUT_S = 5.0


class TradeWriter(Protocol):
    async def write_trades(self, events: Sequence[TradeEvent]) -> None: ...


@dataclass(frozen=True, slots=True)
class GapEvent:
    """A tape window with possibly missing prints, published on `{env}.md.{sym}.gap`."""

    symbol: str
    start_us: int
    end_us: int
    recovered: bool
    reason: str  # "reconnect" | "frame_loss"

    def label(self) -> str:
        """Words, not a colour band (a11y note): `No data 12:03:11-12:03:19`."""

        def hms(us: int) -> str:
            return datetime.fromtimestamp(us / 1e6, tz=UTC).strftime("%H:%M:%S")

        prefix = "Backfilled" if self.recovered else "No data"
        return f"{prefix} {hms(self.start_us)}-{hms(self.end_us)}"


class DedupeRing:
    """Fixed-capacity recent-id set: O(1) lookup, oldest evicted first."""

    def __init__(self, capacity: int = DEDUPE_CAPACITY) -> None:
        self._order: deque[str] = deque()
        self._ids: set[str] = set()
        self._cap = capacity

    def __len__(self) -> int:
        return len(self._ids)

    def add(self, trade_id: str) -> bool:
        """True if new (and now remembered); False for a duplicate."""
        if trade_id in self._ids:
            return False
        if len(self._order) >= self._cap:
            self._ids.discard(self._order.popleft())
        self._order.append(trade_id)
        self._ids.add(trade_id)
        return True


def merge_ordered(*batches: Iterable[TradePrint]) -> list[TradePrint]:
    """Union by trade id, ordered by `(ts_event, trade_id)` (§2.1, C4)."""
    seen: dict[str, TradePrint] = {}
    for batch in batches:
        for p in batch:
            seen.setdefault(p.trade_id, p)
    return sorted(seen.values(), key=lambda p: (p.ts_event_us, p.trade_id))


def _now_us() -> int:
    return time.time_ns() // 1000


class TradeStream:
    """Refcounted `publicTrade.{symbol}` demand + dedupe + gap backfill + publish."""

    def __init__(
        self,
        *,
        bus: Bus,
        env: str,
        set_desired: Callable[[set[str]], None],
        parse_frame: Callable[[str], list[TradePrint] | None],
        topic_for: Callable[[str], str],
        is_listed: Callable[[str], bool],
        touch: Callable[[str], None],
        fetch_recent: Callable[[str], Awaitable[Sequence[TradePrint]]] | None = None,
        tick_size: Callable[[str], Decimal | None] = lambda _s: None,
        clock: Callable[[], float] = time.monotonic,
        now_us: Callable[[], int] = _now_us,
        grace_s: float = DEFAULT_GRACE_S,
        writer: TradeWriter | None = None,
        dedupe_capacity: int = DEDUPE_CAPACITY,
        backfill_timeout_s: float = BACKFILL_TIMEOUT_S,
    ) -> None:
        self._bus, self._env = bus, env
        self._set_desired, self._parse = set_desired, parse_frame
        self._topic_for, self._is_listed, self._touch = topic_for, is_listed, touch
        self._fetch, self._tick_size = fetch_recent, tick_size
        self._clock, self._now_us = clock, now_us
        self._demand = DemandTracker(clock, grace_s)
        self._writer, self._cap, self._bf_timeout = writer, dedupe_capacity, backfill_timeout_s
        self._rings: dict[str, DedupeRing] = {}
        self._last_ts: dict[str, int] = {}  # last published ts_event per symbol
        self._seq: dict[str, int] = {}
        self._gap_open: dict[str, tuple[int, str]] = {}  # symbol -> (start_us, reason)
        self._recent: dict[str, deque[TradeEvent]] = {}
        self._gaps: dict[str, deque[GapEvent]] = {}
        self._writes: asyncio.Queue[TradeEvent] = asyncio.Queue(maxsize=WRITE_QUEUE_MAXSIZE)
        self._tasks: list[asyncio.Task[None]] = []
        self._health = bus.subscribe(
            "trade-stream-health",
            TopicPattern(env=env, domain="health", detail="feed"),
            QueuePolicy.NEVER_DROP,
            maxsize=1024,
        )

    # ---- demand ---------------------------------------------------------
    def acquire(self, consumer: str, symbol: str) -> None:
        if not self._is_listed(symbol):
            raise UnknownSymbolError(symbol)
        self._demand.acquire(consumer, symbol)
        self.sync()

    def release(self, consumer: str, symbol: str) -> None:
        self._demand.release(consumer, symbol)
        self.sync()

    def sync(self) -> None:
        wanted = self._demand.desired()
        self._set_desired({self._topic_for(s) for s in wanted})
        for gone in set(self._rings) - wanted:
            for d in (self._rings, self._last_ts, self._gap_open):
                d.pop(gone, None)

    # ---- reads (GET /market/trades) --------------------------------------
    def is_listed(self, symbol: str) -> bool:
        return self._is_listed(symbol)

    def tick_size(self, symbol: str) -> Decimal | None:
        return self._tick_size(symbol)

    def recent(self, symbol: str) -> list[TradeEvent]:
        return list(self._recent.get(symbol, ()))

    def gaps(self, symbol: str) -> list[GapEvent]:
        return list(self._gaps.get(symbol, ()))

    def open_gaps(self) -> dict[str, tuple[int, str]]:
        return dict(self._gap_open)

    # ---- gaps -----------------------------------------------------------
    def mark_gap(self, reason: str, symbol: str | None = None) -> None:
        """Open a gap window at the last published print (reconnect / frame loss)."""
        for sym in [symbol] if symbol else list(self._last_ts):
            if sym in self._last_ts and sym not in self._gap_open:
                self._gap_open[sym] = (self._last_ts[sym], reason)

    async def _backfill(self, symbol: str) -> list[TradePrint] | None:
        if self._fetch is None:
            trade_backfill_rows_total.labels(result="unavailable").inc()
            return None
        try:
            async with asyncio.timeout(self._bf_timeout):
                rows = list(await self._fetch(symbol))
        except asyncio.CancelledError:
            raise
        except Exception:  # rate-limited / network / malformed: gap stays unrecovered
            trade_backfill_rows_total.labels(result="error").inc()
            logger.warning("trade backfill failed", symbol=symbol)
            return None
        trade_backfill_rows_total.labels(result="ok").inc(len(rows))
        return rows

    # ---- frames ---------------------------------------------------------
    async def handle_frame(self, frame: str) -> None:
        try:
            prints = self._parse(frame)
        except ValueError:
            trade_prints_rejected_total.inc()
            logger.warning("trade frame rejected")
            return
        if not prints:
            return
        sym = prints[0].symbol
        if sym not in self._demand.desired():
            return
        self._touch(self._topic_for(sym))
        ts_ingest = self._now_us()
        live = sorted(prints, key=lambda p: (p.ts_event_us, p.trade_id))
        gap = self._gap_open.pop(sym, None)
        if gap is None:
            await self._publish_all(sym, [(p, "live") for p in live], ts_ingest)
            return
        start_us, reason = gap
        backfill = await self._backfill(sym)
        end_us = live[0].ts_event_us
        rows = [p for p in (backfill or ()) if p.symbol == sym]
        recovered = bool(rows) and min(p.ts_event_us for p in rows) <= start_us
        live_ids = {p.trade_id for p in live}
        merged = merge_ordered(live, rows)
        gev = GapEvent(sym, start_us, end_us, recovered, reason)
        self._gaps.setdefault(sym, deque(maxlen=256)).append(gev)
        trade_gaps_total.labels(symbol=sym, recovered=str(recovered).lower()).inc()
        await self._bus.publish(Topic(env=self._env, domain="md", symbol=sym, detail="gap"), gev)
        tagged = [(p, "live" if p.trade_id in live_ids else "backfill") for p in merged]
        await self._publish_all(sym, tagged, ts_ingest)

    async def _publish_all(
        self, sym: str, prints: list[tuple[TradePrint, str]], ts_ingest: int
    ) -> None:
        ring = self._rings.setdefault(sym, DedupeRing(self._cap))
        topic = Topic(env=self._env, domain="md", symbol=sym, detail="trade")
        floor = self._last_ts.get(sym)
        for p, source in prints:
            if not ring.add(p.trade_id):
                trade_duplicates_suppressed_total.labels(symbol=sym).inc()
                continue
            if source == "backfill" and floor is not None and p.ts_event_us < floor:
                continue  # pre-gap history: publishing it would move time backwards
            event = self._event(p, source, ts_ingest)
            ingest_events_total.labels(stream="trade", symbol=sym).inc()
            await self._bus.publish(topic, event)  # NEVER_DROP subscribers back-pressure us
            self._last_ts[sym] = max(self._last_ts.get(sym, 0), p.ts_event_us)
            recent = self._recent.setdefault(sym, deque(maxlen=1000))
            recent.append(event)
            self._enqueue_write(event)
        if prints:
            ingest_lag_seconds.labels(stream="trade").set(
                max(0.0, (ts_ingest - prints[-1][0].ts_event_us) / 1e6)
            )

    def _event(self, p: TradePrint, source: str, ts_ingest: int) -> TradeEvent:
        seq = self._seq.get(p.symbol, 0) + 1
        self._seq[p.symbol] = seq
        tick = self._tick_size(p.symbol)
        ticks = int((p.price / tick).to_integral_value()) if tick else 0
        return TradeEvent.model_validate(
            {
                "event_id": EventId(uuid7(p.ts_event_us // 1000)),
                "ts_event": p.ts_event_us,
                "ts_ingest": ts_ingest,
                "source": source,
                "symbol": p.symbol,
                "trade_id": p.trade_id,
                "price": p.price,
                "qty": p.qty,
                "side": p.side,
                "is_block_trade": p.is_block_trade,
                "price_ticks": ticks,
                "notional": p.price * p.qty,
                "seq": seq,
            }
        )

    def _enqueue_write(self, event: TradeEvent) -> None:
        if self._writer is None:
            return
        if self._writes.full():  # write-behind never blocks the reader
            with contextlib.suppress(asyncio.QueueEmpty):
                self._writes.get_nowait()
            trade_writes_dropped_total.inc()
        self._writes.put_nowait(event)
        questdb_write_queue_depth.labels(table="trades").set(self._writes.qsize())

    # ---- loops / lifecycle -------------------------------------------------
    async def process_health(self, event: FeedHealthEvent) -> None:
        if event.state in ("resubscribing", "degraded"):
            self.mark_gap("reconnect")

    async def _health_loop(self) -> None:
        while True:
            ev = await self._health.get()
            if isinstance(ev, FeedHealthEvent):
                await self.process_health(ev)

    async def drain_writes(self, max_batch: int = 500) -> int:
        """Write one batch (blocks for the first row); returns rows written."""
        batch = [await self._writes.get()]
        while len(batch) < max_batch and not self._writes.empty():
            batch.append(self._writes.get_nowait())
        questdb_write_queue_depth.labels(table="trades").set(self._writes.qsize())
        try:
            if self._writer is not None:
                await self._writer.write_trades(batch)
        except Exception:  # write-behind must never take ingest down
            logger.warning("trade write-behind failed", rows=len(batch))
        return len(batch)

    async def _write_loop(self) -> None:
        while True:
            await self.drain_writes()

    async def start(self) -> None:
        self._tasks = [
            spawn(self._health_loop(), name="trade-health"),
            spawn(self._write_loop(), name="trade-write-behind"),
        ]

    async def stop(self) -> None:
        tasks, self._tasks = self._tasks, []
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._bus.unsubscribe(self._health)


__all__ = [
    "DEDUPE_CAPACITY",
    "DedupeRing",
    "GapEvent",
    "TradeStream",
    "TradeWriter",
    "merge_ordered",
]
