"""Lifecycle contract for the bus module (M5).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. `BusService`
now owns a real `Bus` (E08-T03); `start()`/`stop()` gate publish acceptance
and drain `NEVER_DROP` queues on shutdown per §4.1 rule 2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from candleviewer.bus.bus import Bus
from candleviewer.observability.health import HealthReport, HealthStatus

if TYPE_CHECKING:
    from candleviewer.app import AppContext


class BusService:
    """Owns the process-wide `Bus` instance for the M5 `bus` module."""

    def __init__(self) -> None:
        self._started = False
        self.bus = Bus()

    async def start(self, ctx: AppContext) -> None:
        """Start the module: the bus accepts publishes immediately on
        construction, so this only flips the lifecycle flag."""
        self._started = True

    async def stop(self, grace_s: float) -> dict[str, int]:
        """Stop the module within `grace_s` seconds: stop accepting new
        publishes and drain outstanding `NEVER_DROP` queues. Returns the
        outstanding-count dict from `Bus.drain` (empty means nothing lost)."""
        outstanding = await self.bus.drain(grace_s)
        self._started = False
        return outstanding

    def health(self) -> HealthReport:
        """Report module health. Reports `ok` once started."""
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        return HealthReport(module="bus", status=status, detail="in-process topic bus")
