"""The alert firing transaction (E40-T03; 21-database-schema.md §3.10.4).

`record_firing` commits the `alert_deliveries` row(s), the `outbox` row(s) and the
`alerts` counter / `enabled` updates in ONE unit of work, so a crash between "decide"
and "send" can neither lose nor duplicate a delivery: either every row exists (and the
E40-T04 poller delivers the pending outbox row exactly once, `ux_outbox_dedup`) or none.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa

from candleviewer.storage.repositories.alerts import AlertRow
from candleviewer.storage.repositories.alerts_sqlalchemy import ALERT_COLUMNS, _alert
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

# Only the static column allow-list is substituted, never caller data.
_LIVE = sa.text(
    "SELECT @C@ FROM alerts WHERE enabled AND deleted_at IS NULL".replace("@C@", ALERT_COLUMNS)
)
_GET = sa.text(
    "SELECT @C@ FROM alerts WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL".replace(
        "@C@", ALERT_COLUMNS
    )
)
#: Conditional disarm: zero rows => another worker already fired this `once` alert.
_DISARM_ONCE = sa.text(
    "UPDATE alerts SET enabled = false, updated_at = clock_timestamp() "
    "WHERE id = CAST(:id AS uuid) AND enabled AND deleted_at IS NULL"
)
_DISARM = sa.text(
    "UPDATE alerts SET enabled = false, updated_at = clock_timestamp() "
    "WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL"
)
_BUMP = sa.text(
    "UPDATE alerts SET fire_count = fire_count + 1, last_fired_at = :fired_at "
    "WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL"
)
_INSERT_DELIVERY = sa.text(
    "INSERT INTO alert_deliveries (alert_id, user_id, channel, status, title, body, context, "
    "error_message) VALUES (CAST(:alert_id AS uuid), CAST(:user_id AS uuid), "
    "CAST(:channel AS alert_channel), CAST(:status AS delivery_status), :title, :body, "
    "CAST(:context AS jsonb), :error) RETURNING id"
)
_INSERT_OUTBOX = sa.text(
    "INSERT INTO outbox (topic, dedup_key, payload) VALUES (:topic, :dedup, "
    "CAST(:payload AS jsonb)) ON CONFLICT (topic, dedup_key) DO NOTHING"
)


class SqlAlchemyAlertFiringStore:
    """`alerts.ports.FiringStore` over Postgres."""

    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        *,
        topic: str,
        dedup_key: Callable[[int], str],
    ) -> None:
        """`topic`/`dedup_key` come from `alerts.outbox` (M10 may not import M22)."""
        self._relational, self._topic, self._dedup = relational, topic, dedup_key

    async def load_live(self) -> list[AlertRow]:
        async with self._relational.unit_of_work() as uow:
            return [_alert(m) for m in (await uow.session.execute(_LIVE)).mappings()]

    async def get(self, alert_id: str) -> AlertRow | None:
        async with self._relational.unit_of_work() as uow:
            m = (await uow.session.execute(_GET, {"id": alert_id})).mappings().first()
        return None if m is None else _alert(m)

    async def record_firing(
        self,
        *,
        alert_id: str,
        user_id: str,
        channels: Sequence[str],
        status: str,
        title: str,
        body: str,
        context: dict[str, Any],
        fired_at: datetime,
        once: bool,
        bump: bool,
        disable: bool = False,
    ) -> list[int] | None:
        ids: list[int] = []
        async with self._relational.unit_of_work() as uow:
            run = uow.session.execute
            if once:
                res = await run(_DISARM_ONCE, {"id": alert_id})
                if not int(getattr(res, "rowcount", 0) or 0):
                    return None  # lost the race; nothing committed
            elif disable:
                await run(_DISARM, {"id": alert_id})
            if bump:
                await run(_BUMP, {"id": alert_id, "fired_at": fired_at})
            ctx_json = json.dumps(context, sort_keys=True, default=str)
            for ch in channels:
                row = await run(_INSERT_DELIVERY, {
                    "alert_id": alert_id, "user_id": user_id, "channel": ch, "status": status,
                    "title": title, "body": body, "context": ctx_json,
                    "error": "storm" if status == "suppressed" else None,
                })  # fmt: skip
                did = int(row.scalar_one())
                ids.append(did)
                if status == "queued":
                    await run(_INSERT_OUTBOX, {
                        "topic": self._topic, "dedup": self._dedup(did),
                        "payload": json.dumps({"delivery_id": did, "alert_id": alert_id,
                                               "channel": ch}),
                    })  # fmt: skip
            await uow.commit()
        return ids
