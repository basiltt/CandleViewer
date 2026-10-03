"""Supervised daily prune of unmatched rule runs (E35-T02, schema doc 3.4.3/7).

Started by the ASGI lifespan only when `retention_enabled` (RetentionSchedule
`rule_jobs()` non-empty). Interval-based (24 h): the codebase has no cron
evaluator, and the job is idempotent so the exact minute is immaterial.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from candleviewer.observability.context import spawn
from candleviewer.storage.retention.schedule import RetentionSchedule

logger = logging.getLogger(__name__)
PRUNE_INTERVAL_SECONDS = 24 * 3600


class _Pruner(Protocol):
    async def prune_unmatched(self) -> object: ...


class RulePruneTask:
    """Tracked, cancellable owner of the rule-run prune loop (C-2.18)."""

    def __init__(
        self,
        repo: _Pruner,
        schedule: RetentionSchedule,
        *,
        interval_s: float = PRUNE_INTERVAL_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._repo = repo
        self._enabled = bool(schedule.rule_jobs())
        self._interval_s = interval_s
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def run_once(self) -> None:
        try:
            await self._repo.prune_unmatched()
        except Exception:
            logger.exception("rule_runs_prune_failed")

    async def _loop(self) -> None:
        while True:
            await self.run_once()
            await self._sleep(self._interval_s)

    def start(self) -> None:
        if self._enabled and self._task is None:
            self._task = spawn(self._loop(), name="rule-runs-prune")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
