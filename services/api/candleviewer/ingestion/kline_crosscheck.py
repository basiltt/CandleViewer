"""Kline cross-check mode (E12-S05; `24-internal-schemas.md` §2.4: klines are "a cross-check
and a cold-start backfill").

Compares exchange klines against builder-produced (tape) bars for the same window, matching on
open time. A divergence beyond tolerance is logged with symbol, interval and bar timestamp and
counted in `kline_crosscheck_divergence_total`, so persistent feed rot shows up on a dashboard.

**Documented tolerance:** prices (o/h/l/c) must match within `price_ticks` ticks (default 0 —
both sides come from the same exchange trades); volume within `volume_rel` relative error
(default 0.1 %, absorbing exchange-side rounding of `size` into the kline volume). Bars present
on only one side, and forming bars (unconfirmed kline or unclosed tape bar), are not
divergences (gaps are reported elsewhere; a forming bar is still moving). Structurally
typed so `ingestion` never imports `bars` (C-3.1).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Protocol

from candleviewer.ingestion._logging import get_logger
from candleviewer.ingestion.metrics import kline_crosscheck_divergence_total, symbol_label

DEFAULT_VOLUME_REL: Final = Decimal("0.001")
_FIELDS: Final = ("open", "high", "low", "close")


class OhlcvLike(Protocol):
    @property
    def open(self) -> Decimal: ...
    @property
    def high(self) -> Decimal: ...
    @property
    def low(self) -> Decimal: ...
    @property
    def close(self) -> Decimal: ...
    @property
    def volume(self) -> Decimal: ...


class KlineLike(OhlcvLike, Protocol):
    @property
    def start(self) -> int: ...
    @property
    def confirmed(self) -> bool: ...


class TapeBarLike(OhlcvLike, Protocol):
    @property
    def open_time(self) -> int: ...
    @property
    def closed(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class Divergence:
    ts_us: int
    fields: tuple[str, ...]


def cross_check(
    symbol: str,
    interval: str,
    klines: Sequence[KlineLike],
    tape_bars: Sequence[TapeBarLike],
    *,
    tick_size: Decimal | None = None,
    price_ticks: int = 0,
    volume_rel: Decimal = DEFAULT_VOLUME_REL,
) -> list[Divergence]:
    """Return (and log + count) every bar whose OHLCV diverges beyond tolerance."""
    price_tol = (tick_size or Decimal(0)) * price_ticks
    # A3: only closed bars on both sides are comparable; a forming bar is still moving.
    tape = {b.open_time: b for b in tape_bars if b.closed}
    out: list[Divergence] = []
    for k in klines:
        bar = tape.get(k.start) if k.confirmed else None
        if bar is None:
            continue
        bad = [f for f in _FIELDS if abs(getattr(k, f) - getattr(bar, f)) > price_tol]
        ref = max(abs(bar.volume), abs(k.volume))
        if ref and abs(k.volume - bar.volume) > ref * volume_rel:
            bad.append("volume")
        if bad:
            out.append(Divergence(k.start, tuple(bad)))
    if out:
        kline_crosscheck_divergence_total.labels(
            symbol=symbol_label(symbol), interval=interval
        ).inc(len(out))
        log = get_logger(__name__)
        for d in out[:50]:  # bounded log volume; the metric carries the full count
            log.warning("kline_crosscheck_divergence", symbol=symbol, interval=interval,
                        ts_us=d.ts_us, fields=list(d.fields))  # fmt: skip
    return out


__all__ = ["DEFAULT_VOLUME_REL", "Divergence", "KlineLike", "TapeBarLike", "cross_check"]
