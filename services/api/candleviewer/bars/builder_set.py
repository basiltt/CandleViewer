"""`BarBuilderSet`: one bus subscription per symbol, fanned to every builder in one pass (E12-T03).

`24-internal-schemas.md` §3.5. Hot path (C-2.20): plain code, no statechart. Bar series have
no catalogue lifecycle (B1-B20), so lease state is plain bookkeeping in `leases.py`.

- **Fan-out.** The first registered spec on a symbol subscribes `{env}.md.{symbol}.trade` with
  `NEVER_DROP` (trades are never dropped: a full queue backpressures `TradeStream`, §4.2).
  One owned task per symbol pops each trade and folds it into every builder of the symbol in
  registration order. It loops over a tuple that is rebuilt only on (un)register, so the
  per-trade loop builds no list. Builders never touch the bus.
- **Runtime (un)register.** The lane lock serialises the trade loop, registration, the clock
  tick and teardown. A spec added mid-stream sees every trade the lane processes after it joins
  (a restored spec also sees the tape after its watermark, below). No trade is dropped.
- **Lifecycle.** `register(spec, symbol, consumer, user)` takes a lease, `release` drops it, and
  the last release starts the 30 s grace (US-MKT-005). `tick()` (every `tick_s`, driven by the
  injected clock) closes time bars on the clock, tears down expired series after writing their
  final blob, and persists every series each `persist_every_us` (60 s). Caps: see `leases.py`.
- **Restart.** A new series loads its blob (`state_store.py`). If the blob is usable it
  restores, then replays from the tape only the trades after the watermark, then goes live.
  Live trades the watermark covers are skipped once, so nothing is applied twice (BI-5). A
  missing or refused blob cold-starts the series (fresh builder, partial first bar). A
  refused blob is also deleted, counted and logged with its `spec_hash`, and it sets
  `health_reason`. A refused blob never raises.
- **Emit.** Live and replayed emissions both go through `EmitRouter` (`emit.py`), stamped with
  `generation` 0. An ADR-0033 rebuild would register a series under a new generation; the
  hook is `_Entry.generation` and is not implemented here.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Final, Protocol

import structlog

from candleviewer.bars.activity_builders import TickBarBuilder, VolumeBarBuilder
from candleviewer.bars.emit import LIVE_GENERATION, EmitRouter
from candleviewer.bars.errors import BarsError, BarSpecError
from candleviewer.bars.leases import DEFAULT_CAPS, SpecCaps, SpecLeases
from candleviewer.bars.metrics import (
    bar_builder_cold_start_seconds,
    bar_builder_cold_starts_total,
    bar_builder_fanout_latency_seconds,
    bar_builder_specs_in_use,
    bar_state_restore_failures_total,
    bar_state_snapshots_written_total,
)
from candleviewer.bars.models import BarBuilder, BarSpec, BarUpdate
from candleviewer.bars.state_store import StateStore, StoredState, Watermark
from candleviewer.bars.time_builder import TimeBarBuilder
from candleviewer.bus.bus import Bus, Subscription
from candleviewer.bus.models import QueuePolicy, Topic
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.observability.context import spawn

PERSIST_EVERY_US: Final = 60_000_000
TICK_S: Final = 1.0
LANE_QUEUE: Final = 4096
#: `health_reason` once any state blob was refused and its series cold-started.
STATE_COLD_STARTED: Final = "bar_state_blob_cold_started"
_RESTORE_ERRORS = (BarsError, ValueError, KeyError, TypeError, IndexError, ArithmeticError)
BuilderFactory = Callable[[BarSpec, str], BarBuilder]


def _log() -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


def default_factory(spec: BarSpec, symbol: str) -> BarBuilder:
    """Builders merged so far; range/delta (E12-S03) and renko (S04) extend this mapping."""
    kinds: dict[str, BuilderFactory] = {
        "time": TimeBarBuilder,
        "tick": TickBarBuilder,
        "volume": VolumeBarBuilder,
    }
    make = kinds.get(spec.kind)
    if make is None:
        raise BarSpecError(f"Bar series of kind '{spec.kind}' are not available yet.")
    return make(spec, symbol)


class TapeSource(Protocol):
    """Recorded trades of a symbol (E12-T02 trades table / recorder), oldest first."""

    async def head_us(self, symbol: str) -> int | None: ...

    def since(self, symbol: str, ts_us: int) -> AsyncIterator[TradeEvent]: ...


class _Mark:
    """Mutable watermark: newest `ts_event` applied and the trade ids applied at it."""

    __slots__ = ("ids", "ts")

    def __init__(self, ts: int = -(2**63), ids: frozenset[str] = frozenset()) -> None:
        self.ts, self.ids = ts, set(ids)

    def advance(self, ts: int, trade_id: str) -> None:
        if ts > self.ts:
            self.ts = ts
            self.ids.clear()
        if ts == self.ts:
            self.ids.add(trade_id)

    def covers(self, ts: int, trade_id: str) -> bool:
        return ts < self.ts or (ts == self.ts and trade_id in self.ids)

    def frozen(self) -> Watermark:
        return Watermark(self.ts, frozenset(self.ids))


@dataclass(slots=True)
class _Entry:
    spec: BarSpec
    builder: BarBuilder
    saved_at: int
    skip: _Mark | None = None  # restored/replayed watermark; cleared once live passes it
    generation: int = LIVE_GENERATION


@dataclass(slots=True)
class _Lane:
    sub: Subscription
    entries: tuple[_Entry, ...] = ()
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    mark: _Mark = field(default_factory=_Mark)
    task: asyncio.Task[None] | None = None


class BarBuilderSet:
    def __init__(
        self,
        bus: Bus,
        env: str,
        router: EmitRouter,
        store: StateStore,
        *,
        tape: TapeSource | None = None,
        now_us: Callable[[], int],
        caps: SpecCaps = DEFAULT_CAPS,
        factory: BuilderFactory = default_factory,
        persist_every_us: int = PERSIST_EVERY_US,
        tick_s: float = TICK_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._bus, self._env, self._router, self._store = bus, env, router, store
        self._tape, self._now, self._factory = tape, now_us, factory
        self._persist_every, self._tick_s, self._sleep = persist_every_us, tick_s, sleep
        self._leases = SpecLeases(caps)
        self._lanes: dict[str, _Lane] = {}
        self._ticker: asyncio.Task[None] | None = None
        self.health_reason: str | None = None

    # -- lifecycle -------------------------------------------------------------------------
    def start(self) -> None:
        if self._ticker is None:
            self._ticker = spawn(self._tick_loop(), name="bars-set-tick")

    async def stop(self) -> None:
        """Cancel the ticker and lane loops, apply what is already queued, write final blobs."""
        if self._ticker is not None:
            self._ticker.cancel()
            await asyncio.gather(self._ticker, return_exceptions=True)
            self._ticker = None
        for symbol in list(self._lanes):
            lane = self._lanes.pop(symbol)
            await self._stop_lane(lane)
            async with lane.lock:
                while lane.sub.qsize():
                    await self._apply(lane, lane.sub.get_nowait())
                saves = [self._stored(lane, e) for e in lane.entries]
            for stored in saves:
                await self._save(stored)
            bar_builder_specs_in_use.labels(symbol=symbol).set(0)

    async def _maybe_close_lane(self, symbol: str) -> None:
        """Drop the symbol's subscription once it has no series and no pending lease."""
        lane = self._lanes.get(symbol)
        if lane is not None and not lane.entries and not self._leases.on_symbol(symbol):
            del self._lanes[symbol]
            await self._stop_lane(lane)

    async def _stop_lane(self, lane: _Lane) -> None:
        if lane.task is not None:
            lane.task.cancel()
            await asyncio.gather(lane.task, return_exceptions=True)
        self._bus.unsubscribe(lane.sub)

    async def _tick_loop(self) -> None:
        while True:
            await self._sleep(self._tick_s)
            await self.tick()

    # -- leases ----------------------------------------------------------------------------
    async def register(
        self, spec: BarSpec, symbol: str, consumer: str, user: str | None = None
    ) -> None:
        """Lease `(symbol, spec)` for `consumer`; builds the series on first lease.

        Raises `SpecCapExceeded` (nothing changed) or `BarSpecError` for an unbuildable kind.
        """
        key = (symbol, spec.spec_hash)
        if not self._leases.acquire(key, consumer, user):
            return
        try:
            builder = self._factory(spec, symbol)
            lane = self._lane(symbol)
            async with lane.lock:
                # A series still in teardown (expired, lock not yet taken) is re-adopted.
                if all(e.spec.spec_hash != key[1] for e in lane.entries):
                    entry = await self._build(spec, symbol, builder)
                    lane.entries = (*lane.entries, entry)
        except BaseException:
            self._leases.drop(key)
            await self._maybe_close_lane(symbol)
            raise
        bar_builder_specs_in_use.labels(symbol=symbol).set(len(lane.entries))

    def release(self, spec_hash: str, symbol: str, consumer: str) -> None:
        self._leases.release((symbol, spec_hash), consumer, self._now())

    def release_consumer(self, consumer: str) -> None:
        """Liveness sweep: a client that vanished without releasing loses all its leases."""
        self._leases.release_consumer(consumer, self._now())

    def active(self, symbol: str) -> tuple[str, ...]:
        lane = self._lanes.get(symbol)
        return () if lane is None else tuple(e.spec.spec_hash for e in lane.entries)

    def _lane(self, symbol: str) -> _Lane:
        lane = self._lanes.get(symbol)
        if lane is None:
            topic = Topic(env=self._env, domain="md", symbol=symbol, detail="trade")
            sub = self._bus.subscribe(
                f"bars.{symbol}", topic.key, QueuePolicy.NEVER_DROP, maxsize=LANE_QUEUE
            )
            lane = self._lanes[symbol] = _Lane(sub)
            lane.task = spawn(self._run(lane), name=f"bars-lane-{symbol}")
        return lane

    # -- restore / replay ------------------------------------------------------------------
    async def _build(self, spec: BarSpec, symbol: str, builder: BarBuilder) -> _Entry:
        t0 = time.perf_counter()
        h = spec.spec_hash
        stored, reason = await self._store.load(symbol, h)
        wm = None if stored is None else stored.watermark
        if wm is not None and self._tape is not None:
            head = await self._tape.head_us(symbol)
            if head is not None and wm.ts_us > head:
                stored, reason = None, "ahead_of_tape"
        if stored is not None:
            try:
                builder.restore(stored.state)
            except _RESTORE_ERRORS:
                stored, reason, builder = None, "restore_failed", self._factory(spec, symbol)
        if reason not in ("ok", "missing"):
            bar_state_restore_failures_total.labels(reason=reason).inc()
            _log().warning("bars_state_blob_discarded", symbol=symbol, spec_hash=h, reason=reason)
            await self._store.delete(symbol, h)
            self.health_reason = STATE_COLD_STARTED
        entry = _Entry(spec, builder, saved_at=self._now())
        if stored is None:
            bar_builder_cold_starts_total.inc()
        elif wm is not None:
            entry.skip = skip = _Mark(wm.ts_us, wm.ids)
            if self._tape is not None:
                async for t in self._tape.since(symbol, wm.ts_us):
                    if not skip.covers(t.ts_event, t.trade_id):
                        await self._emit(entry, builder.on_trade(t))
                        skip.advance(t.ts_event, t.trade_id)
        bar_builder_cold_start_seconds.observe(time.perf_counter() - t0)
        return entry

    # -- hot path --------------------------------------------------------------------------
    async def _run(self, lane: _Lane) -> None:
        sub = lane.sub
        while True:
            trade = await sub.get()
            async with lane.lock:
                await self._apply(lane, trade)

    async def _apply(self, lane: _Lane, t: TradeEvent) -> None:
        t0 = time.perf_counter()
        ts, tid = t.ts_event, t.trade_id
        for e in lane.entries:
            skip = e.skip
            if skip is not None:
                if skip.covers(ts, tid):
                    continue
                if ts > skip.ts:
                    e.skip = None
            ups = e.builder.on_trade(t)
            if ups:
                await self._router.emit(e.spec, ups, e.generation)
        lane.mark.advance(ts, tid)
        bar_builder_fanout_latency_seconds.observe(time.perf_counter() - t0)

    async def _emit(self, e: _Entry, ups: Sequence[BarUpdate]) -> None:
        if ups:
            await self._router.emit(e.spec, ups, e.generation)

    # -- clock, persistence, teardown ------------------------------------------------------
    async def tick(self) -> None:
        """Clock closes, 60 s persistence and grace-period teardown (driven by `start()`)."""
        now = self._now()
        saves: list[StoredState] = []
        for lane in list(self._lanes.values()):
            async with lane.lock:
                for e in lane.entries:
                    await self._emit(e, e.builder.on_clock(now))
                    if now - e.saved_at >= self._persist_every:
                        e.saved_at = now
                        saves.append(self._stored(lane, e))
        for symbol, h in self._leases.expired(now):
            lane = self._lanes[symbol]
            async with lane.lock:
                if (symbol, h) in self._leases:
                    continue  # re-leased while we waited for the lock
                gone = [e for e in lane.entries if e.spec.spec_hash == h]
                lane.entries = tuple(e for e in lane.entries if e.spec.spec_hash != h)
                for e in gone:  # final blob, written before a re-register can read it
                    await self._save(self._stored(lane, e))
            bar_builder_specs_in_use.labels(symbol=symbol).set(len(lane.entries))
            await self._maybe_close_lane(symbol)
        for stored in saves:
            await self._save(stored)

    def _stored(self, lane: _Lane, e: _Entry) -> StoredState:
        mark = e.skip if e.skip is not None and e.skip.ts > lane.mark.ts else lane.mark
        wm = None if mark.ts == _Mark().ts else mark.frozen()
        return StoredState(e.builder.snapshot(), wm)

    async def _save(self, stored: StoredState) -> None:
        try:
            await self._store.save(stored)
        except OSError as exc:
            _log().warning(
                "bars_state_write_failed",
                spec_hash=stored.state.spec_hash,
                error_type=type(exc).__name__,
            )
            return
        bar_state_snapshots_written_total.inc()
