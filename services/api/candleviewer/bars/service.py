"""Lifecycle contract for the bars module (M8): `start`, `stop`, `health`
(`docs/plan/20-architecture.md` Sec.3).

The `BarBuilderSet` is constructed by its consumer wiring (E12-T05/T06) and attached with
`attach()`. `health()` is DEGRADED, never down, with the set's sticky `BarsHealthReason`
tokens as `detail` (blob cold start SR-E12-12, quarantined builder, dead task, sink timeout).
The composition root exposes it as the `bars` health component
(`health_wiring.register_bars_probe`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from candleviewer.observability.health import HealthReport, HealthStatus

if TYPE_CHECKING:
    from candleviewer.app import AppContext
    from candleviewer.bars.builder_set import BarBuilderSet


class BarsService:
    """M8 `bars` module lifecycle."""

    def __init__(self) -> None:
        self._started = False
        self._set: BarBuilderSet | None = None

    def attach(self, builder_set: BarBuilderSet) -> None:
        self._set = builder_set

    async def start(self, ctx: AppContext) -> None:
        self._started = True

    async def stop(self, grace_s: float) -> None:
        if self._set is not None:
            await self._set.stop()
        self._started = False

    def health(self) -> HealthReport:
        if not self._started:
            return HealthReport(module="bars", status=HealthStatus.STOPPED, detail="")
        reasons = () if self._set is None else self._set.health_reasons()
        if reasons:
            detail = ",".join(r.value for r in reasons)
            return HealthReport(module="bars", status=HealthStatus.DEGRADED, detail=detail)
        return HealthReport(module="bars", status=HealthStatus.OK, detail="")
