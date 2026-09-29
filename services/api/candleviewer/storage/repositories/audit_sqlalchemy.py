"""`SqlAlchemyAuditRepository` — the concrete Postgres implementation of
`candleviewer.audit.repository.AuditRepository` (E09-T02).

Lives in M10 (`storage`, allowed to import `sqlalchemy`) so `candleviewer.audit`
never imports a storage driver directly (CONSTITUTION.md ADR-0003, C-3.1).
Structurally compatible with the `AuditRepository` Protocol without importing
`candleviewer.audit` — the composition root injects it into `AuditService(repository=...)`;
neither module imports the other.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import sqlalchemy as sa

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_ADVISORY_LOCK_SQL = sa.text("SELECT pg_advisory_xact_lock(hashtext('audit_log'))")

_INSERT_SQL = sa.text("""
    INSERT INTO audit_log
        (actor_user_id, actor_label, actor_ip, session_id, action, object_kind,
         object_id, object_label, outcome, severity, reason, before_state,
         after_state, request_id, env, event_ts)
    VALUES
        (:actor_user_id, :actor_label, :actor_ip, :session_id, :action, :object_kind,
         :object_id, :object_label, :outcome, :severity, :reason,
         CAST(:before_state AS jsonb), CAST(:after_state AS jsonb), :request_id, :env, :event_ts)
    """)

_HEAD_SQL = sa.text("SELECT id, entry_hash FROM audit_log ORDER BY id DESC LIMIT 1")
_COUNT_SQL = sa.text("SELECT count(*) FROM audit_log")
_ENTRY_HASH_SQL = sa.text("SELECT entry_hash FROM audit_log WHERE id = :id")

#: Every hashed column is rendered to text *by Postgres*, with exactly the
#: casts `audit_chain()` uses, so the Python verifier concatenates the same
#: bytes the trigger hashed (driver-side types — `IPv4Address`, decoded
#: jsonb dicts, tz-aware datetimes — would not round-trip byte-exactly).
_VERIFY_COLUMNS = (
    "id, prev_hash, entry_hash, actor_user_id::text AS actor_user_id, actor_label, "
    "actor_ip::text AS actor_ip, session_id::text AS session_id, action, object_kind, "
    "object_id, outcome::text AS outcome, severity::text AS severity, reason, "
    "before_state::text AS before_state, after_state::text AS after_state, "
    "request_id::text AS request_id, env::text AS env, "
    "to_char(event_ts AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.USOF') AS event_ts"
)

_QUERY_COLUMNS = (
    "id, event_ts, actor_user_id, action, object_kind, object_id, outcome, "
    "severity, actor_ip, request_id, entry_hash, prev_hash"
)

_INSERT_CHECKPOINT_SQL = sa.text("""
    INSERT INTO audit_checkpoints (id, head_id, head_hash, row_count, signed_by)
    VALUES (:id, :head_id, :head_hash, :row_count, :signed_by)
    ON CONFLICT (head_id) DO NOTHING
    """)


def _json_or_null(value: dict[str, Any] | None) -> str | None:
    """SQL NULL for an absent state — never the JSON literal `null`, which
    the chain trigger would hash as the 4-char text `null`."""
    return None if value is None else json.dumps(value, sort_keys=True)


class SqlAlchemyAuditRepository:
    """Backs `AuditWriter`/`AuditQueryService`/`checkpoint.run_checkpoint`.

    Constructed directly from a `SqlAlchemyRelationalRepository` (the same
    relational-tier client `StorageService` wires for every other module) —
    The composition root constructs it and injects it into `AuditService`.
    """

    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def insert(self, record: dict[str, Any]) -> None:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(_ADVISORY_LOCK_SQL)
            await uow.session.execute(
                _INSERT_SQL,
                {
                    "actor_user_id": record.get("actor_user_id"),
                    "actor_label": record["actor_label"],
                    "actor_ip": record.get("actor_ip"),
                    "session_id": record.get("session_id"),
                    "action": record["action"],
                    "object_kind": record.get("object_kind"),
                    "object_id": record.get("object_id"),
                    "object_label": record.get("object_label"),
                    "outcome": record["outcome"],
                    "severity": record["severity"],
                    "reason": record.get("reason"),
                    "before_state": _json_or_null(record.get("before_state")),
                    "after_state": _json_or_null(record.get("after_state")),
                    "request_id": record.get("request_id"),
                    "env": record.get("env"),
                    "event_ts": datetime.fromisoformat(record["event_ts"]),
                },
            )
            await uow.commit()

    async def query_page(
        self,
        *,
        actor_user_id: str | None,
        actions: list[str] | None,
        severity: str | None,
        outcome: str | None,
        from_ts: datetime | None,
        to_ts: datetime | None,
        cursor: int | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        clauses = ["1=1"]
        params: dict[str, Any] = {"limit": limit}
        if actor_user_id is not None:
            clauses.append("actor_user_id = :actor_user_id")
            params["actor_user_id"] = actor_user_id
        if actions:
            clauses.append("action = ANY(:actions)")
            params["actions"] = actions
        if severity is not None:
            clauses.append("severity = :severity")
            params["severity"] = severity
        if outcome is not None:
            clauses.append("outcome = :outcome")
            params["outcome"] = outcome
        if from_ts is not None:
            clauses.append("event_ts >= :from_ts")
            params["from_ts"] = from_ts
        if to_ts is not None:
            clauses.append("event_ts <= :to_ts")
            params["to_ts"] = to_ts
        if cursor is not None:
            clauses.append("id < :cursor")
            params["cursor"] = cursor

        sql = sa.text(f"""
            SELECT {_QUERY_COLUMNS}
            FROM audit_log
            WHERE {" AND ".join(clauses)}
            ORDER BY id DESC
            LIMIT :limit
            """)  # noqa: S608 - clauses/columns are fixed constants, values are bound params
        async with self._relational.unit_of_work() as uow:
            result = await uow.session.execute(sql, params)
            return [dict(row._mapping) for row in result]

    async def fetch_entry_hash(self, entry_id: int) -> str | None:
        async with self._relational.unit_of_work() as uow:
            row = (await uow.session.execute(_ENTRY_HASH_SQL, {"id": entry_id})).first()
            return row[0] if row is not None else None

    async def fetch_verify_batch(
        self, *, after_id: int, to_id: int | None, limit: int
    ) -> list[dict[str, Any]]:
        clauses = ["id > :after_id"]
        params: dict[str, Any] = {"after_id": after_id, "limit": limit}
        if to_id is not None:
            clauses.append("id <= :to_id")
            params["to_id"] = to_id
        sql = sa.text(f"""
            SELECT {_VERIFY_COLUMNS}
            FROM audit_log
            WHERE {" AND ".join(clauses)}
            ORDER BY id ASC
            LIMIT :limit
            """)  # noqa: S608 - clauses/columns are fixed constants, values are bound params
        async with self._relational.unit_of_work() as uow:
            result = await uow.session.execute(sql, params)
            return [dict(row._mapping) for row in result]

    async def read_head(self) -> tuple[int, str] | None:
        async with self._relational.unit_of_work() as uow:
            row = (await uow.session.execute(_HEAD_SQL)).first()
            return (row[0], row[1]) if row is not None else None

    async def count(self) -> int:
        async with self._relational.unit_of_work() as uow:
            return int((await uow.session.execute(_COUNT_SQL)).scalar_one())

    async def write_checkpoint(
        self, *, checkpoint_id: str, head_id: int, head_hash: str, row_count: int, signed_by: str
    ) -> None:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(
                _INSERT_CHECKPOINT_SQL,
                {
                    "id": checkpoint_id,
                    "head_id": head_id,
                    "head_hash": head_hash,
                    "row_count": row_count,
                    "signed_by": signed_by,
                },
            )
            await uow.commit()
