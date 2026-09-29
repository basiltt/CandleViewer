"""Lifecycle contract for the oms module (M14).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. This is an
empty scaffold — the supervisor (Sec.6.2) can construct and sequence this
module, but it does no real work until its owning epic lands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from candleviewer.observability.health import HealthReport, HealthStatus

from .validator import ReadOnlyCheck, Validator

if TYPE_CHECKING:
    from candleviewer.app import AppContext


class OmsService:
    """Empty scaffold for the M14 `oms` module lifecycle.

    `validator` (E09-T04) is the one piece of real, always-on logic this
    scaffold carries: it is constructed in `start()` from
    `ctx.oms_read_only_gate` (injected by the composition root, never
    imported directly per M14's §3 allow-list) so every order path can call
    `validator.assert_order_placement_allowed()` regardless of how much of
    the rest of OMS has landed yet.
    """

    def __init__(self) -> None:
        self._started = False
        self.validator: Validator | None = None

    async def start(self, ctx: AppContext) -> None:
        """Start the module. No-op until the owning epic implements it."""
        self.validator = Validator(read_only_gate=ctx.oms_read_only_gate)
        self._started = True

    async def stop(self, grace_s: float) -> None:
        """Stop the module within `grace_s` seconds. No-op scaffold."""
        self._started = False

    def health(self) -> HealthReport:
        """Report module health. Scaffold modules report `ok` when constructed."""
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        return HealthReport(module="", status=status, detail="scaffold module — no real logic yet")


__all__ = ["OmsService", "ReadOnlyCheck", "Validator"]
