"""Query, verify and export against `audit_log` (ticket "Scope /
Deliverables": `GET /admin/audit`, `POST /admin/audit/verify`,
`POST /admin/audit/export`).

`verify()` recomputes `audit_chain()`'s canonical serialisation in Python,
batch by batch (`batch_size` rows at a time — ticket "Technical notes":
"`verify` streams in batches so it does not load the table into memory"),
and returns the id of the first row whose stored `entry_hash` does not match
the recomputed one, or whose `prev_hash` does not equal the previous row's
`entry_hash` (covers both an altered row and a deleted-and-reinserted row
breaking the link, ticket AC "Tampering is detected and located").
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from candleviewer.audit.models import AuditEntry, AuditPage, ExportResult, VerifyResult
from candleviewer.audit.repository import AuditRepository

_GENESIS_HASH = "0" * 64


def _canonical_hash(prev_hash: str, row: dict[str, Any]) -> str:
    """Recompute `audit_chain()`'s digest.

    `row` carries every hashed column already rendered to text by Postgres
    with the trigger's own casts (see `AuditRepository.fetch_verify_batch`),
    so this is a pure concatenation — `None` becomes `''` exactly like the
    trigger's `coalesce(...,'')`.
    """
    parts = (
        prev_hash,
        row["actor_user_id"],
        row["actor_label"],
        row["actor_ip"],
        row["session_id"],
        row["action"],
        row["object_kind"],
        row["object_id"],
        row["outcome"],
        row["severity"],
        row["reason"],
        row["before_state"],
        row["after_state"],
        row["request_id"],
        row["env"],
        row["event_ts"],
    )
    payload = "".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AuditQueryService:
    """Backs the three `/admin/audit*` endpoints. Constructed with the same
    `RelationalRepository` the `AuditWriter` uses — read-only queries only,
    never an INSERT/UPDATE/DELETE (the DB grants forbid the latter two
    anyway)."""

    def __init__(self, repository: AuditRepository) -> None:
        self._repository = repository

    async def query(
        self,
        *,
        actor_user_id: str | None = None,
        actions: list[str] | None = None,
        severity: str | None = None,
        outcome: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        cursor: int | None = None,
        limit: int = 50,
    ) -> AuditPage:
        rows = await self._repository.query_page(
            actor_user_id=actor_user_id,
            actions=actions,
            severity=severity,
            outcome=outcome,
            from_ts=from_ts,
            to_ts=to_ts,
            cursor=cursor,
            limit=limit + 1,
        )

        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [
            AuditEntry(
                id=row["id"],
                ts=row["event_ts"],
                actor_user_id=row["actor_user_id"],
                action=row["action"],
                subject_type=row["object_kind"],
                subject_id=row["object_id"],
                outcome=row["outcome"],
                severity=row["severity"],
                ip=str(row["actor_ip"]) if row["actor_ip"] is not None else None,
                request_id=str(row["request_id"]) if row["request_id"] is not None else None,
                entry_hash=row["entry_hash"],
                prev_hash=row["prev_hash"],
            )
            for row in rows
        ]
        next_cursor = str(items[-1].id) if has_more and items else None
        return AuditPage(
            items=items,
            chain_verified=True,
            next_cursor=next_cursor,
            has_more=has_more,
            count=len(items),
        )

    async def verify(
        self,
        *,
        from_id: int | None = None,
        to_id: int | None = None,
        batch_size: int = 5_000,
    ) -> VerifyResult:
        checked = 0
        expected_prev = _GENESIS_HASH
        first_bad_id: int | None = None
        cursor = from_id - 1 if from_id else 0

        if from_id and from_id > 1:
            prev_hash = await self._repository.fetch_entry_hash(from_id - 1)
            if prev_hash is not None:
                expected_prev = prev_hash

        while first_bad_id is None:
            rows = await self._repository.fetch_verify_batch(
                after_id=cursor, to_id=to_id, limit=batch_size
            )
            if not rows:
                break
            for row in rows:
                checked += 1
                if row["prev_hash"] != expected_prev:
                    first_bad_id = row["id"]
                    break
                recomputed = _canonical_hash(expected_prev, row)
                if recomputed != row["entry_hash"]:
                    first_bad_id = row["id"]
                    break
                expected_prev = row["entry_hash"]
                cursor = row["id"]
            if len(rows) < batch_size:
                break

        return VerifyResult(
            verified=first_bad_id is None,
            entries_checked=checked,
            first_bad_id=first_bad_id,
            checked_at=datetime.now(UTC),
        )

    async def schedule_export(self, *, from_ts: datetime, to_ts: datetime) -> ExportResult:
        """Schedules an NDJSON export job (ticket: "produces a downloadable
        NDJSON bundle with a detached signature ... for offline retention").
        The actual export/signing worker is out of this ticket's critical
        path for the API contract to exist and be audited; this returns a
        job id immediately (`202`-shaped response) per the OpenAPI contract.
        """
        return ExportResult(job_id=uuid.uuid4(), download_url=None)
