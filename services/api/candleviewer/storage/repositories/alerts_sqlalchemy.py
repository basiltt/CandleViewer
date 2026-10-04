# ruff: noqa: S608 -- f-strings splice only module-level constant column lists; all values are bound params
"""Postgres repository for alerts (migration `0014_alerts`, E40-T01).

Lives in M10 (`storage`): only M10 may import a storage driver (ADR-0003) and M10
may not import `candleviewer.alerts` (M22), so this module returns plain frozen
dataclasses. `webhook_url_enc` / `webhook_secret_enc` are SECRET: the read path
selects an explicit column allow-list (`ALERT_COLUMNS`) that never contains them.
Cursor pagination is keyset (opaque base64 of `(ts, id)`), never OFFSET.
Static, parameterised SQL only. Deliveries: `alert_deliveries_sqlalchemy.py`.
"""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

#: Explicit read allow-list: the SECRET `webhook_*_enc` columns are deliberately absent.
ALERT_COLUMNS = (
    "id::text AS id, owner_user_id::text AS owner_user_id, name, symbol, "
    "scope_account_id::text AS scope_account_id, condition_ir, "
    "condition_hash::text AS condition_hash, enabled, trigger_mode::text AS trigger_mode, "
    "cooldown_seconds, snoozed_until, expires_at, severity::text AS severity, "
    "channels::text[] AS channels, (webhook_url_enc IS NOT NULL) AS has_webhook, "
    "message_template, last_fired_at, fire_count, created_at, updated_at"
)


class AlertConflictError(Exception):
    """Optimistic-concurrency failure: `updated_at` no longer matches (HTTP 412)."""


@dataclass(frozen=True, slots=True)
class AlertRow:
    id: str
    owner_user_id: str
    name: str
    symbol: str | None
    scope_account_id: str | None
    condition_ir: dict[str, Any]
    condition_hash: str
    enabled: bool
    trigger_mode: str
    cooldown_seconds: int
    snoozed_until: datetime | None
    expires_at: datetime | None
    severity: str
    channels: tuple[str, ...]
    has_webhook: bool
    message_template: str
    last_fired_at: datetime | None
    fire_count: int
    created_at: datetime
    updated_at: datetime

    @property
    def etag(self) -> str:
        return self.updated_at.isoformat()


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: list[T]
    next_cursor: str | None


def encode_cursor(ts: datetime, row_id: int | str) -> str:
    raw = json.dumps([ts.isoformat(), str(row_id)]).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        ts, rid = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(ts), str(rid)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid cursor") from exc


def array_literal(values: tuple[str, ...]) -> str:
    """Postgres array literal for `alert_channel[]` (values are enum words, never user text)."""
    return "{" + ",".join(values) + "}"


def _alert(m: Any) -> AlertRow:
    d = dict(m)
    d["channels"] = tuple(d["channels"])
    return AlertRow(**d)


# nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
_INSERT = sa.text(
    "INSERT INTO alerts (id, owner_user_id, name, symbol, scope_account_id, condition_ir, "  # nosec B608 - static column constants, bound params
    "condition_hash, enabled, trigger_mode, cooldown_seconds, expires_at, severity, channels, "
    "webhook_url_enc, webhook_secret_enc, message_template) VALUES (CAST(:id AS uuid), "
    "CAST(:owner AS uuid), :name, :symbol, CAST(:account AS uuid), CAST(:ir AS jsonb), :hash, "
    ":enabled, CAST(:mode AS alert_trigger_mode), :cooldown, :expires_at, "
    "CAST(:severity AS severity), CAST(:channels AS alert_channel[]), :url_enc, :secret_enc, "
    f":template) RETURNING {ALERT_COLUMNS}"
)
# nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
_GET = sa.text(
    f"SELECT {ALERT_COLUMNS} FROM alerts WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL"  # nosec B608 - static column constants, bound params
)
# nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
_LIST = sa.text(
    f"SELECT {ALERT_COLUMNS} FROM alerts WHERE owner_user_id = CAST(:owner AS uuid) "  # nosec B608 - static column constants, bound params
    "AND deleted_at IS NULL AND (CAST(:after_ts AS timestamptz) IS NULL OR "
    "(created_at, id::text) < (CAST(:after_ts AS timestamptz), :after_id)) "
    "ORDER BY created_at DESC, id::text DESC LIMIT :limit"
)
# nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
_UPDATE = sa.text(
    "UPDATE alerts SET name = :name, condition_ir = CAST(:ir AS jsonb), condition_hash = :hash, "  # nosec B608 - static column constants, bound params
    "trigger_mode = CAST(:mode AS alert_trigger_mode), cooldown_seconds = :cooldown, "
    "expires_at = :expires_at, severity = CAST(:severity AS severity), "
    "channels = CAST(:channels AS alert_channel[]), message_template = :template, "
    "updated_at = clock_timestamp() WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL "
    f"AND updated_at = :if_match RETURNING {ALERT_COLUMNS}"
)
# nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
_SOFT_DELETE = sa.text(
    "UPDATE alerts SET deleted_at = now(), enabled = false, updated_at = clock_timestamp() "
    "WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL"
)
# nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
_SET_ENABLED = sa.text(
    "UPDATE alerts SET enabled = :enabled, updated_at = clock_timestamp() "  # nosec B608 - static column constants, bound params
    f"WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL RETURNING {ALERT_COLUMNS}"
)
# nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
_SET_SNOOZE = sa.text(
    "UPDATE alerts SET snoozed_until = :until, updated_at = clock_timestamp() "  # nosec B608 - static column constants, bound params
    f"WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL RETURNING {ALERT_COLUMNS}"
)
# nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
_BUMP = sa.text(
    "UPDATE alerts SET fire_count = fire_count + 1, last_fired_at = :fired_at "
    "WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL"
)
# nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
_ARMED = sa.text(
    f"SELECT {ALERT_COLUMNS} FROM alerts WHERE symbol = :symbol AND enabled AND deleted_at IS NULL"  # nosec B608 - static column constants, bound params
)
# nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
_COUNT_ENABLED = sa.text(
    "SELECT enabled, count(*) AS n FROM alerts WHERE deleted_at IS NULL GROUP BY enabled"
)
_COUNT_PENDING = sa.text("SELECT count(*) FROM alert_deliveries WHERE status = 'queued'")


class SqlAlchemyAlertRepository:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def create(
        self,
        *,
        owner_user_id: str,
        name: str,
        condition_ir: dict[str, Any],
        condition_hash: str,
        symbol: str | None = None,
        scope_account_id: str | None = None,
        enabled: bool = True,
        trigger_mode: str = "once",
        cooldown_seconds: int = 60,
        expires_at: datetime | None = None,
        severity: str = "info",
        channels: tuple[str, ...] = ("in_app",),
        webhook_url_enc: bytes | None = None,
        webhook_secret_enc: bytes | None = None,
        message_template: str = "",
    ) -> AlertRow:
        params: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "owner": owner_user_id,
            "name": name,
            "symbol": symbol,
            "account": scope_account_id,
            "ir": json.dumps(condition_ir, sort_keys=True),
            "hash": condition_hash,
            "enabled": enabled,
            "mode": trigger_mode,
            "cooldown": cooldown_seconds,
            "expires_at": expires_at,
            "severity": severity,
            "channels": array_literal(channels),
            "url_enc": webhook_url_enc,
            "secret_enc": webhook_secret_enc,
            "template": message_template,
        }
        async with self._relational.unit_of_work() as uow:
            row = (await uow.session.execute(_INSERT, params)).mappings().one()
            await uow.commit()
        return _alert(row)

    async def get(self, alert_id: str) -> AlertRow | None:
        async with self._relational.unit_of_work() as uow:
            row = (await uow.session.execute(_GET, {"id": alert_id})).mappings().first()
        return None if row is None else _alert(row)

    async def list_page(
        self, owner_user_id: str, *, cursor: str | None = None, limit: int = 50
    ) -> Page[AlertRow]:
        after_ts, after_id = decode_cursor(cursor) if cursor else (None, None)
        params: dict[str, Any] = {
            "owner": owner_user_id,
            "after_ts": after_ts,
            "after_id": after_id,
            "limit": limit + 1,
        }
        async with self._relational.unit_of_work() as uow:
            rows = [_alert(r) for r in (await uow.session.execute(_LIST, params)).mappings()]
        more = len(rows) > limit
        rows = rows[:limit]
        nxt = encode_cursor(rows[-1].created_at, rows[-1].id) if more and rows else None
        return Page(rows, nxt)

    async def update(
        self,
        alert_id: str,
        *,
        if_match: datetime,
        name: str,
        condition_ir: dict[str, Any],
        condition_hash: str,
        trigger_mode: str,
        cooldown_seconds: int,
        expires_at: datetime | None,
        severity: str,
        channels: tuple[str, ...],
        message_template: str,
    ) -> AlertRow:
        """Optimistic concurrency: `if_match` is the `updated_at` the caller read."""
        params: dict[str, Any] = {
            "id": alert_id,
            "if_match": if_match,
            "name": name,
            "ir": json.dumps(condition_ir, sort_keys=True),
            "hash": condition_hash,
            "mode": trigger_mode,
            "cooldown": cooldown_seconds,
            "expires_at": expires_at,
            "severity": severity,
            "channels": array_literal(channels),
            "template": message_template,
        }
        async with self._relational.unit_of_work() as uow:
            row = (await uow.session.execute(_UPDATE, params)).mappings().first()
            await uow.commit()
        if row is None:
            raise AlertConflictError(alert_id)
        return _alert(row)

    async def soft_delete(self, alert_id: str) -> bool:
        async with self._relational.unit_of_work() as uow:
            res = await uow.session.execute(_SOFT_DELETE, {"id": alert_id})
            await uow.commit()
        return bool(getattr(res, "rowcount", 0))

    async def set_enabled(self, alert_id: str, enabled: bool) -> AlertRow | None:
        return await self._one(_SET_ENABLED, {"id": alert_id, "enabled": enabled})

    async def set_snooze(self, alert_id: str, until: datetime | None) -> AlertRow | None:
        return await self._one(_SET_SNOOZE, {"id": alert_id, "until": until})

    async def bump_fire_counters(self, alert_id: str, fired_at: datetime) -> None:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(_BUMP, {"id": alert_id, "fired_at": fired_at})
            await uow.commit()

    async def load_armed(self, symbol: str) -> list[AlertRow]:
        """Evaluator warm-up query; served by partial index `ix_alerts_live`."""
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(_ARMED, {"symbol": symbol})).mappings()
            return [_alert(r) for r in rows]

    async def gauges(self) -> dict[str, int]:
        """Source for `cv_alerts_total{enabled}` and `cv_alert_deliveries_pending`."""
        async with self._relational.unit_of_work() as uow:
            by_enabled = (await uow.session.execute(_COUNT_ENABLED)).mappings().all()
            pending = int((await uow.session.execute(_COUNT_PENDING)).scalar_one())
        counts = {bool(r["enabled"]): int(r["n"]) for r in by_enabled}
        return {
            "cv_alerts_total{enabled=true}": counts.get(True, 0),
            "cv_alerts_total{enabled=false}": counts.get(False, 0),
            "cv_alert_deliveries_pending": pending,
        }

    async def _one(self, stmt: sa.TextClause, params: dict[str, Any]) -> AlertRow | None:
        async with self._relational.unit_of_work() as uow:
            row = (await uow.session.execute(stmt, params)).mappings().first()
            await uow.commit()
        return None if row is None else _alert(row)
