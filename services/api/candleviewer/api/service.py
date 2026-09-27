"""Lifecycle contract for the api module (M23 `api` half).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. Routing
itself (`/healthz`, `/readyz`) lives in `health.py`; this scaffold exists so
the supervisor can sequence M23 alongside every other module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from candleviewer.observability.health import HealthReport, HealthStatus

if TYPE_CHECKING:
    from candleviewer.app import AppContext


class ApiService:
    """Empty scaffold for the M23 `api` module lifecycle."""

    def __init__(self) -> None:
        self._started = False

    async def start(self, ctx: AppContext) -> None:
        """Start the module. No-op until the owning epic implements it."""
        self._started = True

    async def stop(self, grace_s: float) -> None:
        """Stop the module within `grace_s` seconds. No-op scaffold."""
        self._started = False

    def health(self) -> HealthReport:
        """Report module health. Scaffold modules report `ok` when constructed."""
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        return HealthReport(
            module="", status=status, detail="scaffold module — no real logic yet"
        )
