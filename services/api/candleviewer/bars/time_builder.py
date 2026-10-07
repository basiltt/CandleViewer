"""Time-bar builder (`24-internal-schemas.md` §3.2-§3.4, ticket E12-S01).

Hot path (C-2.20): plain synchronous code, no statechart. Each trade mutates a slotted
`_Draft`; a frozen `Bar` is materialised with `Bar.model_construct` only on emit.

Grid (§3.3): `start = floor((ts - anchor) / step) * step + anchor`, where `anchor` is
`session_anchor_utc_min` minutes past 00:00 UTC.
- `align_to_epoch=True`: one grid from the epoch, offset by the anchor.
- `align_to_epoch=False`: the grid restarts at every session start (anchor + k * 1 day), so an
  interval that does not divide a day gets a shorter last bar ending on the session boundary.
For time bars `open_time`/`close_time` are the bucket boundaries, which `BarSeries.densify()`
relies on.

Edge cases:
- Empty intervals emit nothing; the next real bar has `gap_before=True`.
- `on_clock(now)` closes the open bar once `now >= close_time` (dead market, §3.3b).
- A late trade whose bucket matches a closed bar is applied to it and re-emits `close` with
  `amended=True`, as long as the bar closed no more than 60 s ago, measured against the
  watermark (the highest clock or trade time seen so far). Older trades, and trades whose
  bucket has no bar (an emitted empty interval), are dropped and counted. Creating a bar
  there would break strictly increasing `index`.
- Trades inside the open bar are applied in arrival order, which is deterministic for a
  given input sequence (BI-4). Duplicate suppression is upstream (`TradeStream` trade-id
  dedupe), not here.
- The first bar of a fresh builder has `partial=True`: trades earlier in that interval were
  not observed.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Final

import orjson
import structlog

from candleviewer.bars.errors import BarsError, BarSpecError
from candleviewer.bars.models import Bar, BarSpec, BarUpdate, BuilderState
from candleviewer.domain.primitives import TsUs
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.observability.metrics import Counter

MIN_INTERVAL_MS: Final = 1_000
MAX_INTERVAL_MS: Final = 86_400_000
LATE_WINDOW_US: Final = 60_000_000
STATE_VERSION: Final = 1
_DAY_US: Final = 86_400_000_000
_VWAP_Q: Final = Decimal("1e-8")
_ZERO: Final = Decimal(0)
_NONE: Final[tuple[BarUpdate, ...]] = ()

bars_built_total = Counter(
    "bars_built_total", "Bars closed by a builder.", labelnames=("symbol", "kind")
)
bars_amended_total = Counter(
    "bars_amended_total", "Closed bars re-emitted after a late trade.", labelnames=("symbol",)
)
bars_late_trade_dropped_total = Counter(
    "bars_late_trade_dropped_total",
    "Late trades not applied to any bar (older than 60 s, or the interval had no bar).",
    labelnames=("symbol",),
)
_log = structlog.get_logger(__name__)


def validate_time_spec(spec: BarSpec) -> int:
    """Return `interval_ms`, or raise `BarSpecError` if it is outside [1 s, 1 D] or not whole
    seconds. A tiny interval would emit a bar for almost every trade, so it is rejected."""
    if spec.kind != "time" or spec.interval_ms is None:
        raise BarSpecError("A time-bar builder needs a bar spec of kind 'time'.")
    ms = spec.interval_ms
    if not MIN_INTERVAL_MS <= ms <= MAX_INTERVAL_MS or ms % 1000:
        raise BarSpecError(
            f"The interval_ms {ms} is not allowed; use whole seconds from "
            f"{MIN_INTERVAL_MS} to {MAX_INTERVAL_MS}."
        )
    return ms


def bucket_bounds(spec: BarSpec, ts_us: int) -> tuple[int, int]:
    """`(open_time, close_time)` in µs of the bucket containing `ts_us` (§3.3)."""
    step = validate_time_spec(spec) * 1000
    anchor = spec.session_anchor_utc_min * 60_000_000
    if spec.align_to_epoch:
        start = (ts_us - anchor) // step * step + anchor
        return start, start + step
    session = (ts_us - anchor) // _DAY_US * _DAY_US + anchor
    start = (ts_us - session) // step * step + session
    return start, min(start + step, session + _DAY_US)


class _Draft:
    """Mutable accumulator for one bar; plain attributes, so a trade allocates nothing here."""

    __slots__ = (
        "buy",
        "close",
        "close_time",
        "count",
        "delta",
        "gap_before",
        "high",
        "index",
        "low",
        "max_d",
        "min_d",
        "open",
        "open_time",
        "partial",
        "sell",
        "turnover",
    )

    def __init__(self, index: int, open_time: int, close_time: int, px: Decimal) -> None:
        self.index = index
        self.open_time = open_time
        self.close_time = close_time
        self.open = self.high = self.low = self.close = px
        self.buy = self.sell = self.delta = self.turnover = _ZERO
        self.min_d = self.max_d = _ZERO
        self.count = 0
        self.partial = self.gap_before = False

    def apply(self, t: TradeEvent) -> None:
        px, qty = t.price, t.qty
        if px > self.high:
            self.high = px
        elif px < self.low:
            self.low = px
        self.close = px
        if t.side == "buy":
            self.buy += qty
            self.delta += qty
        else:
            self.sell += qty
            self.delta -= qty
        d = self.delta
        if self.count == 0:
            self.min_d = self.max_d = d
        elif d < self.min_d:
            self.min_d = d
        elif d > self.max_d:
            self.max_d = d
        self.count += 1
        self.turnover += px * qty

    def to_bar(self, spec_hash: str, symbol: str, closed: bool) -> Bar:
        vol = self.buy + self.sell
        vwap = (self.turnover / vol).quantize(_VWAP_Q, ROUND_HALF_EVEN) if vol else self.open
        return Bar.model_construct(
            spec_hash=spec_hash,
            symbol=symbol,
            index=self.index,
            open_time=self.open_time,
            close_time=self.close_time,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=vol,
            buy_volume=self.buy,
            sell_volume=self.sell,
            delta=self.delta,
            min_delta=self.min_d,
            max_delta=self.max_d,
            trade_count=self.count,
            turnover=self.turnover,
            vwap=vwap,
            closed=closed,
            partial=self.partial,
            gap_before=self.gap_before,
            synthetic=False,
        )

    def dump(self) -> list[Any]:
        return [getattr(self, n) if n in _INT_SLOTS else str(getattr(self, n)) for n in _SLOTS]

    @classmethod
    def load(cls, row: list[Any]) -> _Draft:
        d = cls.__new__(cls)
        for n, v in zip(_SLOTS, row, strict=True):
            setattr(d, n, v if n in _INT_SLOTS else Decimal(v))
        return d


_SLOTS: Final = _Draft.__slots__
#: Slots stored as JSON ints/bools; every other slot is a Decimal rendered as a string.
_INT_SLOTS: Final = frozenset(
    {"index", "open_time", "close_time", "count", "partial", "gap_before"}
)


class TimeBarUpdate(BarUpdate):
    """`BarUpdate` plus the §3.3c `amended` flag, set on a `close` re-emitted by a late trade.

    Stop-gap until the E12-T01 `BarUpdate` contract carries `amended` (#1985); folds into
    `BarUpdate` when #1985 lands. It is still a `BarUpdate`, so `BarBuilder` consumers are
    unaffected.
    """

    amended: bool = False


class TimeBarBuilder:
    """`BarBuilder` for `kind="time"`, one per `(symbol, spec)`. See the module docstring."""

    def __init__(self, spec: BarSpec, symbol: str) -> None:
        validate_time_spec(spec)
        self.spec = spec
        self.symbol = symbol
        self._hash = spec.spec_hash
        self._cur: _Draft | None = None
        self._closed: deque[_Draft] = deque()  # closed within LATE_WINDOW_US of the watermark
        self._next_index = 0
        self._last_close: int | None = None  # close_time of the newest closed bar
        self._watermark = -(2**63)
        self._last_seq: int | None = None
        self._built = bars_built_total.labels(symbol=symbol, kind="time")
        self._amended = bars_amended_total.labels(symbol=symbol)
        self._dropped = bars_late_trade_dropped_total.labels(symbol=symbol)

    def _emit(self, kind: str, d: _Draft, closed: bool, amended: bool = False) -> TimeBarUpdate:
        bar = d.to_bar(self._hash, self.symbol, closed)
        return TimeBarUpdate.model_construct(kind=kind, bar=bar, amended=amended)

    def _close(self, d: _Draft) -> TimeBarUpdate:
        self._cur = None
        self._closed.append(d)
        self._last_close = d.close_time
        self._built.inc()
        if d.index == 0:
            _log.info("bars_first_bar", symbol=self.symbol, spec_hash=self._hash, kind="time")
        return self._emit("close", d, closed=True)

    def _prune(self) -> None:
        closed = self._closed
        while closed and self._watermark - closed[0].close_time > LATE_WINDOW_US:
            closed.popleft()

    def on_trade(self, t: TradeEvent) -> Sequence[BarUpdate]:
        if t.symbol != self.symbol:
            raise BarsError(f"Trade for {t.symbol} sent to the {self.symbol} time-bar builder.")
        ts = t.ts_event
        self._last_seq = t.seq
        if ts > self._watermark:
            self._watermark = ts
        cur = self._cur
        if cur is not None and cur.open_time <= ts < cur.close_time:
            cur.apply(t)
            return (self._emit("update", cur, closed=False),)
        floor = cur.open_time if cur is not None else self._last_close
        if floor is not None and ts < floor:
            return self._late(t)
        out: list[BarUpdate] = [] if cur is None else [self._close(cur)]
        self._prune()
        start, end = bucket_bounds(self.spec, ts)
        d = _Draft(self._next_index, start, end, t.price)
        d.partial = self._next_index == 0
        d.gap_before = self._last_close is not None and self._last_close != start
        self._next_index += 1
        d.apply(t)
        self._cur = d
        out.append(self._emit("open", d, closed=False))
        return out

    def _late(self, t: TradeEvent) -> Sequence[BarUpdate]:
        ts = t.ts_event
        for d in self._closed:
            if d.open_time <= ts < d.close_time:
                if self._watermark - d.close_time <= LATE_WINDOW_US:
                    d.apply(t)
                    self._amended.inc()
                    return (self._emit("close", d, closed=True, amended=True),)
                break
        self._dropped.inc()
        _log.warning(
            "bars_late_trade_dropped",
            symbol=self.symbol,
            spec_hash=self._hash,
            lateness_ms=(self._watermark - ts) // 1000,
        )
        return _NONE

    def on_clock(self, now_us: TsUs) -> Sequence[BarUpdate]:
        if now_us > self._watermark:
            self._watermark = now_us
        cur = self._cur
        if cur is None or now_us < cur.close_time:
            return _NONE
        out = (self._close(cur),)
        self._prune()
        return out

    def snapshot(self) -> BuilderState:
        """Versioned JSON draft (Decimals as strings) inside the `BuilderState` envelope.

        §3.2's "msgpack blob" wording is superseded by versioned orjson (`state_version`);
        msgpack is not a dependency. Docs update tracked in #1987.
        """
        doc = {
            "cur": None if self._cur is None else self._cur.dump(),
            "closed": [d.dump() for d in self._closed],
            "next_index": self._next_index,
            "last_close": self._last_close,
            "watermark": self._watermark,
        }
        return BuilderState(
            spec_hash=self._hash,
            symbol=self.symbol,
            state_version=STATE_VERSION,
            last_trade_seq=self._last_seq,
            blob=orjson.dumps(doc),
        )

    def restore(self, state: BuilderState) -> None:
        if (state.spec_hash, state.symbol) != (self._hash, self.symbol):
            raise BarsError("The builder state belongs to a different symbol or bar spec.")
        if state.state_version != STATE_VERSION:
            raise BarsError(f"Builder state version {state.state_version} is not supported.")
        doc = orjson.loads(state.blob)
        self._cur = None if doc["cur"] is None else _Draft.load(doc["cur"])
        self._closed = deque(_Draft.load(r) for r in doc["closed"])
        self._next_index = doc["next_index"]
        self._last_close = doc["last_close"]
        self._watermark = doc["watermark"]
        self._last_seq = state.last_trade_seq
