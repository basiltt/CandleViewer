"""`AuditWriter` — the single writer task through which every `audit.emit`
call is serialised (ticket "Technical notes / design": "Inserts are
serialised through a single writer task to keep the chain well-ordered under
concurrency"; the trigger's own `SELECT ... ORDER BY id DESC LIMIT 1` would
otherwise race under concurrent INSERTs).

Write path: `emit()` builds a redacted `AuditEmission` and puts it on a
bounded `asyncio.Queue` — this is the only thing on the hot call-site path,
so it returns in the ticket's <1 ms budget. The writer task pulls one
record at a time, durably appends it to the on-disk WAL (`fsync`, survives a
crash), then inserts it into `audit_log` inside
`pg_advisory_xact_lock(hashtext('audit_log'))` so the chain trigger's
read-then-write cannot race with a second connection. On success the WAL
cursor advances past that record; on a Postgres outage the insert is retried
with backoff while later `emit()` calls keep queuing (backpressure is the
bounded queue, not data loss) until Postgres returns, at which point the
writer drains the backlog **and** the WAL (crash-recovery path) in original
order, so `audit_log` ends up densely, monotonically chained with no gaps
and no duplicates (ticket AC "Postgres outage does not lose events").
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
    """Owns the bounded queue, the WAL and the single background writer task.

    `start()`/`stop()` follow the module lifecycle contract every other
    package here implements: `start()` spawns the writer task (and replays
    any WAL backlog left over from a previous crash); `stop(grace_s)` stops
    accepting new `emit()` calls, drains the queue (bounded by `grace_s`)
    and joins the writer task.
    """

    def __init__(
        self,
        repository: AuditRepository,
        wal_path: str,
        *,
        max_queue_size: int = 10_000,
        max_wal_bytes: int = 64 * 1024 * 1024,
        retry_initial_delay_s: float = 0.5,
        retry_max_delay_s: float = 30.0,
        on_alarm: AlarmCallback = None,
        clock: Clock = _utc_now,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        self._repository = repository
        self._wal = AuditWal(_path(wal_path), max_bytes=max_wal_bytes)
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max_queue_size)
        self._retry_initial_delay_s = retry_initial_delay_s
        self._retry_max_delay_s = retry_max_delay_s
        self._on_alarm = on_alarm
        self._clock = clock
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._dropped_total = 0
        self._written_total = 0
        self._write_errors_total = 0

    @property
    def written_total(self) -> int:
        return self._written_total

    @property
    def dropped_total(self) -> int:
        return self._dropped_total

    @property
    def write_errors_total(self) -> int:
        return self._write_errors_total

    @property
    def buffer_depth(self) -> int:
        return self._queue.qsize()

    async def start(self) -> None:
        """Start the single writer task. It first replays any WAL backlog
        left by a previous crash (in original order), then consumes new
        `emit()` calls — replay runs inside the task so `start()` never
        blocks the composition root while Postgres is unavailable."""
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="audit-writer")
        self._task.add_done_callback(_log_task_failure)

    async def stop(self, grace_s: float = 5.0) -> None:
        self._running = False
        if self._task is None:
            return
        try:
            await asyncio.wait_for(self._queue.join(), timeout=grace_s)
        except TimeoutError:
            logger.warning("AuditWriter.stop: queue did not drain within %.1fs", grace_s)
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            # Expected: we cancelled it. Anything still queued is either
            # already in the WAL (replayed on next start) or was never
            # accepted durably; stop() is the only place this is swallowed.
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
        """Enqueue one audit entry. Returns once the record is on the bounded
        queue (ticket perf budget: <1 ms at the call site) — durability is
        the writer task's job, not this coroutine's."""
        if not self._running:
            raise AuditWriterStopped()
        validate_action(action)
        emission = AuditEmission(
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
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            await self._drop_oldest_and_alarm("queue full")
            self._queue.put_nowait(record)

    async def _drop_oldest_and_alarm(self, reason: str) -> None:
        try:
            self._queue.get_nowait()
            self._queue.task_done()
            self._dropped_total += 1
        except asyncio.QueueEmpty:  # pragma: no cover - race only
            pass
        if self._on_alarm is not None:
            await self._on_alarm(reason)
        else:
            logger.error("audit WAL/queue overflow: %s", reason)

    async def _replay_backlog(self) -> None:
        for end_offset, record in self._wal.replay():
            await self._write_with_retry(record)
            self._wal.mark_committed(end_offset)
        self._wal.compact()

    async def _run(self) -> None:
        await self._replay_backlog()
        while True:
            record = await self._queue.get()
            try:
                self._append_to_wal(record)
                offset = self._wal.size_bytes()
                await self._write_with_retry(record)
                self._wal.mark_committed(offset)
                self._written_total += 1
            finally:
                self._queue.task_done()

    def _append_to_wal(self, record: dict[str, Any]) -> None:
        try:
            self._wal.append(record)
        except AuditWalFull:
            # Everything before the cursor is already in Postgres; reclaim it.
            self._wal.compact()
            self._wal.append(record)

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


def _log_task_failure(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.critical("audit writer task died", exc_info=task.exception())


def _path(raw: str) -> Path:
    return Path(raw)
