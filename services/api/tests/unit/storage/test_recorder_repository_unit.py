"""Unit tests for `SqlAlchemyRecorderRepository` using a recording fake unit of work (E16-T01).

SQL semantics (constraints, resolution order) are covered by the docker-backed
`tests/integration/storage/test_recorder_repository.py`; here we pin the
parameter plumbing and result mapping of every public method.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from candleviewer.storage.repositories.recorder_sqlalchemy import (
    HARD_DEFAULT_RETAIN_DAYS,
    SqlAlchemyRecorderRepository,
)


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _Result:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _Session:
    def __init__(self, owner: _Relational) -> None:
        self._owner = owner

    async def execute(self, stmt: Any, params: dict[str, Any]) -> _Result:
        self._owner.calls.append((str(stmt), params))
        return _Result(self._owner.rows)


class _Uow:
    def __init__(self, owner: _Relational) -> None:
        self.session = _Session(owner)

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None


class _Relational:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def unit_of_work(self) -> _Uow:
        return _Uow(self)


def _repo(
    rows: list[dict[str, Any]] | None = None,
) -> tuple[SqlAlchemyRecorderRepository, _Relational]:
    rel = _Relational(rows)
    return SqlAlchemyRecorderRepository(rel), rel  # type: ignore[arg-type]


async def test_list_and_get_pass_env() -> None:
    repo, rel = _repo([{"symbol": "BTCUSDT"}])
    assert await repo.list_recorded("live") == [{"symbol": "BTCUSDT"}]
    assert await repo.get_by_symbol("BTCUSDT", "live") == {"symbol": "BTCUSDT"}
    assert rel.calls[0][1] == {"env": "live"}
    assert rel.calls[1][1] == {"symbol": "BTCUSDT", "env": "live"}


async def test_get_by_symbol_none_when_absent() -> None:
    repo, _ = _repo([])
    assert await repo.get_by_symbol("ETHUSDT") is None


async def test_upsert_auto_serialises_ref_and_returns_id() -> None:
    repo, rel = _repo([{"id": "abc"}])
    got = await repo.upsert_auto("BTCUSDT", "chart_open", {"kind": "chart", "id": "c1"})
    assert got == "abc"
    assert json.loads(rel.calls[0][1]["ref"]) == {"kind": "chart", "id": "c1"}
    assert rel.calls[0][1]["reason"] == "chart_open"
    assert "ON CONFLICT" in rel.calls[0][0]


async def test_reason_ref_updates_are_single_statements() -> None:
    repo, rel = _repo([{"?column?": 1}])
    assert await repo.add_reason_ref("id1", {"kind": "chart", "id": "c1"}) is True
    assert await repo.remove_reason_ref("id1", {"kind": "chart", "id": "c1"}) is True
    assert len(rel.calls) == 2
    repo2, _ = _repo([])
    assert await repo2.add_reason_ref("x", {}) is False
    assert await repo2.remove_reason_ref("x", {}) is False


async def test_soft_remove_sets_removed_at_never_deletes() -> None:
    repo, rel = _repo([{"x": 1}])
    assert await repo.soft_remove("id1") is True
    sql = rel.calls[0][0]
    assert "removed_at = now()" in sql and "DELETE" not in sql.upper()


async def test_open_and_close_session() -> None:
    repo, rel = _repo([{"x": 1}])
    sid = await repo.open_session(
        recorded_symbol_id="rs1",
        symbol="BTCUSDT",
        streams=["trades", "tickers"],
        orderbook_depth=200,
        ws_endpoint="wss://example.invalid",
    )
    assert rel.calls[0][1]["streams"] == ["trades", "tickers"]
    assert rel.calls[0][1]["id"] == sid
    assert await repo.close_session(sid, "manual_stop") is True
    assert rel.calls[1][1] == {"id": sid, "reason": "manual_stop"}


async def test_record_gap_returns_id() -> None:
    repo, rel = _repo([{"id": 7}])
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
    gid = await repo.record_gap(
        session_id="s1",
        symbol="BTCUSDT",
        stream="trades",
        gap_start=t0,
        gap_end=t1,
        cause="ws_disconnect",
    )
    assert gid == 7
    assert rel.calls[0][1]["cause"] == "ws_disconnect"


@pytest.mark.parametrize(
    ("rows", "expected"),
    [([], HARD_DEFAULT_RETAIN_DAYS), ([{"retain_days": 3}], 3), ([{"retain_days": None}], None)],
)
async def test_resolve_policy_maps_rows(rows: list[dict[str, Any]], expected: int | None) -> None:
    repo, _ = _repo(rows)
    assert await repo.resolve_policy("ETHUSDT", "trades") == expected


async def test_resolve_policy_sql_orders_pinned_then_symbol_then_default() -> None:
    repo, rel = _repo([])
    await repo.resolve_policy("ETHUSDT", "trades")
    sql = rel.calls[0][0]
    assert "pinned" in sql and "ORDER BY ord LIMIT 1" in sql
