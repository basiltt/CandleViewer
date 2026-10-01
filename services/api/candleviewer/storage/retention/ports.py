"""Ports the reaper depends on (E07-T05). Concrete adapters arrive with E16/E42."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from candleviewer.storage.cold.observability import SystemEventSink
from candleviewer.storage.models import StreamKind, TimeRange

Tier = Literal["hot", "cold"]


@dataclass(frozen=True, slots=True)
class Partition:
    symbol: str
    stream: StreamKind
    tier: Tier
    range: TimeRange
    rows: int
    bytes: int


class StorageOps(Protocol):
    """Inventory + destructive ops. Paths never come from callers (SR-097)."""

    async def list_partitions(
        self, symbol: str, stream: StreamKind, tier: Tier
    ) -> list[Partition]: ...

    async def is_exported_and_verified(self, part: Partition) -> bool: ...

    async def drop(self, part: Partition) -> None:
        """QuestDB `DROP PARTITION` (hot) / partition-directory delete (cold)."""
        ...


class RetentionFacts(Protocol):
    """Read-only facts from Postgres; an absent table reads as the empty set."""

    async def symbols(self) -> list[str]: ...

    async def pinned_symbols(self) -> set[str]: ...

    async def priority(self, symbol: str) -> int: ...

    async def auto_recorded_symbols(self) -> set[str]: ...

    async def replay_session_for(self, part: Partition) -> str | None:
        """Id of an active `replay_sessions` row referencing `part`, if any."""
        ...

    async def has_unexported_journal_trade(self, part: Partition) -> bool: ...


class DiskProbe(Protocol):
    def free_pct(self) -> float: ...


class AuditWriter(Protocol):
    """Append-only (SR-099): one entry per deletion."""

    async def write(self, action: str, detail: dict[str, str | int]) -> None: ...


class RecorderControl(Protocol):
    async def pause(self, symbol: str) -> None: ...


__all__ = [
    "AuditWriter",
    "DiskProbe",
    "Partition",
    "RecorderControl",
    "RetentionFacts",
    "StorageOps",
    "SystemEventSink",
    "Tier",
]
