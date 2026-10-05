"""Ingestion soak + burst harness (E08-T06, R0 exit evidence).

Drives the real M5 `Bus` (NEVER_DROP trade subscriber) and the real M7
`BookState` with a deterministic synthetic feed on >=3 symbols, and samples
RSS / CPU / event-loop lag / queue depths / per-stream latency percentiles.
Writes a machine-readable JSON report. **Never touches the network**: the
feed is synthetic (seeded RNG, prices anchored on
`packages/fixtures/raw/synthetic_sample.jsonl`).

Two modes:

* ``soak`` - steady 1x feed for ``--duration-s`` (virtual seconds; ``--realtime``
  paces ticks on the wall clock for the 24 h demo leg). Fails explicitly
  (exit 1, ``SoakRegressionError``) with the RSS growth curve attached when
  memory grows beyond +/-5 % end to end - never a pass with a caveat.
* ``burst`` - 5x feed for ``--burst-s`` against a capacity-modelled consumer;
  asserts zero trade loss, that ``ingest_queue_full_total{class="trade"}``
  counted the applied backpressure, and that steady state returns within
  the documented recovery window (``docs/ops/ingestion.md``).

Sampling is out-of-process capable: ``PsutilSampler(pid)`` reads another
process's RSS/CPU, so the 24 h run can watch the API without perturbing it.
Unit tests inject a fake sampler (`tests/unit/ingestion/test_ingestion_soak_bench.py`).

Run: ``uv run python bench/ingestion_soak.py soak --duration-s 1800 --out soak.json``
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import sys
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Protocol

import psutil

from candleviewer.book.state import BookState
from candleviewer.bus.bus import Bus
from candleviewer.bus.metrics import ingest_queue_full_total
from candleviewer.bus.models import QueuePolicy, Topic
from candleviewer.exchange.base.models import BookLevel
from candleviewer.ingestion.metrics import ingest_events_total, symbol_label
from candleviewer.observability.context import spawn

SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
_ANCHOR = {"BTCUSDT": 65000, "ETHUSDT": 3200, "SOLUSDT": 150}  # ticks of 0.1
MEMORY_TOLERANCE = 0.05
WARMUP_FRACTION = 0.10
#: R0 exit budgets (30-release-roadmap 5; 06-performance 4.3).
BUDGET_INGEST_BUS_P95_MS = 20.0
BUDGET_BOOK_APPLY_P95_MS = 2.0
#: Documented recovery window after a 5x/60 s burst at 4x consumer headroom.
RECOVERY_WINDOW_S = 30.0


class SoakRegressionError(AssertionError):
    """Memory grew beyond tolerance; carries the growth curve."""

    def __init__(self, growth: float, curve: Sequence[tuple[float, int]]) -> None:
        self.growth = growth
        self.curve = list(curve)
        pts = ", ".join(f"{t:.0f}s={r / 2**20:.1f}MiB" for t, r in self.curve)
        super().__init__(f"RSS grew {growth:+.2%} (limit +/-{MEMORY_TOLERANCE:.0%}); curve: {pts}")


class BurstError(AssertionError):
    """The never-drop / backpressure / recovery contract was violated."""


@dataclass(frozen=True, slots=True)
class ProcSample:
    rss_bytes: int
    cpu_percent: float


class Sampler(Protocol):
    def sample(self) -> ProcSample: ...


class PsutilSampler:
    """RSS/CPU of `pid` (default: this process) via psutil, out-of-process capable."""

    def __init__(self, pid: int | None = None) -> None:
        self._proc = psutil.Process(pid or os.getpid())
        self._proc.cpu_percent(None)  # prime the interval counter

    def sample(self) -> ProcSample:
        return ProcSample(self._proc.memory_info().rss, self._proc.cpu_percent(None))


@dataclass(slots=True)
class Point:
    t_s: float
    rss_bytes: int
    cpu_percent: float
    loop_lag_ms: float
    queue_depth: int
    backlog: int


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile; 0.0 for an empty series."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(pct * len(ordered)) - 1))
    return ordered[idx]


class Reservoir:
    """Fixed-size uniform sample (Algorithm R) so a 24 h run's latency
    bookkeeping cannot itself grow memory."""

    def __init__(self, size: int = 20_000, seed: int = 11) -> None:
        self.size = size
        self.seen = 0
        self.values: list[float] = []
        self._rng = random.Random(seed)  # noqa: S311 - sampling, not crypto

    def add(self, v: float) -> None:
        self.seen += 1
        if len(self.values) < self.size:
            self.values.append(v)
            return
        j = self._rng.randrange(self.seen)
        if j < self.size:
            self.values[j] = v

    def summary(self) -> dict[str, float]:
        return {
            "p50": percentile(self.values, 0.50),
            "p95": percentile(self.values, 0.95),
            "p99": percentile(self.values, 0.99),
            "count": float(self.seen),
        }


class SyntheticMarket:
    """Deterministic trade + L2 delta generator (seeded; no network, no clock)."""

    def __init__(self, symbols: Sequence[str], seed: int = 7, depth: int = 200) -> None:
        self._rng = random.Random(seed)  # noqa: S311 - reproducible synthetic data, not crypto
        self.depth = depth
        self.books = {s: self._seed_book(s) for s in symbols}
        self.next_id = 0

    @staticmethod
    def _lvl(ticks: int, qty: int) -> BookLevel:
        return BookLevel(price=Decimal(ticks) / 10, qty=Decimal(qty), price_ticks=ticks)

    def _seed_book(self, sym: str) -> BookState:
        mid = _ANCHOR.get(sym, 1000) * 10
        half = self.depth // 2
        bids = [self._lvl(mid - i, 1 + i % 7) for i in range(1, half)]
        asks = [self._lvl(mid + i, 1 + i % 5) for i in range(1, half)]
        return BookState.from_levels(self.depth, bids, asks)

    def trade(self, sym: str) -> dict[str, object]:
        self.next_id += 1
        return {"id": self.next_id, "symbol": sym, "side": self._rng.choice("bs")}

    def delta(self, sym: str) -> tuple[list[BookLevel], list[BookLevel]]:
        mid = _ANCHOR.get(sym, 1000) * 10
        half = self.depth // 2
        bids = [self._lvl(mid - self._rng.randint(1, half - 1), self._rng.randint(0, 9))]
        asks = [self._lvl(mid + self._rng.randint(1, half - 1), self._rng.randint(0, 9))]
        return bids, asks


@dataclass(slots=True)
class RunConfig:
    mode: str = "soak"
    symbols: tuple[str, ...] = SYMBOLS
    duration_s: float = 60.0
    tick_s: float = 0.1
    trades_per_s: int = 50
    book_deltas_per_s: int = 10
    sample_every_s: float = 5.0
    realtime: bool = False
    burst_s: float = 60.0
    burst_factor: int = 5
    capacity_factor: int = 4
    queue_size: int = 256
    seed: int = 7


@dataclass(slots=True)
class Report:
    mode: str
    config: dict[str, object]
    passed: bool
    failures: list[str] = field(default_factory=list)
    trades_published: int = 0
    trades_delivered: int = 0
    trades_lost: int = 0
    out_of_order: int = 0
    queue_full_events: float = 0.0
    memory_growth: float = 0.0
    recovery_s: float | None = None
    latency_ms: dict[str, dict[str, float]] = field(default_factory=dict)
    curve: list[dict[str, float]] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)


def _queue_full_trade() -> float:
    return float(ingest_queue_full_total.labels(**{"class": "trade"})._value.get())


def memory_growth(curve: Sequence[Point]) -> float:
    """End-to-end RSS growth after warm-up: median(last 3) / median(first 3) - 1."""
    if len(curve) < 2:
        return 0.0
    start = max(1, int(len(curve) * WARMUP_FRACTION)) if len(curve) > 6 else 0
    steady = list(curve[start:])
    head = sorted(p.rss_bytes for p in steady[:3])
    tail = sorted(p.rss_bytes for p in steady[-3:])
    base = head[len(head) // 2]
    return (tail[len(tail) // 2] - base) / base if base else 0.0


def check_memory(curve: Sequence[Point]) -> float:
    """Return growth, raising `SoakRegressionError` (with the curve) past +/-5 %."""
    growth = memory_growth(curve)
    if abs(growth) > MEMORY_TOLERANCE:
        raise SoakRegressionError(growth, [(p.t_s, p.rss_bytes) for p in curve])
    return growth


class _Consumer:
    """Capacity-modelled NEVER_DROP trade consumer: `budget` items per tick.

    Checks loss and per-symbol ordering without retaining ids (constant memory).
    """

    def __init__(self, bus: Bus, env: str, size: int) -> None:
        self.sub = bus.subscribe(
            "soak-trades", f"{env}.md.*.trade", QueuePolicy.NEVER_DROP, maxsize=size
        )
        self.budget = 0
        self.delivered = 0
        self.out_of_order = 0
        self._last: dict[str, int] = {}
        self.granted = asyncio.Event()

    async def run(self) -> None:
        while True:
            if self.budget > 0 and self.sub.qsize() > 0:
                ev = self.sub.get_nowait()
                self.budget -= 1
                self.delivered += 1
                sym, ident = str(ev["symbol"]), int(ev["id"])
                if ident <= self._last.get(sym, 0):
                    self.out_of_order += 1
                self._last[sym] = ident
                await asyncio.sleep(0)  # let a back-pressured publisher resume
            elif self.budget > 0:
                await asyncio.sleep(0)
            else:
                self.granted.clear()
                await self.granted.wait()


class _Producer:
    """Exchange-side buffer -> `Bus.publish` (awaits when the queue is full)."""

    def __init__(self, bus: Bus, env: str, symbols: Sequence[str]) -> None:
        self.bus = bus
        self.pending: deque[dict[str, object]] = deque()
        self.topics = {s: Topic(env=env, domain="md", symbol=s, detail="trade") for s in symbols}
        self.children = {
            s: ingest_events_total.labels(stream="trade", symbol=symbol_label(s)) for s in symbols
        }
        self.published = 0
        self.publish_ms = Reservoir()
        self.blocked = False
        self.wake = asyncio.Event()

    async def run(self) -> None:
        while True:
            await self.wake.wait()
            while self.pending:
                ev = self.pending.popleft()
                sym = str(ev["symbol"])
                t0 = time.perf_counter_ns()
                self.blocked = True
                await self.bus.publish(self.topics[sym], ev)
                self.blocked = False
                self.publish_ms.add((time.perf_counter_ns() - t0) / 1e6)
                self.children[sym].inc()
                self.published += 1
            self.wake.clear()


async def _settle(cons: _Consumer, prod: _Producer, limit: int = 100_000) -> None:
    """Yield (never sleep) until the tick is quiescent: consumer out of budget
    or queue empty, and producer drained or blocked on a full queue. Unused
    consumer budget is per tick, so it is zeroed on return."""
    for _ in range(limit):
        await asyncio.sleep(0)
        consumer_done = cons.budget == 0 or cons.sub.qsize() == 0
        producer_done = not prod.pending or (prod.blocked and cons.sub.queue.full())
        if consumer_done and producer_done and (prod.blocked or not prod.wake.is_set()):
            cons.budget = 0
            cons.granted.set()  # let the consumer park on its event
            await asyncio.sleep(0)
            return
    raise BurstError("harness failed to settle a tick (scheduler livelock)")


async def run(
    cfg: RunConfig,
    sampler: Sampler,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Report:
    """One soak or burst run. Virtual time by default (tick count, no sleeps);
    `cfg.realtime` paces each tick on the wall clock via `sleep`."""
    env = "demo"
    bus = Bus()
    market = SyntheticMarket(cfg.symbols, cfg.seed)
    cons = _Consumer(bus, env, cfg.queue_size)
    prod = _Producer(bus, env, cfg.symbols)
    tasks = [spawn(cons.run(), name="soak-consumer"), spawn(prod.run(), name="soak-producer")]
    book_ms = Reservoir(seed=cfg.seed + 1)
    loop_lag = Reservoir(size=2_000, seed=cfg.seed + 2)
    qf0 = _queue_full_trade()
    curve: list[Point] = []
    steady_trades = cfg.trades_per_s * cfg.tick_s * len(cfg.symbols)
    capacity = max(1, int(steady_trades * cfg.capacity_factor))
    burst_end = cfg.burst_s if cfg.mode == "burst" else 0.0
    total_s = cfg.duration_s if cfg.mode == "soak" else cfg.burst_s + RECOVERY_WINDOW_S * 2
    n_ticks = int(total_s / cfg.tick_s)
    every = max(1, int(cfg.sample_every_s / cfg.tick_s))
    recovered_at: float | None = None
    carry = 0.0
    try:
        for i in range(n_ticks):
            t = i * cfg.tick_s
            mult = cfg.burst_factor if t < burst_end else 1
            carry += cfg.trades_per_s * cfg.tick_s * mult
            for _ in range(int(carry)):
                for sym in cfg.symbols:
                    prod.pending.append(market.trade(sym))
            carry -= int(carry)
            for sym in cfg.symbols:
                for _ in range(max(1, int(cfg.book_deltas_per_s * cfg.tick_s * mult))):
                    bids, asks = market.delta(sym)
                    t0 = time.perf_counter_ns()
                    market.books[sym].apply(bids, asks)
                    book_ms.add((time.perf_counter_ns() - t0) / 1e6)
            cons.budget = capacity
            cons.granted.set()
            prod.wake.set()
            t_lag = time.perf_counter()
            await _settle(cons, prod)
            loop_lag.add((time.perf_counter() - t_lag) * 1000)
            backlog = len(prod.pending) + cons.sub.qsize()
            if t >= burst_end and recovered_at is None and backlog == 0 and cfg.mode == "burst":
                recovered_at = t - burst_end
            if i % every == 0 or i == n_ticks - 1:
                s = sampler.sample()
                curve.append(
                    Point(
                        t,
                        s.rss_bytes,
                        s.cpu_percent,
                        loop_lag.summary()["p99"],
                        cons.sub.qsize(),
                        backlog,
                    )
                )
            if cfg.realtime:
                await sleep(cfg.tick_s)
        # Final drain: nothing may remain undelivered.
        for _ in range(10_000):
            if not prod.pending and cons.sub.qsize() == 0:
                break
            cons.budget = capacity
            cons.granted.set()
            prod.wake.set()
            await _settle(cons, prod)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return _report(cfg, prod, cons, book_ms, curve, _queue_full_trade() - qf0, recovered_at)


def _report(
    cfg: RunConfig,
    prod: _Producer,
    cons: _Consumer,
    book_ms: Reservoir,
    curve: list[Point],
    queue_full: float,
    recovered_at: float | None,
) -> Report:
    rep = Report(mode=cfg.mode, config=asdict(cfg), passed=True)
    rep.trades_published = prod.published
    rep.trades_delivered = cons.delivered
    rep.trades_lost = prod.published - cons.delivered + len(prod.pending)
    rep.out_of_order = cons.out_of_order
    rep.queue_full_events = queue_full
    rep.recovery_s = recovered_at
    rep.latency_ms = {"ingest_to_bus": prod.publish_ms.summary(), "book_apply": book_ms.summary()}
    rep.curve = [asdict(p) for p in curve]
    rep.environment = {"python": sys.version.split()[0], "platform": sys.platform}
    if rep.trades_lost or rep.out_of_order:
        rep.failures.append(f"trade loss={rep.trades_lost} out_of_order={rep.out_of_order}")
    p95_bus = rep.latency_ms["ingest_to_bus"]["p95"]
    p95_book = rep.latency_ms["book_apply"]["p95"]
    if cfg.mode == "soak":
        if p95_bus > BUDGET_INGEST_BUS_P95_MS:
            rep.failures.append(f"ingest->bus p95 {p95_bus:.3f} ms > {BUDGET_INGEST_BUS_P95_MS}")
        if p95_book > BUDGET_BOOK_APPLY_P95_MS:
            rep.failures.append(f"book apply p95 {p95_book:.3f} ms > {BUDGET_BOOK_APPLY_P95_MS}")
        try:
            rep.memory_growth = check_memory(curve)
        except SoakRegressionError as exc:
            rep.memory_growth = exc.growth
            rep.failures.append(str(exc))
    else:
        if queue_full <= 0:
            rep.failures.append("burst never back-pressured: ingest_queue_full_total did not move")
        if recovered_at is None or recovered_at > RECOVERY_WINDOW_S:
            rep.failures.append(f"no steady state within {RECOVERY_WINDOW_S:.0f}s of burst end")
    rep.passed = not rep.failures
    return rep


def enforce(rep: Report) -> None:
    """Raise the explicit failure type; a failing run never reports a pass."""
    for f in rep.failures:
        if f.startswith("RSS grew"):
            raise SoakRegressionError(
                rep.memory_growth, [(c["t_s"], int(c["rss_bytes"])) for c in rep.curve]
            )
    if rep.failures:
        raise BurstError("; ".join(rep.failures))


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("mode", choices=("soak", "burst"))
    ap.add_argument("--duration-s", type=float, default=60.0, help="soak length (virtual s)")
    ap.add_argument("--burst-s", type=float, default=60.0)
    ap.add_argument("--burst-factor", type=int, default=5)
    ap.add_argument("--trades-per-s", type=int, default=50, help="per symbol, steady state")
    ap.add_argument("--symbols", default=",".join(SYMBOLS))
    ap.add_argument("--realtime", action="store_true", help="pace on the wall clock (24 h leg)")
    ap.add_argument("--pid", type=int, default=None, help="sample another process (out-of-process)")
    ap.add_argument("--out", type=Path, default=Path("ingestion-soak.json"))
    a = ap.parse_args(argv)
    cfg = RunConfig(
        mode=a.mode,
        symbols=tuple(s for s in a.symbols.split(",") if s),
        duration_s=a.duration_s,
        burst_s=a.burst_s,
        burst_factor=a.burst_factor,
        trades_per_s=a.trades_per_s,
        realtime=a.realtime,
    )
    rep = asyncio.run(run(cfg, PsutilSampler(a.pid)))
    a.out.write_text(json.dumps(asdict(rep), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lat = rep.latency_ms
    print(
        f"{rep.mode}: passed={rep.passed} published={rep.trades_published} "
        f"lost={rep.trades_lost} queue_full={rep.queue_full_events:.0f} "
        f"recovery_s={rep.recovery_s} growth={rep.memory_growth:+.2%} "
        f"bus_p95={lat['ingest_to_bus']['p95']:.4f}ms book_p95={lat['book_apply']['p95']:.4f}ms"
    )
    for f in rep.failures:
        print(f"FAIL: {f}", file=sys.stderr)
    return 0 if rep.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
