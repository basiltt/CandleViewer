"""storage module (M10).

Postgres repositories, QuestDB writer/reader, Parquet/DuckDB tier, retention.

Public interface only — internal implementation modules are not re-exported.
Allowed dependencies (CONSTITUTION.md C-3.1): M1.

E07-T01 (`docs/plan/27-adrs/ADR-0003-storage-tiers.md`): repository
Protocols, `StorageService` lifecycle, domain models and error types. Real
engine clients (Postgres/QuestDB/cold tier) are E07-T02/T03/T04; aggregate-
specific relational repositories are owned by their respective epics
(E09/E27/E29, ...). In-memory fakes live under `candleviewer.storage.testing`
so other modules can import them without reaching into this package's own
test tree.
"""

from __future__ import annotations

from candleviewer.storage.errors import (
    StorageDiskCritical,
    StorageError,
    StorageExportVerifyFailed,
    StorageRetentionBlockedByPin,
    StorageSchemaDrift,
    StorageTierUnavailable,
)
from candleviewer.storage.health import StorageHealthReport, TierHealth, TierState
from candleviewer.storage.models import (
    ExportRun,
    RetentionDecision,
    StreamKind,
    StorageTier,
    SymbolStream,
    TierHint,
    TimeRange,
)
from candleviewer.storage.repositories import (
    ColdTierRepository,
    MarketDataRepository,
    RelationalRepository,
    RetentionRepository,
    UnitOfWork,
)
from candleviewer.storage.service import StorageService

__all__ = [
    "ColdTierRepository",
    "ExportRun",
    "MarketDataRepository",
    "RelationalRepository",
    "RetentionDecision",
    "RetentionRepository",
    "StorageDiskCritical",
    "StorageError",
    "StorageExportVerifyFailed",
    "StorageHealthReport",
    "StorageRetentionBlockedByPin",
    "StorageSchemaDrift",
    "StorageService",
    "StorageTier",
    "StorageTierUnavailable",
    "StreamKind",
    "SymbolStream",
    "TierHealth",
    "TierHint",
    "TierState",
    "TimeRange",
    "UnitOfWork",
]
