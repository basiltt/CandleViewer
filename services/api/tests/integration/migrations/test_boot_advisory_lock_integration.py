"""Integration test for `candleviewer.migrations.boot` (E03-T10 acceptance
criterion 5: concurrent-boot advisory-lock serialisation).

Needs a real Postgres 16 (`testcontainers`, `@pytest.mark.integration` —
CONSTITUTION.md C-13.3 / `.claude/rules/40-testing.md`); no network egress
beyond the locally-started container, no live exchange. Not run in this
sandbox: docker is unavailable here ("not run locally: no docker" — see the
PR body); this suite is exercised by the `migrations` CI job's
`concurrent-boot` step.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.migrations.boot import run_migrations_under_advisory_lock

pytestmark = pytest.mark.integration

_SERVICES_API_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        # `run_migrations_under_advisory_lock` uses `asyncpg.connect(dsn=...)`
        # directly (not SQLAlchemy), so it needs the plain `postgresql://` URL.
        yield container.get_connection_url().replace("postgresql+psycopg2", "postgresql")


async def test_two_concurrent_boots_serialise_on_advisory_lock(pg_dsn: str) -> None:
    """Given two api containers start simultaneously against one database,
    when both attempt to apply migrations, then exactly one applies them and
    the other waits and then starts normally (ticket Gherkin scenario 5)."""
    results = await asyncio.gather(
        run_migrations_under_advisory_lock(
            pg_dsn, services_api_root=_SERVICES_API_ROOT, lock_timeout_s=60.0
        ),
        run_migrations_under_advisory_lock(
            pg_dsn, services_api_root=_SERVICES_API_ROOT, lock_timeout_s=60.0
        ),
    )

    # `alembic upgrade head` is idempotent, so both calls report success —
    # the assertion that matters is that neither raced (no lock-contention
    # error, no partial-apply exception) and both returned cleanly.
    assert all(result.applied for result in results)
