"""`SqlAlchemyIdentityProvider` with a fake unit of work (QA #1658)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.storage.repositories.identity_sqlalchemy import SqlAlchemyIdentityProvider

_NOW = datetime(2026, 10, 1, tzinfo=UTC)


class _Rel:
    def __init__(self, results: list[list[Any]]) -> None:
        self.results = results
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: dict[str, Any]) -> Any:
            self.calls.append((str(stmt), params))
            rows = self.results.pop(0)
            return SimpleNamespace(first=lambda: rows[0] if rows else None, all=lambda: rows)

        yield SimpleNamespace(session=SimpleNamespace(execute=execute))


def _provider(rel: _Rel) -> SqlAlchemyIdentityProvider:
    return SqlAlchemyIdentityProvider(rel)  # type: ignore[arg-type]  # structural fake


async def test_user_maps_openapi_user_without_secret_columns() -> None:
    row = SimpleNamespace(
        _mapping={
            "id": "u1",
            "username": "alice",
            "email": "a@x.invalid",
            "display_name": None,
            "status": "active",
            "mfa_required": True,
            "mfa_enabled": True,
            "roles": ["owner"],
            "last_login_at": None,
            "created_at": _NOW,
            "updated_at": _NOW,
        }
    )
    rel = _Rel([[row]])
    user = await _provider(rel).user("u1")
    assert user["roles"] == ["owner"] and user["mfa_enabled"] is True
    assert user["created_at"] == _NOW.isoformat() and user["last_login_at"] is None
    sql, params = rel.calls[0]
    assert "password_hash" not in sql and params == {"id": "u1"}


async def test_user_unknown_raises_lookup_error() -> None:
    with pytest.raises(LookupError):
        await _provider(_Rel([[]])).user("nope")


async def test_session_info_lists_permissions_and_scope() -> None:
    rel = _Rel([[("orders:submit",), ("users:write",)], [("acc-1",)]])
    info = await _provider(rel).session_info("u1")
    assert info == {"permissions": ["orders:submit", "users:write"], "account_scope": ["acc-1"]}
