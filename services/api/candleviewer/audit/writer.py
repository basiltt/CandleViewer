"""`AuditWriter` — WAL-first, never-lossy audit append path (C-2.9, C-2.18).

Write path (PR #1561 security findings 1-2):

1. `emit()` validates the action, redacts `before_state`/`after_state`,
   assigns a `record_id` (uuid) and **durably appends** the record to the
   local WAL (`write` + `fsync`, in a worker thread so the loop never blocks,
   serialised by `_wal_lock`) *before it returns*. Acceptance == durability:
   once `emit()` returns, the record survives `stop()`, a crash or a
   Postgres outage.
2. A single flusher task reads uncommitted records from the WAL in append
   order and inserts each into `audit_log` (the repository and the
   `audit_chain()` trigger both take `pg_advisory_xact_lock`), then advances
   the WAL commit cursor. Postgres errors are retried with backoff; the WAL
   is the buffer.
3. `start()` replays any WAL records left by a previous run first (same
   loop). Replay is idempotent: `record_id` is UNIQUE and the insert is
   `ON CONFLICT (record_id) DO NOTHING`, closing the "row committed, cursor
   not advanced" crash window — every record reaches the DB exactly once.

Overflow policy (bounded, fail-closed, never drop): the WAL is capped at
`max_wal_bytes`. When full, the committed prefix is compacted and the append
retried; if it is still full (Postgres down long enough to fill it), or the
WAL cannot be written at all (`OSError`), `emit()` raises
`AuditUnavailable` and fires `on_alarm`. Callers MUST treat that as "refuse
the audited action". No record that `emit()` accepted is ever discarded.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from candleviewer.audit.actions import validate_action
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditEmission, AuditOutcome, ExchangeEnv, Severity
from candleviewer.audit.redact import redact
from candleviewer.audit.repository import AuditRepository
from candleviewer.audit.wal import AuditWal, AuditWalFull

logger = logging.getLogger(__name__)

AlarmCallback = Callable[[str], Awaitable[None]] | None
Clock = Callable[[], datetime]
Sleeper = Callable[[float], Awaitable[None]]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _uuid_or_none(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(value)


class AuditWriter:
    """Owns the WAL and the single flusher task.

    `start()` spawns the flusher (which first replays WAL backlog);
    `stop(grace_s)` stops accepting `emit()`, waits up to `grace_s` for the
    WAL to drain into Postgres, then cancels the flusher. Anything not yet
    flushed is already durable in the WAL and is replayed on the next start.
    """

    def __init__(
        self,
        repository: AuditRepository,
        wal_path: str,
        *,
        flush_batch_size: int = 500,
        max_wal_bytes: int = 64 * 1024 * 1024,
        retry_initial_delay_s: float = 0.5,
        retry_max_delay_s: float = 30.0,
        on_alarm: AlarmCallback = None,
        clock: Clock = _utc_now,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        self._repository = repository
        self._wal = AuditWal(_path(wal_path), max_bytes=max_wal_bytes)
        self._wal_lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._idle = asyncio.Event()
        self._flush_batch_size = flush_batch_size
        self._retry_initial_delay_s = retry_initial_delay_s
        self._retry_max_delay_s = retry_max_delay_s
        self._on_alarm = on_alarm
        self._clock = clock
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._pending = 0
        self._written_total = 0
        self._write_errors_total = 0
        self._refused_total = 0
        self._inflight = False

    @property
    def written_total(self) -> int:
        return self._written_total

    @property
    def refused_total(self) -> int:
        """`emit()` calls refused with `AuditUnavailable` (WAL full/unwritable)."""
        return self._refused_total

    @property
    def write_errors_total(self) -> int:
        return self._write_errors_total

    @property
    def buffer_depth(self) -> int:
        """Records accepted into the WAL by this process, not yet in Postgres."""
        return self._pending

    async def start(self) -> None:
        """Start the flusher. It replays WAL backlog from a previous run
        first, inside the task, so `start()` never blocks on Postgres."""
        if self._task is not None:
            return
        self._running = True
        self._idle.clear()
        self._wake.set()
        self._task = asyncio.create_task(self._run(), name="audit-writer")
        self._task.add_done_callback(_log_task_failure)

    async def flush(self, timeout_s: float) -> None:
        """Wait until every WAL record is committed to Postgres."""
        async with asyncio.timeout(timeout_s):
            await self._idle.wait()

    async def stop(self, grace_s: float = 5.0) -> None:
        self._running = False
        if self._task is None:
            return
        try:
            await self.flush(grace_s)
        except TimeoutError:
            logger.warning("AuditWriter.stop: WAL not drained within %.1fs", grace_s)
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            # Expected: we cancelled it. Every record emit() accepted is
            # already fsync'd in the WAL; unflushed ones are replayed
            # (idempotently, by record_id) on the next start().
            pass
        self._task = None

    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_user_id: str | uuid.UUID | None = None,
        actor_ip: str | None = None,
        session_id: str | uuid.UUID | None = None,
        object_kind: str | None = None,
        object_id: str | None = None,
        object_label: str | None = None,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        severity: Severity = Severity.INFO,
        reason: str | None = None,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
        request_id: str | uuid.UUID | None = None,
        env: ExchangeEnv | None = None,
    ) -> None:
        """Durably append one audit entry to the WAL, then return.

        Raises `AuditWriterStopped` if not running, `UnknownAuditAction` for
        an unregistered action, and `AuditUnavailable` if the record could
        not be made durable — the caller must then refuse the action."""
        if not self._running:
            raise AuditWriterStopped()
        validate_action(action)
        emission = AuditEmission(
            record_id=uuid.uuid4(),
            action=action,
            actor_label=actor_label,
            actor_user_id=_uuid_or_none(actor_user_id),
            actor_ip=actor_ip,
            session_id=_uuid_or_none(session_id),
            object_kind=object_kind,
            object_id=object_id,
            object_label=object_label,
            outcome=outcome,
            severity=severity,
            reason=reason,
            before_state=redact(before_state),
            after_state=redact(after_state),
            request_id=_uuid_or_none(request_id),
            env=env,
            event_ts=self._clock(),
        )
        record = json.loads(emission.model_dump_json())
        try:
            async with self._wal_lock:
                await self._append_durably(record)
                self._pending += 1
                # Under the lock, so the flusher cannot mark idle after this.
                self._idle.clear()
        except (AuditWalFull, OSError) as exc:
            self._refused_total += 1
            reason_text = f"audit WAL unavailable: {type(exc).__name__}"
            if self._on_alarm is not None:
                await self._on_alarm(reason_text)
            logger.critical(reason_text)
            raise AuditUnavailable(reason_text) from exc
        self._wake.set()

    async def _append_durably(self, record: dict[str, Any]) -> None:
        """Caller holds `_wal_lock`. On `AuditWalFull`, reclaim the committed
        prefix (only when no flush batch is in flight, whose offsets a
        compaction would invalidate) and retry once."""
        try:
            await asyncio.to_thread(self._wal.append, record)
        except AuditWalFull:
            if self._inflight or self._wal.committed_offset() == 0:
                raise
            await asyncio.to_thread(self._wal.compact)
            await asyncio.to_thread(self._wal.append, record)

    async def _run(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while True:
                async with self._wal_lock:
                    batch = await asyncio.to_thread(self._wal.read_pending, self._flush_batch_size)
                    self._inflight = bool(batch)
                    if not batch:
                        self._idle.set()
                if not batch:
                    break
                for _end_offset, record in batch:
                    await self._write_with_retry(record)
                    self._written_total += 1
                # One cursor fsync per batch: a crash mid-batch re-inserts the
                # already-written prefix, which ON CONFLICT (record_id) ignores.
                async with self._wal_lock:
                    await asyncio.to_thread(self._wal.mark_committed, batch[-1][0])
                    self._pending = max(0, self._pending - len(batch))
                    self._inflight = False
                    await asyncio.to_thread(self._wal.compact)

    async def _write_with_retry(self, record: dict[str, Any]) -> None:
        delay = self._retry_initial_delay_s
        while True:
            try:
                await self._repository.insert(record)
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # any driver error is retried; the record stays in the WAL
                self._write_errors_total += 1
                logger.warning(
                    "audit insert failed (%s), retrying in %.2fs", type(exc).__name__, delay
                )
                await self._sleep(delay)
                delay = min(delay * 2, self._retry_max_delay_s)


class AuditWriterStopped(AuditError):
    """Raised by `emit()` when the writer is not running (fail loudly, never drop)."""

    def __init__(self) -> None:
        super().__init__("AuditWriter is not running; emit() refused")


class AuditUnavailable(AuditError):
    """Raised by `emit()` when the record could not be made durable (WAL full
    or unwritable). The audited action must be refused (C-2.9 fail-closed)."""


def _log_task_failure(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.critical("audit writer task died", exc_info=task.exception())


def _path(raw: str) -> Path:
    return Path(raw)
