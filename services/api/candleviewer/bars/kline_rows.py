"""Kline -> `bars_time` rows (E12-S05, BR-07, SR-E12-10).

Exchange klines carry OHLCV only. A kline-sourced row therefore stores **NULL** — never zero —
in every order-flow column (`buy_volume`, `sell_volume`, `delta`, `min_delta`, `max_delta`,
`delta_pct`, `trade_count`, `vwap`): a zero delta is a lie, a NULL is a fact
(`22-api-openapi.yaml` `/market/klines`: "before that point delta/footprint fields are null").
The ILP serializer omits `None` fields, so they read back as NULL.

Rows are tagged `source="kline"`, which ranks below `tape`/`parquet` (`rows.SOURCE_RANK`), and
only *confirmed* klines become rows (an unconfirmed candle is never persisted as closed).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Final, Protocol

import structlog

from candleviewer.bars.errors import BarsError
from candleviewer.bars.models import BarSpec
from candleviewer.bars.rows import BUILD_VERSIONS, bar_param_for, row_checksum, to_double
from candleviewer.bars.spec import from_wire
from candleviewer.bars.writer import SourceOverwriteRefused
from candleviewer.exchange.base.models import KlineEvent

_log = structlog.get_logger(__name__)

KLINE_SOURCE: Final = "kline"
#: Columns a kline cannot know; always NULL on a kline-sourced row.
ORDERFLOW_NULL_COLUMNS: Final = (
    "buy_volume",
    "sell_volume",
    "delta",
    "min_delta",
    "max_delta",
    "delta_pct",
    "trade_count",
    "vwap",
)


class KlineRowError(BarsError):
    """A kline cannot become a `bars_time` row (unconfirmed, wrong symbol/interval)."""


def kline_spec(interval: str) -> BarSpec:
    """The time `BarSpec` for an exchange kline interval code (`"5"` -> 5-minute bars)."""
    return from_wire("time", interval)


def kline_row(event: KlineEvent, spec: BarSpec) -> dict[str, object]:
    """One ILP-ready `bars_time` row for a confirmed kline (designated `ts` = open, µs)."""
    if not event.confirmed:
        raise KlineRowError("An unconfirmed kline is never persisted as a closed bar.")
    if spec.kind != "time" or spec.interval_ms is None:
        raise KlineRowError("Kline rows only exist for time bars.")
    row: dict[str, object] = {
        "ts": event.start,
        "close_ts": event.start + spec.interval_ms * 1000,
        "symbol": event.symbol,
        "bar_param": bar_param_for(spec),
        "open": to_double(event.open),
        "high": to_double(event.high),
        "low": to_double(event.low),
        "close": to_double(event.close),
        "volume": to_double(event.volume),
        **dict.fromkeys(ORDERFLOW_NULL_COLUMNS),
        "is_closed": True,
        "build_version": BUILD_VERSIONS["time"],
        "source": KLINE_SOURCE,
    }
    row["row_checksum"] = row_checksum(row)
    return row


def kline_rows(events: Sequence[KlineEvent], spec: BarSpec) -> list[dict[str, object]]:
    """Rows for every confirmed kline in `events`; unconfirmed ones are skipped, not stored."""
    return [kline_row(e, spec) for e in events if e.confirmed]


class RowSubmitter(Protocol):
    async def submit_rows(
        self, rows: list[dict[str, object]], spec: BarSpec, *, source: str
    ) -> None: ...


#: `(symbol, bar_param, open-time µs list) -> open times already holding a tape/parquet row`.
#: The stored-row half of SR-E12-10 (the writer only knows rows this process wrote).
StoredHigherSource = Callable[[str, str, list[int]], Awaitable[set[int]]]


async def submit_kline_bars(
    writer: RowSubmitter,
    symbol: str,
    interval: str,
    events: Sequence[KlineEvent],
    *,
    stored_higher: StoredHigherSource | None = None,
) -> int:
    """Persist confirmed klines as `source=kline` rows; returns rows queued.

    A kline never overwrites tape (BR-07): open times already holding a higher-ranked stored
    row are dropped up front, and if the writer still refuses the batch
    (`SourceOverwriteRefused`, a tape row written by this process) rows are retried one by
    one so only the conflicting ones are skipped — never forced through.
    """
    spec = kline_spec(interval)
    rows = [r for r in kline_rows(events, spec) if r["symbol"] == symbol]
    if stored_higher is not None and rows:
        taken = await stored_higher(symbol, bar_param_for(spec), [int(str(r["ts"])) for r in rows])
        rows = [r for r in rows if int(str(r["ts"])) not in taken]
    if not rows:
        return 0
    try:
        await writer.submit_rows(rows, spec, source=KLINE_SOURCE)
        return len(rows)
    except SourceOverwriteRefused:
        queued = 0
        for row in rows:
            try:
                await writer.submit_rows([row], spec, source=KLINE_SOURCE)
                queued += 1
            except SourceOverwriteRefused:
                continue  # counted by the writer (`bars_source_overwrite_refused_total`)
        _log.info("kline_rows_skipped_over_tape", symbol=symbol, skipped=len(rows) - queued)
        return queued


__all__ = [
    "KLINE_SOURCE",
    "ORDERFLOW_NULL_COLUMNS",
    "KlineRowError",
    "RowSubmitter",
    "StoredHigherSource",
    "kline_row",
    "kline_rows",
    "kline_spec",
    "submit_kline_bars",
]
