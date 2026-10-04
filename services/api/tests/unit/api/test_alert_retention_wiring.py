"""E40-T01: alert retention purge is wired through `create_app()` (PR #1770 review)."""

from __future__ import annotations

from pydantic import SecretStr

from candleviewer.app import create_app
from candleviewer.settings import Settings


def test_purge_task_enabled_with_owner_dsn_and_retention() -> None:
    s = Settings(
        retention_enabled=True,
        pg_owner_dsn=SecretStr("postgresql+asyncpg://cv_owner:x@localhost:5432/candleviewer"),
    )
    task = create_app(s).state.alert_purge_task
    assert task._enabled is True


def test_purge_task_off_without_owner_dsn() -> None:
    task = create_app(Settings(retention_enabled=True)).state.alert_purge_task
    assert task._enabled is False


def test_purge_task_off_when_retention_disabled() -> None:
    s = Settings(
        retention_enabled=False,
        pg_owner_dsn=SecretStr("postgresql+asyncpg://cv_owner:x@localhost:5432/candleviewer"),
    )
    assert create_app(s).state.alert_purge_task._enabled is False
