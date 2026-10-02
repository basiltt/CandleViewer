"""Retention reaper (E07-T05). Control-flow order is a safety property:

resolve -> exclude pinned -> exclude replay-referenced -> exclude unexported/
unverified -> dry-run report -> (disk<15%: accelerate, alert FIRST) -> audit ->
drop one partition at a time, one audit entry per deletion. A plan is always
re-derived from current facts (idempotent, resumable) and every blocking
predicate is re-checked immediately before a drop (a pin added after the
dry-run still wins).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from candleviewer.observability.metrics import Counter, Gauge
from candleviewer.storage.errors import (
    StorageDiskCritical,
    StorageRetentionBlockedByPin,
    StorageRetentionBlockedByReplay,
    StorageRetentionBlockedUnverified,
)
from candleviewer.storage.retention.locks import InProcessRunLock
from candleviewer.storage.retention.policy import RetentionPolicy
from candleviewer.storage.retention.ports import (
    AuditWriter,
    DiskProbe,
    Partition,
    RecorderControl,
    RetentionFacts,
    RunLock,
    StorageOps,
    SystemEventSink,
    Tier,
)

storage_retention_runs_total = Counter("storage_retention_runs_total", "Reaper runs.", ["result"])
storage_retention_dropped_bytes_total = Counter(
    "storage_retention_dropped_bytes_total", "Bytes freed.", ["symbol", "stream"]
)
storage_retention_skipped_total = Counter(
    "storage_retention_skipped_total", "Partitions skipped.", ["reason"]
)
storage_disk_free_ratio = Gauge("storage_disk_free_ratio", "Free disk ratio.", ["volume"])

_US_PER_DAY = 86_400_000_000
MIN_FREE_PCT = 15.0
RECOVER_FREE_PCT = 25.0
CRITICAL_FREE_PCT = 5.0
_PROCESS_LOCK = InProcessRunLock()

Reason = Literal["", "pinned", "replay", "unverified", "journal"]
_ERRORS = {
    "pinned": StorageRetentionBlockedByPin.code,
    "replay": StorageRetentionBlockedByReplay.code,
    "unverified": StorageRetentionBlockedUnverified.code,
    "journal": StorageRetentionBlockedUnverified.code,
}


@dataclass(frozen=True, slots=True)
class ReportItem:
    partition: Partition
    action: Literal["drop", "skip"]
    reason: Reason = ""
    detail: str = ""

    @property
    def error_code(self) -> str:
        return _ERRORS.get(self.reason, "")


@dataclass(slots=True)
class RetentionReport:
    items: list[ReportItem]
    accelerated: bool = False
    affected_symbols: list[str] = field(default_factory=list)

    @property
    def to_drop(self) -> list[ReportItem]:
        return [i for i in self.items if i.action == "drop"]

    @property
    def skipped(self) -> list[ReportItem]:
        return [i for i in self.items if i.action == "skip"]


def _detail(part: Partition) -> dict[str, str | int]:
    return {
        "symbol": part.symbol,
        "stream": part.stream.value,
        "tier": part.tier,
        "range_start_us": part.range.start_us,
        "range_end_us": part.range.end_us,
        "freed_bytes": part.bytes,
        "rows": part.rows,
    }


class Reaper:
    def __init__(
        self,
        policy: RetentionPolicy,
        ops: StorageOps,
        facts: RetentionFacts,
        disk: DiskProbe,
        audit: AuditWriter,
        events: SystemEventSink,
        recorder: RecorderControl,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        volume: str = "data",
        lock: RunLock | None = None,
    ) -> None:
        self._policy, self._ops, self._facts = policy, ops, facts
        self._disk, self._audit, self._events, self._recorder = disk, audit, events, recorder
        self._clock, self._volume = clock, volume
        self._accelerated = False
        # SR-099: one run per volume across instances (Postgres advisory lock in
        # production); the per-drop existence re-check is the second line.
        self._lock: RunLock = lock if lock is not None else _PROCESS_LOCK

    def _update_mode(self) -> float:
        free = self._disk.free_pct()
        storage_disk_free_ratio.labels(volume=self._volume).set(free / 100.0)
        if free < MIN_FREE_PCT:
            self._accelerated = True
        elif free > RECOVER_FREE_PCT:
            self._accelerated = False
        return free

    async def guard(self) -> bool:
        """SR-096: <5% free pauses non-pinned auto-recorded symbols (critical
        event first). Trading does not share this volume. True if paused."""
        free = self._update_mode()
        if free >= CRITICAL_FREE_PCT:
            return False
        pinned = await self._facts.pinned_symbols()
        targets = sorted((await self._facts.auto_recorded_symbols()) - pinned)
        await self._events.emit(
            "CRITICAL",
            StorageDiskCritical.code,
            {"free_pct": int(free), "paused_symbols": len(targets)},
        )
        for symbol in targets:
            await self._recorder.pause(symbol)
        return True

    async def _blocker(self, part: Partition, pinned: set[str]) -> tuple[Reason, str]:
        if part.symbol in pinned:
            return "pinned", ""
        session = await self._facts.replay_session_for(part)
        if session is not None:
            return "replay", f"session_id={session}"
        if part.tier == "hot":
            if not await self._ops.is_exported_and_verified(part):
                return "unverified", ""
            if await self._facts.has_unexported_journal_trade(part):
                return "journal", ""
        return "", ""

    async def dry_run(self) -> RetentionReport:
        """Pure planning: never mutates storage."""
        self._update_mode()
        factor = 0.5 if self._accelerated else 1.0
        now_us = int(self._clock().timestamp() * 1_000_000)
        pinned = await self._facts.pinned_symbols()
        symbols = await self._facts.symbols()
        if self._accelerated:
            prio = {s: await self._facts.priority(s) for s in symbols}
            symbols = sorted(symbols, key=lambda s: (prio[s], s))
        items: list[ReportItem] = []
        affected: list[str] = []
        tiers: tuple[Tier, ...] = ("hot", "cold")
        for symbol in symbols:
            for stream in self._policy.streams:
                rule = self._policy.resolve(symbol, stream)
                if rule is None:
                    continue
                for tier in tiers:
                    days = rule.hot_days if tier == "hot" else rule.cold_days
                    if days is None:
                        continue
                    cutoff = now_us - int(days * factor * _US_PER_DAY)
                    for part in await self._ops.list_partitions(symbol, stream, tier):
                        if part.range.end_us > cutoff:
                            continue
                        reason, detail = await self._blocker(part, pinned)
                        items.append(ReportItem(part, "skip" if reason else "drop", reason, detail))
                        if not reason and symbol not in affected:
                            affected.append(symbol)
        return RetentionReport(items, self._accelerated, affected)

    async def apply(self, report: RetentionReport) -> RetentionReport:
        """Execute only what `report` listed. Alert BEFORE any delete."""
        if report.accelerated:
            for symbol in report.affected_symbols:
                await self._events.emit(
                    "WARNING", "STORAGE_ACCELERATED_RETENTION", {"symbol": symbol}
                )
        for item in report.skipped:
            storage_retention_skipped_total.labels(reason=item.reason).inc()
            if item.reason == "unverified":
                await self._events.emit(
                    "CRITICAL",
                    _ERRORS["unverified"],
                    {"symbol": item.partition.symbol, "stream": item.partition.stream.value},
                )
            await self._audit.write(
                "retention.skip",
                _detail(item.partition) | {"reason": item.reason, "info": item.detail},
            )
        pinned = await self._facts.pinned_symbols()
        result: list[ReportItem] = list(report.skipped)
        failures = 0
        for item in report.to_drop:
            part = item.partition
            reason, detail = await self._blocker(part, pinned)  # re-check right before drop
            if reason:
                storage_retention_skipped_total.labels(reason=reason).inc()
                result.append(ReportItem(part, "skip", reason, detail))
                if reason == "unverified":
                    await self._events.emit(
                        "CRITICAL",
                        _ERRORS[reason],
                        {"symbol": part.symbol, "stream": part.stream.value},
                    )
                continue
            current = await self._ops.list_partitions(part.symbol, part.stream, part.tier)
            if part not in current:  # already reaped by another instance: idempotent no-op
                storage_retention_skipped_total.labels(reason="already_dropped").inc()
                continue
            try:
                await self._ops.drop(part)
            except Exception as exc:  # justified: one failure must not abort the run
                failures += 1
                info = f"drop_failed:{type(exc).__name__}"
                result.append(ReportItem(part, "skip", "", info))
                await self._audit.write("retention.drop_failed", _detail(part) | {"info": info})
                await self._events.emit(
                    "WARNING",
                    "STORAGE_RETENTION_DROP_FAILED",
                    {
                        "symbol": part.symbol,
                        "stream": part.stream.value,
                        "error": type(exc).__name__,
                    },
                )
                continue
            await self._audit.write("retention.purge", _detail(part))
            storage_retention_dropped_bytes_total.labels(
                symbol=part.symbol, stream=part.stream.value
            ).inc(part.bytes)
            result.append(item)
            await asyncio.sleep(0)  # yield to ingestion between partitions
        storage_retention_runs_total.labels(result="partial" if failures else "ok").inc()
        return RetentionReport(result, report.accelerated, report.affected_symbols)

    async def run(self, *, dry_run_only: bool = False) -> RetentionReport:
        """Daily job entry: guard, dry-run first (audited), then apply."""
        async with self._lock.hold(self._volume) as acquired:
            if not acquired:
                storage_retention_runs_total.labels(result="skipped_locked").inc()
                return RetentionReport([])
            return await self._run(dry_run_only)

    async def _run(self, dry_run_only: bool) -> RetentionReport:
        await self.guard()
        report = await self.dry_run()
        await self._audit.write(
            "retention.dry_run",
            {
                "drop": len(report.to_drop),
                "skip": len(report.skipped),
                "accelerated": int(report.accelerated),
            },
        )
        if dry_run_only:
            return report
        return await self.apply(report)
