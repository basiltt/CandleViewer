"""`SqlAlchemyInstrumentsRepository` — Postgres persistence for the instrument
catalogue (`instruments` + append-only `instrument_versions`, migration
`0004_instruments`; E08-S01-2).

Lives in M10 (`storage`, may depend on M1 only — C-3.1), so it never imports
the domain `Instrument` model or anything in `ingestion`. Rows cross the
boundary as the JSON-mode mapping `Instrument.model_dump(mode="json")`; the
ingestion scheduler re-validates on load. It is structurally compatible with
`candleviewer.ingestion.instruments_refresh.InstrumentsRepositoryLike` and
is injected by the composition root.

`raw` stores that full neutral mapping so `load_all()` is lossless (every
model field round-trips, including ones without a dedicated column); the
typed columns exist for SQL-side filtering and the version history.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_UPSERT_SQL = sa.text("""
    INSERT INTO instruments
        (symbol, category, base_coin, quote_coin, settle_coin, status, tick_size, qty_step,
         min_order_qty, max_order_qty, min_notional_value, max_leverage, leverage_step,
         price_scale, funding_interval_min, launch_ts, metadata_version, raw, refreshed_at,
         stale_since)
    VALUES
        (:symbol, 'linear', :base_coin, :quote_coin, :settle_coin, :status, :tick_size,
         :qty_step, :min_order_qty, :max_order_qty, :min_notional_value, :max_leverage,
         :leverage_step, :price_scale, :funding_interval_min, :launch_ts, :metadata_version,
         CAST(:raw AS jsonb), :refreshed_at, NULL)
    ON CONFLICT (symbol) DO UPDATE SET
        base_coin = EXCLUDED.base_coin, quote_coin = EXCLUDED.quote_coin,
        settle_coin = EXCLUDED.settle_coin, status = EXCLUDED.status,
        tick_size = EXCLUDED.tick_size, qty_step = EXCLUDED.qty_step,
        min_order_qty = EXCLUDED.min_order_qty, max_order_qty = EXCLUDED.max_order_qty,
        min_notional_value = EXCLUDED.min_notional_value,
        max_leverage = EXCLUDED.max_leverage, leverage_step = EXCLUDED.leverage_step,
        price_scale = EXCLUDED.price_scale,
        funding_interval_min = EXCLUDED.funding_interval_min,
        launch_ts = EXCLUDED.launch_ts, metadata_version = EXCLUDED.metadata_version,
        raw = EXCLUDED.raw, refreshed_at = EXCLUDED.refreshed_at, stale_since = NULL
    """)

_VERSION_SQL = sa.text("""
    INSERT INTO instrument_versions
        (symbol, metadata_version, tick_size, qty_step, min_order_qty, max_order_qty,
         min_notional_value, max_leverage, leverage_step, price_scale, funding_interval_min,
         status, changed_fields, raw)
    VALUES
        (:symbol, :metadata_version, :tick_size, :qty_step, :min_order_qty, :max_order_qty,
         :min_notional_value, :max_leverage, :leverage_step, :price_scale,
         :funding_interval_min, :status, :changed_fields, CAST(:raw AS jsonb))
    ON CONFLICT (symbol, metadata_version) DO NOTHING
    """)

_MARK_STALE_SQL = sa.text(
    "UPDATE instruments SET stale_since = :stale_since WHERE stale_since IS NULL"
)
_LOAD_ALL_SQL = sa.text("SELECT raw FROM instruments ORDER BY symbol")

#: `instrument_versions.symbol` references `instruments(symbol)`; a brand-new
#: symbol's parent row must exist first. `record_version` upserts it via the
#: same statement so version-before-snapshot ordering is always safe.


def _ts(us: Any) -> datetime | None:
    if us is None:
        return None
    return datetime.fromtimestamp(int(us) / 1_000_000, tz=UTC)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def _params(row: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    min_notional = row.get("min_notional")
    return {
        "symbol": row["symbol"],
        "base_coin": row.get("base_coin", ""),
        "quote_coin": row.get("quote_coin", "USDT"),
        "settle_coin": row.get("settle_coin", "USDT"),
        "status": row["status"],
        "tick_size": _dec(row["tick_size"]),
        "qty_step": _dec(row["qty_step"]),
        "min_order_qty": _dec(row["min_order_qty"]),
        "max_order_qty": _dec(row["max_order_qty"]),
        "min_notional_value": _dec(min_notional) if min_notional is not None else None,
        "max_leverage": _dec(row["max_leverage"]),
        "leverage_step": _dec(row["leverage_step"]),
        "price_scale": int(row["price_scale"]),
        "funding_interval_min": int(row["funding_interval_min"]),
        "launch_ts": _ts(row.get("launch_time")),
        "metadata_version": int(row["metadata_version"]),
        "raw": json.dumps(dict(row), sort_keys=True),
        "refreshed_at": _ts(row.get("fetched_at")) or now,
    }


class SqlAlchemyInstrumentsRepository:
    """Concrete instruments repository over `SqlAlchemyRelationalRepository`."""

    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def upsert_snapshot(self, rows: Sequence[Mapping[str, Any]]) -> None:
        """Upsert every row in one transaction and clear `stale_since`."""
        now = datetime.now(UTC)
        async with self._relational.unit_of_work() as uow:
            for row in rows:
                await uow.session.execute(_UPSERT_SQL, _params(row, now=now))
            await uow.commit()

    async def record_version(
        self, row: Mapping[str, Any], *, changed_fields: Sequence[str]
    ) -> None:
        """Append one `instrument_versions` row (idempotent per version)."""
        params = _params(row, now=datetime.now(UTC))
        params["changed_fields"] = list(changed_fields)
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(_UPSERT_SQL, params)
            await uow.session.execute(_VERSION_SQL, params)
            await uow.commit()

    async def mark_stale(self, *, stale_since_us: int) -> None:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(_MARK_STALE_SQL, {"stale_since": _ts(stale_since_us)})
            await uow.commit()

    async def load_all(self) -> Sequence[Mapping[str, Any]]:
        async with self._relational.unit_of_work() as uow:
            result = await uow.session.execute(_LOAD_ALL_SQL)
            out: list[Mapping[str, Any]] = []
            for (raw,) in result.all():
                out.append(json.loads(raw) if isinstance(raw, str) else dict(raw))
            return out


__all__ = ["SqlAlchemyInstrumentsRepository"]
