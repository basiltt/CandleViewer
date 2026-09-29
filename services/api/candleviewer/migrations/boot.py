"""Boot-time Alembic migration runner under a Postgres advisory lock
(ADR-0013 rule 9, E03-T10 acceptance criterion 5: "two api containers start
simultaneously against one database ... exactly one applies them and the
other waits and then starts normally").

`pg_advisory_lock(hashtext('cv_migrations'))` serialises concurrent boots: a
losing process blocks on the lock acquisition (not a busy retry loop) until
the winner commits and releases it, then proceeds to find nothing left to
apply. `CV_MIGRATION_LOCK_TIMEOUT` (default 300s) bounds the wait so a
deadlocked winner produces a clear `CI-DEP-004` error instead of hanging the
loser's startup forever.

This module never imports Alembic's CLI; it shells out to `alembic upgrade
head` (matching `alembic.ini`'s `script_location`) so the exact same
programmatic entrypoint `env.py` uses for offline/online mode is exercised,
keeping this helper and CI's `alembic upgrade head` step identical in
behaviour.

Driver policy (one consistent approach): Alembic always runs SYNCHRONOUSLY on
psycopg 3 (`postgresql+psycopg://`). The subprocess receives the target DSN
explicitly via `CV_PG_DSN`, normalised by `to_sync_dsn`, and `env.py` applies
the same normalisation — handing Alembic's sync engine an async driver
(`+asyncpg` / `+psycopg_async`) raises `MissingGreenlet`. The advisory lock is
held on a dedicated asyncpg session for the whole subprocess lifetime; since
`pg_advisory_lock` is session-scoped this serialises every booting process
without the migration needing to share that connection.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import asyncpg

from candleviewer.migrations.dsn import (
    redact_dsn_credentials,
    to_asyncpg_dsn,
    to_sync_dsn,
)

__all__ = [
    "MigrationApplyFailed",
    "MigrationLockTimeout",
    "MigrationRunResult",
    "redact_dsn_credentials",
    "run_migrations_under_advisory_lock",
    "to_asyncpg_dsn",
    "to_sync_dsn",
]

_LOCK_KEY_NAME = "cv_migrations"
_DEFAULT_LOCK_TIMEOUT_S = 300.0


class MigrationLockTimeout(Exception):
    """Raised as `CI-DEP-004`: the advisory lock was not acquired within
    `CV_MIGRATION_LOCK_TIMEOUT` seconds — likely a deadlocked or hung
    migration in another process."""


class MigrationApplyFailed(Exception):
    """Raised when `alembic upgrade head` exits non-zero under the lock."""


@dataclass(frozen=True)
class MigrationRunResult:
    applied: bool
    """`True` once this process has run `alembic upgrade head` under the
    lock and it exited 0. `alembic upgrade head` is itself idempotent, so
    the loser in the concurrent-boot scenario also gets `True` here — its
    invocation is simply a no-op (nothing left above the already-applied
    head) rather than a skipped call."""
    stdout: str
    stderr: str


async def run_migrations_under_advisory_lock(
    dsn: str,
    *,
    services_api_root: Path,
    lock_timeout_s: float = _DEFAULT_LOCK_TIMEOUT_S,
) -> MigrationRunResult:
    """Acquire the `cv_migrations` advisory lock, run `alembic upgrade head`,
    release the lock. Blocks (does not poll/retry) while another process
    holds the lock, bounded by `lock_timeout_s`.

    `dsn` may carry any SQLAlchemy driver suffix; it is normalised to plain
    `postgresql://` for the lock connection and to `postgresql+psycopg://`
    for the Alembic subprocess (see module docstring).
    """
    conn = await asyncpg.connect(dsn=to_asyncpg_dsn(dsn))
    try:
        try:
            await asyncio.wait_for(
                conn.execute("SELECT pg_advisory_lock(hashtext($1))", _LOCK_KEY_NAME),
                timeout=lock_timeout_s,
            )
        except TimeoutError as exc:
            raise MigrationLockTimeout(
                f"CI-DEP-004: timed out after {lock_timeout_s}s waiting for the "
                f"'{_LOCK_KEY_NAME}' advisory lock — check for a hung migration"
            ) from exc

        try:
            # `subprocess.run` blocks; run it off the event loop (C-2.18 —
            # never block the loop) via `asyncio.to_thread`.
            result = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=services_api_root,
                capture_output=True,
                text=True,
                timeout=lock_timeout_s,
                env={**os.environ, "CV_PG_DSN": to_sync_dsn(dsn)},
            )
            if result.returncode != 0:
                raise MigrationApplyFailed(
                    f"alembic upgrade head failed (exit {result.returncode}): "
                    f"{redact_dsn_credentials(result.stderr)}"
                )
            return MigrationRunResult(applied=True, stdout=result.stdout, stderr=result.stderr)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(hashtext($1))", _LOCK_KEY_NAME)
    finally:
        await conn.close()
