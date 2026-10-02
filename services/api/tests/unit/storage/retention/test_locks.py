"""Reaper run locks (E07-Q04 scenario 8, SR-099)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from candleviewer.storage.retention.locks import InProcessRunLock, advisory_key
from candleviewer.storage.retention.policy import RetentionPolicy, load_defaults
from candleviewer.storage.retention.reaper import Reaper
from tests.unit.storage.retention.test_reaper import NOW, Env, part


class _SharedLock:
    """Stands in for one Postgres advisory-lock table shared by two processes."""

    def __init__(self) -> None:
        self.held: set[str] = set()
        self.denied = 0

    @asynccontextmanager
    async def hold(self, volume: str) -> AsyncIterator[bool]:
        if volume in self.held:
            self.denied += 1
            yield False
            return
        self.held.add(volume)
        try:
            await asyncio.sleep(0)  # let the rival instance contend
            yield True
        finally:
            self.held.discard(volume)


def _reaper(env: Env, lock: _SharedLock) -> Reaper:
    return Reaper(
        RetentionPolicy([], load_defaults()),
        env, env, env, env, env, env,
        clock=lambda: NOW,
        lock=lock,
    )  # fmt: skip


async def test_two_concurrent_reapers_one_drop_one_audit() -> None:
    env = Env([part("A", 40)])
    lock = _SharedLock()
    await asyncio.gather(_reaper(env, lock).run(), _reaper(env, lock).run())
    assert len([e for e in env.log if e.startswith("drop:")]) == 1
    assert len([a for a in env.audits if a[0] == "retention.purge"]) == 1
    assert lock.denied == 1 and not lock.held


async def test_in_process_lock_denies_reentry_and_releases() -> None:
    lock = InProcessRunLock()
    async with lock.hold("v") as first:
        async with lock.hold("v") as second:
            assert first and not second
        async with lock.hold("w") as other:
            assert other
    async with lock.hold("v") as again:
        assert again


def test_advisory_key_stable_signed_64bit_and_per_volume() -> None:
    k = advisory_key("data")
    assert k == advisory_key("data") and k != advisory_key("cold")
    assert -(2**63) <= k < 2**63
