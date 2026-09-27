"""Alembic environment for CandleViewer's Postgres schema (M10 `storage`).

This is an empty skeleton (E02-T05): the revision tree is currently empty
(single-head check passes trivially) and content is added by E07. The
`sqlalchemy.url` is resolved from `Settings.pg_dsn` at runtime — never
hard-coded here (C-12.2, no secrets in code).
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None  # populated once storage models exist (E07).


def _get_url() -> str:
    from candleviewer.settings import get_settings

    return get_settings().pg_dsn.get_secret_value()


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection ("offline" mode)."""
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection ("online" mode)."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
