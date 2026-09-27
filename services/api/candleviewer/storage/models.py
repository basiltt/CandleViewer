"""Domain models for the storage module (M10).

`docs/plan/24-internal-schemas.md` config models remain the single source of
truth for `ParquetConfig`/`QuestDbConfig`; this module defines the storage
package's own domain vocabulary (E07-T01): stream kinds, time ranges, tier
hints, and the small set of admin-facing models (`ExportRun`,
`RetentionDecision`) that later E07 tickets extend.

Market-data *row* types deliberately live in `storage/repositories/rows.py`
as `slots=True` dataclasses, not here and not as pydantic `BaseModel`s — the
"Performance notes" section of E07-T01 requires the read path to avoid ORM/
pydantic hydration cost for the `<100 ms for 100k bars` budget
(`docs/plan/20-architecture.md` Sec.13.2). Everything in *this* file is
low-frequency (config-adjacent) and pydantic v2 is the right tool.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

#: Aligned with `docs/plan/22-api-openapi.yaml` `StreamKind` and
#: `docs/plan/21-database-schema.md` Sec.4. The OpenAPI enum only lists the
#: raw ingestion streams (`trades`, `orderbook_delta`, ...); the engine's own
#: derived streams (`bars`, `footprint_cells`, `profiles`,
#: `orderflow_metrics`, `heatmap_cells`) are appended per this ticket's own
#: "Scope / Deliverables" list, which names all thirteen explicitly.
class StreamKind(StrEnum):
    """Every stream the storage tiers persist or serve, hot or cold."""

    TRADES = "trades"
    ORDERBOOK_DELTA = "orderbook_delta"
    ORDERBOOK_SNAPSHOT = "orderbook_snapshot"
    TICKERS = "tickers"
    KLINES = "klines"
    LIQUIDATIONS = "liquidations"
    OPEN_INTEREST = "open_interest"
    FUNDING_RATES = "funding_rates"
    BARS = "bars"
    FOOTPRINT_CELLS = "footprint_cells"
    PROFILES = "profiles"
    ORDERFLOW_METRICS = "orderflow_metrics"
    HEATMAP_CELLS = "heatmap_cells"


#: `auto` resolution (hot vs. cold) is owned by E07-T05's router — never by
#: call sites (ticket "Technical notes / design").
TierHint = Literal["hot", "cold", "auto"]

#: Concrete tier a `HealthReport` names — distinct from `TierHint` because a
#: read call never asks for `"fake"`, but a health report must be able to say
#: which backend (including the E07-T01 in-memory fake) answered it.
StorageTier = Literal["postgres", "questdb", "cold", "fake"]


class TimeRange(BaseModel):
    """An inclusive-start, exclusive-end microsecond-UTC time range.

    Integer microseconds (not `datetime`) per the ticket's explicit
    "`TimeRange` (integer microseconds UTC)" deliverable — this is the unit
    every hot-tier client (QuestDB ILP, Postgres) and the read Protocols use,
    so range comparisons never pay a `datetime` parse/format round trip on a
    hot path.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    start_us: int
    end_us: int

    @field_validator("end_us")
    @classmethod
    def _end_after_start(cls, value: int, info: object) -> int:
        start = getattr(info, "data", {}).get("start_us") if info is not None else None
        if start is not None and value < start:
            raise ValueError("end_us must be >= start_us")
        return value

    @classmethod
    def from_datetimes(cls, start: datetime, end: datetime) -> TimeRange:
        """Convenience constructor for call sites that still hold `datetime`s."""
        return cls(
            start_us=int(start.timestamp() * 1_000_000),
            end_us=int(end.timestamp() * 1_000_000),
        )


class SymbolStream(BaseModel):
    """A `(symbol, stream)` pair — the unit every repository method reads or
    writes by, and the unit `RetentionRepository.policies()` scopes rules to.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    stream: StreamKind


class ExportRun(BaseModel):
    """One cold-tier export attempt (`ColdTierRepository.export_partition`).

    `verified` is set only after `verify_checksums` succeeds — the ticket's
    acceptance criteria treat verification as a separate, explicit step so a
    partition is never considered durable on write-success alone.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    symbol: str
    stream: StreamKind
    partition_range: TimeRange
    row_count: int
    verified: bool = False


class RetentionDecision(BaseModel):
    """A single retention-plan line item (`RetentionRepository.plan`).

    `action="skip"` with a non-empty `reason` is how a `RetentionPin`
    (`StorageRetentionBlockedByPin`) or an in-flight export shows up in a
    dry-run plan without raising — the caller decides whether a non-empty
    skip list is itself an error.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    stream: StreamKind
    action: Literal["roll_off_to_cold", "delete", "skip"]
    range: TimeRange
    reason: str = ""
