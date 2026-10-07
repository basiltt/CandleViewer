"""`BarSeries` container and `densify()` (`24-internal-schemas.md` Â§3.3a, E12-T01).

Densified bars are synthetic (`synthetic=True`, `volume=0`, flat at `prev.close`) and exist
only for consumers that need a continuous index (indicators). They are **never persisted**:
the storage boundary (E12-T02) must call `assert_persistable` on every bar before writing a
row; it raises `SyntheticBarPersistError` instead of writing.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from decimal import Decimal

from candleviewer.bars.errors import BarsError, SyntheticBarPersistError
from candleviewer.bars.models import Bar, BarSpec

_ZERO = Decimal(0)


def assert_persistable(bar: Bar) -> Bar:
    """Persistence-boundary guard: synthetic bars must never become rows."""
    if bar.synthetic:
        raise SyntheticBarPersistError(
            f"Bar {bar.index} of {bar.symbol} is a synthetic densify() bar "
            "and must not be persisted."
        )
    return bar


class BarSeries:
    """An ordered, immutable run of bars for one `(symbol, spec)`."""

    __slots__ = ("bars", "spec")

    def __init__(self, spec: BarSpec, bars: Sequence[Bar]) -> None:
        self.spec = spec
        self.bars: tuple[Bar, ...] = tuple(bars)

    def __len__(self) -> int:
        return len(self.bars)

    def __iter__(self) -> Iterator[Bar]:
        return iter(self.bars)

    def densify(self) -> BarSeries:
        """Fill empty time intervals with flat synthetic bars (time specs only).

        Real bars are passed through untouched (same objects: `index`, `gap_before` and every
        other field unchanged), so §3.1 "index monotonic per (symbol, spec_hash)" holds for
        real keys. Fillers cannot take a fresh index without renumbering real bars, so each
        filler carries the `index` of the real bar preceding its gap and is identified by
        `synthetic=True`; the view is non-decreasing in `index`, and consumers needing a
        contiguous position use the sequence position. Fillers are never persistable.
        """
        if self.spec.kind != "time":
            raise BarsError("densify() applies to time bars only; other kinds have no empty slots.")
        step = int(self.spec.param_value) * 1000
        out: list[Bar] = []
        prev_real: Bar | None = None
        for bar in self.bars:
            if prev_real is not None:
                prev = out[-1]
                t = prev.open_time + step
                while t < bar.open_time:
                    prev = _flat(prev, t, step, prev_real.index)
                    out.append(prev)
                    t += step
            out.append(bar)
            prev_real = bar
        return BarSeries(self.spec, out)


def _flat(prev: Bar, open_time: int, step: int, index: int) -> Bar:
    px = prev.close
    return Bar.model_construct(
        spec_hash=prev.spec_hash,
        symbol=prev.symbol,
        index=index,
        open_time=open_time,
        close_time=open_time + step,
        open=px,
        high=px,
        low=px,
        close=px,
        volume=_ZERO,
        buy_volume=_ZERO,
        sell_volume=_ZERO,
        delta=_ZERO,
        min_delta=_ZERO,
        max_delta=_ZERO,
        trade_count=0,
        turnover=_ZERO,
        vwap=px,
        closed=True,
        partial=False,
        gap_before=False,
        synthetic=True,
    )
