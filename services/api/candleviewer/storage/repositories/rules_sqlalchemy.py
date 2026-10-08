"""`SqlAlchemyRulesRepository` - Postgres persistence for rule versions and the
retention job (migration `0013_rules`, E35-T02).

Lives in M10 (`storage`): only M10 may import a storage driver (ADR-0003) and
M10 may not import `candleviewer.rules`, so the caller (M15) computes the
canonical `ir_hash` with `candleviewer.rules.ir.ir_hash` *before* insert and
passes it in. The stored hash is authoritative: it is never recomputed from the
jsonb column on read (Postgres reorders jsonb keys). Static, parameterised SQL.

`rule_runs.input_snapshot` is financial/confidential (equity, PnL, size): this
module never logs it. `prune_unmatched` deletes only unmatched, non-error `rule_runs`; their events
go via the FK cascade, which `rule_events_forbid_mutation()` permits only when
the parent run is gone. No role can update or directly delete a rule event.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
import structlog

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


#: Non-matched runs (and, by cascade, their events) are dropped after this many days.
UNMATCHED_RETENTION_DAYS = 7
#: Matched runs are archived to Parquet (E16 cold path), then dropped after this many months.
MATCHED_RETENTION_MONTHS = 24

_SELECT_BY_HASH = sa.text(
    "SELECT id::text AS id, version, ir_hash::text AS ir_hash FROM rule_versions "
    "WHERE rule_id = CAST(:rule_id AS uuid) AND ir_hash = :ir_hash"
)
_INSERT_VERSION = sa.text(
    "INSERT INTO rule_versions (id, rule_id, version, ir, ir_hash, compiler_version, "
    "notes, is_valid, created_by) VALUES (CAST(:id AS uuid), CAST(:rule_id AS uuid), "
    "(SELECT COALESCE(MAX(version), 0) + 1 FROM rule_versions "
    "WHERE rule_id = CAST(:rule_id AS uuid)), CAST(:ir AS jsonb), :ir_hash, "
    ":compiler_version, :notes, :is_valid, CAST(:created_by AS uuid)) "
    "ON CONFLICT (rule_id, ir_hash) DO NOTHING RETURNING id::text AS id, version, "
    "ir_hash::text AS ir_hash"
)
_LOCK_RULE = sa.text("SELECT 1 FROM rules WHERE id = CAST(:rule_id AS uuid) FOR UPDATE")
_INSERT_RUN = sa.text(
    "INSERT INTO rule_runs (id, rule_id, rule_version_id, status, mode, trigger_reason, "
    "scope_symbol, input_snapshot, matched, error_code, error_message, duration_ms) "
    "VALUES (CAST(:id AS uuid), CAST(:rule_id AS uuid), CAST(:version_id AS uuid), "
    "CAST(:status AS rule_run_status), CAST(:mode AS rule_mode), :trigger, :symbol, "
    "CAST(:snapshot AS jsonb), :matched, :error_code, :error_message, :duration_ms)"
)
_PRUNE = sa.text(
    "DELETE FROM rule_runs WHERE NOT matched AND status <> 'error' "
    "AND started_at < now() - make_interval(days => :days)"
)


@dataclass(frozen=True, slots=True)
class RuleVersionRow:
    id: str
    version: int
    ir_hash: str
    created: bool


@dataclass(frozen=True, slots=True)
class PruneResult:
    runs_deleted: int
    duration_ms: int


def persist_reason(*, matched: bool, status: str, mode: str, record_all: bool) -> str | None:
    """Why a run must be persisted, or None when it is counted in Prometheus only."""
    if matched:
        return "matched"
    if status == "error":
        return "error"
    if record_all and mode == "simulate":
        return "record_all"
    return None


class SqlAlchemyRulesRepository:
    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        *,
        on_persisted: Callable[[str], None] | None = None,
        on_pruned: Callable[[int], None] | None = None,
    ) -> None:
        """`on_persisted(reason)` / `on_pruned(n)` feed
        `rule_runs_persisted_total{reason}` / `rule_runs_pruned_total`."""
        self._relational = relational
        self._on_persisted = on_persisted
        self._on_pruned = on_pruned

    async def save_version(
        self,
        rule_id: str,
        ir: dict[str, Any],
        ir_hash: str,
        *,
        compiler_version: str,
        created_by: str | None = None,
        notes: str = "",
        is_valid: bool = True,
    ) -> RuleVersionRow:
        """Insert a version, or return the existing one for the same `(rule, ir_hash)`."""
        params: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "rule_id": rule_id,
            "ir": json.dumps(ir, sort_keys=True),
            "ir_hash": ir_hash,
            "compiler_version": compiler_version,
            "notes": notes,
            "is_valid": is_valid,
            "created_by": created_by,
        }
        async with self._relational.unit_of_work() as uow:
            # Serialise version numbering per rule.
            await uow.session.execute(_LOCK_RULE, {"rule_id": rule_id})
            row = (await uow.session.execute(_INSERT_VERSION, params)).mappings().first()
            created = row is not None
            if row is None:
                row = (await uow.session.execute(_SELECT_BY_HASH, params)).mappings().one()
            await uow.commit()
        return RuleVersionRow(str(row["id"]), int(row["version"]), str(row["ir_hash"]), created)

    async def record_run(
        self,
        *,
        rule_id: str,
        version_id: str,
        mode: str,
        trigger_reason: str,
        input_snapshot: dict[str, Any],
        status: str,
        matched: bool,
        record_all: bool = False,
        symbol: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        duration_ms: int | None = None,
    ) -> str | None:
        """Persist a run only when matched, errored, or simulate+`record_all`.

        Returns the run id, or None when the evaluation is not persisted
        (the caller then counts it in Prometheus only).
        """
        reason = persist_reason(matched=matched, status=status, mode=mode, record_all=record_all)
        if reason is None:
            return None
        run_id = str(uuid.uuid4())
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(
                _INSERT_RUN,
                {
                    "id": run_id,
                    "rule_id": rule_id,
                    "version_id": version_id,
                    "status": status,
                    "mode": mode,
                    "trigger": trigger_reason,
                    "symbol": symbol,
                    "snapshot": json.dumps(input_snapshot, sort_keys=True),
                    "matched": matched,
                    "error_code": error_code,
                    "error_message": error_message,
                    "duration_ms": duration_ms,
                },
            )
            await uow.commit()
        if self._on_persisted is not None:
            self._on_persisted(reason)
        return run_id

    async def prune_unmatched(self, days: int = UNMATCHED_RETENTION_DAYS) -> PruneResult:
        """Delete non-matched, non-error runs older than `days` (events cascade).

        Error runs are deliberately kept (schema doc 3.4.3): evidence, low volume.
        """
        started = time.monotonic()
        async with self._relational.unit_of_work() as uow:
            result = await uow.session.execute(_PRUNE, {"days": days})
            deleted = int(getattr(result, "rowcount", 0) or 0)
            await uow.commit()
        elapsed = int((time.monotonic() - started) * 1000)
        if self._on_pruned is not None:
            self._on_pruned(deleted)
        _log().info("rule_runs retention pruned", deleted=deleted, duration_ms=elapsed)
        return PruneResult(deleted, elapsed)
