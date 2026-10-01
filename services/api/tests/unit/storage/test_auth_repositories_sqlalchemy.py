"""Auth SQL repositories with a fake unit of work (no docker: real-DB round
trip lives in tests/integration/auth, not run locally)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.app import build_auth_service
from candleviewer.settings import Environment, Settings
from candleviewer.storage.repositories.mfa_sqlalchemy import SqlAlchemyMfaRepository
from candleviewer.storage.repositories.users_sqlalchemy import SqlAlchemyUserRepository

_NOW = datetime(2026, 10, 1, tzinfo=UTC)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return self._rows


class _Rel:
    def __init__(self, rows: list[Any]) -> None:
        self.rows, self.calls = rows, []

    @asynccontextmanager
    async def unit_of_work(self) -> Any:
        async def execute(stmt: Any, params: dict[str, Any]) -> _Result:
            self.calls.append((str(stmt), params))
            return _Result(self.rows)

        async def commit() -> None:
            return None

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


def _row(**m: Any) -> Any:
    return SimpleNamespace(_mapping=m)


async def test_login_failure_is_one_atomic_conditional_update() -> None:
    rel = _Rel([_row(locked_until=_NOW)])
    repo = SqlAlchemyUserRepository(rel, dict, clock=lambda: _NOW)  # type: ignore[arg-type]  # fake
    got = await repo.record_login_failure(
        "u", lockout_threshold=5, lock_duration=timedelta(minutes=15), now=_NOW
    )
    sql, params = rel.calls[0]
    assert "failed_login_count + 1" in sql and "RETURNING" in sql
    assert params["threshold"] == 5 and got == _NOW


async def test_find_by_identifier_unknown_returns_none_and_is_parameterised() -> None:
    rel = _Rel([])
    repo = SqlAlchemyUserRepository(rel, dict, clock=lambda: _NOW)  # type: ignore[arg-type]  # fake
    assert await repo.find_by_identifier("x' OR 1=1 --") is None
    assert rel.calls[0][1] == {"ident": "x' OR 1=1 --"}


async def test_find_by_identifier_maps_json_params_and_methods() -> None:
    fields: dict[str, Any] = {
        "id": "i",
        "username": "u",
        "email": "e",
        "password_hash": "h",
        "password_algo_params": '{"m": 1}',
        "status": "active",
        "mfa_required": True,
        "failed_login_count": 0,
        "locked_until": None,
        "mfa_methods": ["totp"],
    }
    rel = _Rel([_row(**fields)])
    repo = SqlAlchemyUserRepository(rel, dict, clock=lambda: _NOW)  # type: ignore[arg-type]  # fake
    got = await repo.find_by_identifier("u")
    assert got["password_algo_params"] == {"m": 1} and got["mfa_methods"] == ("totp",)


async def test_recovery_code_consume_is_single_use_cas() -> None:
    rel = _Rel([])
    repo = SqlAlchemyMfaRepository(rel, dict, dict)  # type: ignore[arg-type]  # fake
    assert await repo.consume_recovery_code("c", now=_NOW) is False
    assert "used_at IS NULL" in rel.calls[0][0]
    rel.rows = [_row(x=1)]
    assert await repo.consume_recovery_code("c", now=_NOW) is True


async def test_time_step_replay_rejected_when_no_row_updated() -> None:
    rel = _Rel([])
    repo = SqlAlchemyMfaRepository(rel, dict, dict)  # type: ignore[arg-type]  # fake
    assert await repo.record_time_step("m", time_step=5) is False
    assert "last_accepted_time_step < :step" in rel.calls[0][0]


def test_build_auth_service_fake_backend_is_scaffold() -> None:
    assert build_auth_service(Settings()).is_active is False


def test_build_auth_service_real_backend_wires_repositories() -> None:
    svc = build_auth_service(Settings(storage_backend="real"))
    assert svc._repository is not None and svc._mfa_repository is not None
    assert svc._session_repository is not None


def test_build_auth_service_live_without_keys_refuses() -> None:
    with pytest.raises(ValueError, match="CV_AUTH_TOTP_KEY_HEX"):
        build_auth_service(Settings(storage_backend="real", environment=Environment.LIVE))


def test_seeder_refuses_outside_testnet() -> None:
    from scripts.seed_fixture_user import check_environment

    for env in ("live", "demo"):
        with pytest.raises(SystemExit):
            check_environment(env)
    check_environment("testnet")
