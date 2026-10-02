"""Reaper run locks (E07-Q04 scenario 8, SR-099).

Two reaper instances must never drop or audit the same partition twice. The
production guard is a Postgres session advisory lock keyed per volume: the
loser of `pg_try_advisory_lock` skips the run (non-blocking, no queueing).
The lock lives on one dedicated connection held for the whole run, so a
crashed holder releases it when its connection dies.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

#: Namespace for the advisory-lock key so it cannot collide with the boot
#: migration lock (E03-T10) or any other `pg_advisory_lock` user.
_NAMESPACE = b"cv.storage.retention.reaper:"


def advisory_key(volume: str) -> int:
    """Stable signed 64-bit key for `volume` (Postgres `bigint`)."""
    digest = hashlib.blake2b(_NAMESPACE + volume.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


class InProcessRunLock:
    """Default lock: serialises runs per volume inside one process only."""

    def __init__(self) -> None:
        self._held: set[str] = set()

    @asynccontextmanager
    async def hold(self, volume: str) -> AsyncIterator[bool]:
        if volume in self._held:
            yield False
            return
        self._held.add(volume)
        try:
            yield True
        finally:
            self._held.discard(volume)


class PgAdvisoryRunLock:
    """Cross-instance lock: `pg_try_advisory_lock(key(volume))` on a held connection."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @asynccontextmanager
    async def hold(self, volume: str) -> AsyncIterator[bool]:
        key = advisory_key(volume)
        async with self._engine.connect() as conn:
            got = bool(
                (await conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key})).scalar()
            )
            await conn.commit()
            try:
                yield got
            finally:
                if got:
                    await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
                    await conn.commit()


__all__ = ["InProcessRunLock", "PgAdvisoryRunLock", "advisory_key"]
