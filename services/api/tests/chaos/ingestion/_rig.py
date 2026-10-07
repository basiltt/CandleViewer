"""Production composition over the stub exchange (modelled on `app.wire_public_ws`).

`IngestionService` + `ConnectionManager` (B13 chart via the factory) +
`TradeStream` + `BookStream`, all on one `Bus`, with the stub exchange as the
socket factory and as the REST transport of a real `BybitRestClient`.

Deviations from the composition root (keep in sync with SCENARIOS.md):

* Virtual clock/RNG and the stub transport replace the real ones (the seams the
  production classes expose).
* s08's signed client wires `on_signature_failure=ClockGuard.resync_after_signature_failure`
  although production has no signed-client composition yet (#1949 / #1911): s08 proves
  client + guard, not the app.
* No `B14BookSupervisor` on the `BookStream`.
* No ticker stream.
* The instrument launch-time callback is `lambda _s: None` (no launch-time plausibility).
* The `ClockGuard` feeds the `EventWindow` but is not attached to `IngestionService`
  (`attach_clock`), so no stage-latency offset.
* `BookStream._timeout_loop` is replaced by `check_timeouts()` on the virtual clock.
* The rig never calls `IngestionService.start()` (it starts the pieces itself), so it
  registers `prune_unlisted` as the catalogue listener, wires the router and spawns the
  pump itself.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, TypeVar, cast

from candleviewer.book.models import BookPhase, BookStatus
from candleviewer.bus.bus import Bus, Subscription
from candleviewer.bus.models import QueuePolicy
from candleviewer.exchange.base.models import BookDelta, BookSnapshot

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.config import RestClientConfig

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.instruments import make_instruments_info_fetcher

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.public_ws import frame_route, topic_kind

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.rest import BybitRestClient

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.trades import parse_trade_frame, recent_trades_fetcher, trade_topic
from candleviewer.ingestion.clock import ClockGuard, rest_client_fetcher
from candleviewer.ingestion.connection import ConnectionManager
from candleviewer.ingestion.instruments_refresh import InstrumentsRefreshScheduler
from candleviewer.ingestion.planner import SubscriptionPlanner
from candleviewer.ingestion.reconnect import ConnectionRateGuard, ReconnectPolicy
from candleviewer.ingestion.rejection import EventWindow, corrected_now_us
from candleviewer.ingestion.service import IngestionService
from candleviewer.ingestion.trade_stream import GapEvent, TradeStream
from candleviewer.ingestion.watchdog import FeedHealthEvent, StalenessWatchdog
from candleviewer.observability.context import spawn
from candleviewer.orderbook_wiring import BookStream
from tests._corpus import TICKS
from tests.chaos.ingestion._clock import VirtualClock
from tests.chaos.ingestion._stub_exchange import StubExchange

#: The stub's REST base URL. Allow-listed host string only: `MockTransport`
#: answers in-process, nothing is ever dialled (network guard stays armed).
STUB_BASE_URL = "https://api.bybit.com"
T = TypeVar("T")
TICK_ALL: dict[str, Decimal] = {
    **TICKS,
    "ETHUSDT": Decimal("0.01"),
    "LUNAUSDT": Decimal("0.0001"),  # rest/instruments_before.json
}


def _tick(symbol: str) -> Decimal | None:
    return TICK_ALL.get(symbol)


@dataclass
class Observed:
    """The user-visible signals, in publish order (what SCR-152 / panels read)."""

    feed: list[FeedHealthEvent] = field(default_factory=list)
    book_status: list[BookStatus] = field(default_factory=list)
    book_events: list[BookSnapshot | BookDelta] = field(default_factory=list)
    gaps: list[GapEvent] = field(default_factory=list)
    trades: list[Any] = field(default_factory=list)
    order: list[str] = field(default_factory=list)  # "status:desynced", "delta:42", ...


class FlakyWriter:
    """Hot-tier writer double: `down=True` models a QuestDB/Postgres outage."""

    def __init__(self) -> None:
        self.down = False
        self.persisted_trades: list[Any] = []
        self.persisted_book_rows = 0
        self.failed_batches = 0

    def _check(self) -> None:
        if self.down:
            self.failed_batches += 1
            raise ConnectionError("hot tier unavailable")

    async def write_trades(self, events: Any) -> None:
        self._check()
        self.persisted_trades.extend(events)

    async def write_book_deltas(self, rows: Any) -> None:
        self._check()
        self.persisted_book_rows += len(rows)

    async def write_book_snapshot(self, row: Any) -> None:
        self._check()
        self.persisted_book_rows += 1


class _NullRepo:
    """Instrument repository double (Postgres is out of this suite's seam)."""

    async def upsert_snapshot(self, rows: Any) -> None:
        return None

    async def record_version(self, row: Any, *, changed_fields: Any) -> None:
        return None

    async def mark_stale(self, *, stale_since_us: int) -> None:
        return None

    async def load_all(self) -> list[Any]:
        return []


class Rig:
    """One env's public ingestion stack wired to the stub exchange."""

    def __init__(
        self,
        *,
        seed: int,
        symbols: tuple[str, ...] = ("BTCUSDT",),
        conn_limit: int = 480,
    ) -> None:
        self.seed = seed
        self.clock = VirtualClock()
        self.rng = random.Random(seed)  # noqa: S311  (deterministic jitter)
        self.ex = StubExchange(self.clock, seed=seed)
        self.bus = Bus()
        self.env = "live"
        self.symbols = symbols
        self.writer = FlakyWriter()
        self.seen = Observed()
        self.governor = TokenBucketGovernor(
            default_capacity=50.0,
            default_refill_per_s=5.0,
            clock=self.clock,
            sleep=self.clock.sleep,  # 10018 IP hold (#1908) runs on virtual time
        )
        self.rest = BybitRestClient(
            RestClientConfig(base_url=STUB_BASE_URL),
            governor=self.governor,
            transport=self.ex.transport,
            sleep=self.clock.sleep,
            random_fn=self.rng.random,
            wall_clock=self.host_wall_s,
        )
        self.host_skew_s = 0.0  # market-data host clock skew (WSL sleep)
        self.svc = IngestionService()
        self.instruments = InstrumentsRefreshScheduler(
            fetch_instruments_info=make_instruments_info_fetcher(self.rest),
            repository=_NullRepo(),
            now_us=self.clock.now_us,
            sleep=self.clock.sleep,
            random_fn=self.rng.random,
        )
        self.guard = ConnectionRateGuard(self.clock, limit=conn_limit)
        self.watchdog = StalenessWatchdog(self.clock, lambda _e: None, kind_of=topic_kind)
        self.ws = ConnectionManager(
            self.ex.socket_factory,
            SubscriptionPlanner(),
            self.watchdog,
            ReconnectPolicy(rng=random.Random(seed + 1)),  # noqa: S311
            self.guard,
            self.svc.offer_frame,
            sleep=self.clock.sleep,
            bus=self.bus,
            env=self.env,
        )
        self._demand: dict[str, set[str]] = {}
        # Composition-root parity (`app.wire_public_ws`, #1912): the plausibility
        # window runs on host clock + ClockGuard offset; the guard sees the same
        # (skewable) host wall clock and the virtual monotonic clock.
        self.clock_guard = ClockGuard(
            rest_client_fetcher(self.rest, wall_clock=self.host_wall_s, monotonic=self.clock),
            clock=self.clock,
            sleep=self.clock.sleep,
            wall_ns=lambda: self.host_now_us() * 1_000,
            mono_ns=lambda: int(self.clock.now * 1_000_000_000),
        )
        window = EventWindow(
            corrected_now_us(self.clock_guard.offset_us, self.host_now_us), lambda _s: None
        )
        self.trades = TradeStream(
            bus=self.bus,
            env=self.env,
            set_desired=lambda t: self._set_desired("trade", t),
            parse_frame=parse_trade_frame,
            topic_for=trade_topic,
            is_listed=self.is_listed,
            touch=self.watchdog.touch,
            fetch_recent=recent_trades_fetcher(self.rest.get_public),
            tick_size=_tick,
            clock=self.clock,
            now_us=self.clock.now_us,
            event_window=window,
            writer=self.writer,
            write_sleep=self.clock.sleep,  # #1918 write-behind backoff on virtual time
            write_rand=self.rng.random,
        )
        self.books = BookStream(
            bus=self.bus,
            env=self.env,
            set_desired=lambda t: self._set_desired("book", t),
            parse_frame=lambda f: parse_book_frame(f, _tick),
            topic_for=book_topic,
            resubscribe=self.ws.resubscribe_topic,
            is_listed=self.is_listed,
            touch=self.watchdog.touch,
            clock=self.clock,
            now_us=self.clock.now_us,
            writer=self.writer,
            rand=self.rng.random,
        )
        self.svc.attach_ws(self.ws)
        self.svc.attach_router(frame_route, self.watchdog.touch)  # #1916 per-topic lanes
        self.instruments.add_listener(self.svc.prune_unlisted)  # #1913 delist teardown
        self.svc.attach_trades(self.trades)
        self.svc.attach_books(self.books)
        self._ui: Subscription = self.bus.subscribe(
            "chaos-ui", f"{self.env}.*.*.*", QueuePolicy.NEVER_DROP, maxsize=1_000_000
        )

    # ---- composition-root callbacks ---------------------------------------
    def is_listed(self, symbol: str) -> bool:
        """Exactly `app.wire_public_ws._is_listed`: catalogue says `trading`."""
        snap = self.instruments.snapshot()
        inst = snap.get(symbol) if snap is not None else None
        return inst is not None and inst.status == "trading"

    def host_now_us(self) -> int:
        """The host wall clock: venue time plus every injected host jump."""
        skew_s = self.host_skew_s + self.ex.host_skew_s
        return self.clock.now_us() + int(skew_s * 1_000_000)

    def host_wall_s(self) -> float:
        return self.host_now_us() / 1_000_000

    def _set_desired(self, stream: str, topics: set[str]) -> None:
        self._demand[stream] = set(topics)
        self.ws.set_desired(set().union(*self._demand.values()))

    # ---- lifecycle -----------------------------------------------------------
    async def start(self) -> None:
        """`IngestionService.start` minus the settings-bound synthetic feed.

        `BookStream._timeout_loop` sleeps on the real loop clock (not injectable),
        so the rig runs the same `check_timeouts()` on the virtual clock instead."""

        await self.instruments.refresh_now()  # the catalogue gates every topic (E08-S03)
        await self.ws.start()
        await self.trades.start()
        b = cast(Any, self.books)
        self._tasks: list[asyncio.Task[None]] = [
            spawn(b._health_loop(), name="chaos-book-health"),
            spawn(b._write_loop(), name="chaos-book-write"),
            spawn(self._book_ticks(), name="chaos-book-ticks"),
            spawn(cast(Any, self.svc)._pump_frames(), name="chaos-pump"),
        ]
        self.svc.ws = self.ws
        cast(Any, self.svc)._started = True  # what `IngestionService.start` sets last
        for sym in self.symbols:
            self.trades.acquire("chaos", sym)
            self.books.acquire("chaos", sym)
        await self.clock.settle()

    async def _book_ticks(self) -> None:
        while True:
            await self.clock.sleep(0.25)
            await self.books.check_timeouts()

    async def stop(self) -> None:

        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.trades.stop()
        await self.ws.stop()
        await self.rest.aclose()

    # ---- observation -----------------------------------------------------------
    def observe(self) -> Observed:
        """Drain what a UI subscriber would have received since the last call."""
        while not self._ui.queue.empty():
            ev = self._ui.get_nowait()
            if isinstance(ev, BookStatus):
                self.seen.book_status.append(ev)
                self.seen.order.append(f"status:{ev.state}")
            elif isinstance(ev, BookDelta):
                self.seen.book_events.append(ev)
                self.seen.order.append(f"delta:{ev.update_id}")
            elif isinstance(ev, BookSnapshot):
                self.seen.book_events.append(ev)
                self.seen.order.append(f"snapshot:{ev.update_id}")
            elif isinstance(ev, GapEvent):
                self.seen.gaps.append(ev)
            elif isinstance(ev, FeedHealthEvent):
                self.seen.feed.append(ev)
                self.seen.order.append(f"feed:{ev.state}")
            else:
                self.seen.trades.append(ev)
        return self.seen

    def book_phase(self, symbol: str = "BTCUSDT") -> BookPhase | None:
        return self.books.phase(symbol)

    def book_levels(self, symbol: str = "BTCUSDT") -> tuple[dict[Decimal, Decimal], ...]:
        view = self.books.view(symbol, 200)
        if view is None:
            return ({}, {})
        snap = view.snapshot
        return ({lv.price: lv.qty for lv in snap.bids}, {lv.price: lv.qty for lv in snap.asks})

    def health_report(self) -> str:
        """What `/readyz` reads: the ingestion module's own `health()`."""
        return str(self.svc.health().status)

    async def call(self, aw: Awaitable[T], *, within_s: float = 120.0) -> T:
        """Run a REST call to completion on virtual time (its retries sleep on it)."""
        task = asyncio.ensure_future(aw)
        await self.clock.run_until(task.done, within_s=within_s, what="rest call")
        return task.result()


def metric(m: Any, **labels: str) -> float:
    """Current value of a prometheus child (counters/gauges on the default registry)."""
    child = m.labels(**labels) if labels else m
    return float(child._value.get())
