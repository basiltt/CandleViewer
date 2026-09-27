"""`MarketDataRepository` Protocol — hot/cold market-data read/write surface.

`Protocol`, not an ABC (ticket "Technical notes / design"): implementations
(E07-T02 Postgres relational bits, E07-T03 QuestDB, E07-T04 cold tier, and
this ticket's own in-memory fake) need no inheritance, so a fake stays a
plain class that happens to structurally match.

Write methods are batch-only (`Sequence[...]`) on purpose — a per-row API
would make the ILP batching budget of `docs/plan/20-architecture.md` Sec.4.14
unreachable (ticket "Technical notes / design"). Every read method takes a
`TierHint`; `"auto"` resolution lives in E07-T05's router, never here.
"""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from candleviewer.storage.models import TierHint, TimeRange
from candleviewer.storage.repositories.rows import (
    BarRow,
    BookDeltaRow,
    BookSnapshotRow,
    FootprintCellRow,
    OrderflowMetricRow,
    TickerRow,
    TradeRow,
)


@runtime_checkable
class MarketDataRepository(Protocol):
    """Batch writes, tier-aware reads, for every raw and derived market stream.

    Ordering guarantee: every `read_*` method returns rows ordered by
    ascending `ts_us` (ties broken by natural key — `trade_id`/`seq`/price
    level — where the row type has one); callers must not re-sort. Writes do
    not guarantee ordering is preserved (implementations may reorder for
    batching), but a `read_*` immediately following a `write_*` of the same
    range always reflects the write once the coroutine returns.
    """

    async def write_trades(self, rows: Sequence[TradeRow]) -> None:
        """Append trade prints. Dedup key: `(symbol, trade_id)`."""
        ...

    async def write_book_deltas(self, rows: Sequence[BookDeltaRow]) -> None:
        """Append book deltas. Dedup key: `(symbol, seq)`."""
        ...

    async def write_book_snapshot(self, row: BookSnapshotRow) -> None:
        """Persist a full book snapshot. Dedup key: `(symbol, seq)`."""
        ...

    async def write_tickers(self, rows: Sequence[TickerRow]) -> None:
        """Append ticker updates. Dedup key: `(symbol, ts_us)`."""
        ...

    async def write_bars(self, rows: Sequence[BarRow]) -> None:
        """Append/upsert bars. Dedup key: `(symbol, family, param, ts_us)`."""
        ...

    async def read_bars(
        self,
        sym: str,
        family: str,
        param: str,
        rng: TimeRange,
        tier: TierHint = "auto",
    ) -> list[BarRow]:
        """Read bars for `(sym, family, param)` within `rng`, ascending `ts_us`."""
        ...

    async def read_trades(
        self, sym: str, rng: TimeRange, tier: TierHint = "auto"
    ) -> list[TradeRow]:
        """Read trades for `sym` within `rng`, ascending `(ts_us, trade_id)`."""
        ...

    async def read_book_snapshot_at(
        self, sym: str, ts_us: int, depth: int, tier: TierHint = "auto"
    ) -> BookSnapshotRow | None:
        """Latest snapshot at or before `ts_us`, truncated to `depth` levels
        per side, or `None` if no snapshot exists at/before that time."""
        ...

    async def read_book_deltas(
        self, sym: str, rng: TimeRange, tier: TierHint = "auto"
    ) -> list[BookDeltaRow]:
        """Read deltas for `sym` within `rng`, ascending `(ts_us, seq)`."""
        ...

    async def read_orderflow_metrics(
        self, sym: str, metric: str, rng: TimeRange, tier: TierHint = "auto"
    ) -> list[OrderflowMetricRow]:
        """Read one metric series for `sym` within `rng`, ascending `ts_us`."""
        ...

    async def read_footprint_cells(
        self, sym: str, rng: TimeRange, tier: TierHint = "auto"
    ) -> list[FootprintCellRow]:
        """Read footprint cells for `sym` within `rng`, ascending
        `(bar_ts_us, price_level)`."""
        ...

    async def latest_ticker(self, sym: str, tier: TierHint = "auto") -> TickerRow | None:
        """Most recent ticker for `sym`, or `None` if none has been written."""
        ...
