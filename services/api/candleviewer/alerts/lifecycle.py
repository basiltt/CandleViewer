"""`AlertCharts`: B10 `alert` lifecycle recorder (E40-T03, C-2.19).

One chart per live alert, built only through `statechart.factory.build("alert")` and
driven only through `statechart.gateway`. Statecharts record, synchronous code enforces
(C-2.21): by the time an event is sent the evaluator has already gated, decided and
committed. A send the current state does not handle is refused here via `can()` and
never parked on the `onUnhandled: "defer"` queue (CV-C06). Each firing's terminal
outcome resets the chart (the alert re-arms for the next firing). Sealed-snapshot
restore goes through `statechart.persistence.restore` once a snapshot repository is
wired (E50); until then the `alerts` row is the durable truth and charts are rebuilt.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Sequence
from typing import Any, Final

import candleviewer.statechart.bindings.b10_alert as b10
from candleviewer.statechart import build
from candleviewer.statechart.factory import default_clock
from candleviewer.statechart.gateway import Gateway

MACHINE: Final = "alert"
LANE: Final = "platform"
MAX_CHARTS: Final = 4096
_TERMINAL: Final = frozenset({"delivered", "partially_delivered", "delivery_failed"})
_SETTLE_YIELDS: Final = 64
#: Await each event's macrostep so a failed B10 action surfaces here. Safe: sends come only
#: from the evaluator task, never from a B10 action, so the CV-C51 self-receipt hang cannot
#: arise (same pattern as `rules.lifecycle`).
_AWAIT_STEP: Final = True


class _Refusals:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def record_send_refused(self, reason: str) -> None:
        self.counts[reason] = self.counts.get(reason, 0) + 1


def leaf_of(interp: Any) -> str:
    state: str = next(iter(interp.current_state_ids))
    return state.split(".", 1)[1]


class AlertCharts:
    def __init__(self, *, max_charts: int = MAX_CHARTS, hook: b10.Hook | None = None) -> None:
        self._charts: OrderedDict[str, Any] = OrderedDict()
        self._gateway = Gateway()
        self.refusals = _Refusals()
        self._lock = asyncio.Lock()
        self._max = max_charts
        self._owns_hook = hook is not None
        if hook is not None:
            b10.set_hook(hook)

    def leaf(self, alert_id: str) -> str | None:
        interp = self._charts.get(alert_id)
        return None if interp is None else leaf_of(interp)

    async def _get(self, alert_id: str) -> Any:
        async with self._lock:
            interp = self._charts.get(alert_id)
            if interp is not None and leaf_of(interp) not in _TERMINAL | {"resolved"}:
                self._charts.move_to_end(alert_id)
                return interp
            if interp is not None:  # previous firing finished: fresh armed chart
                await self._drop(alert_id)
            interp = (await build(MACHINE, clock=default_clock(), lane=LANE)).interpreter
            self._gateway.register(alert_id, interp, kind="alert", lane=LANE, metrics=self.refusals)
            self._charts[alert_id] = interp
            while len(self._charts) > self._max:
                await self._drop(next(iter(self._charts)))
            return interp

    async def _drop(self, alert_id: str) -> None:
        interp = self._charts.pop(alert_id, None)
        self._gateway.unregister(alert_id)
        if interp is not None:
            await interp.stop()

    async def _send_alert(self, key: str, event: str, /, **payload: Any) -> str:
        """Unique name + literal event so `tools/statechart/event_coverage.py` checks
        every alert send against the B10 descriptor."""
        ev: dict[str, Any] = {"type": event, **payload}
        interp = await self._get(key)
        if not interp.can(ev):
            self.refusals.record_send_refused("unhandled")
            return leaf_of(interp)
        await self._gateway.send(key, {"type": event, **payload}, wait=_AWAIT_STEP)
        return leaf_of(interp)

    async def fired(
        self, alert_id: str, delivery_ids: Sequence[int], channels: Sequence[str]
    ) -> None:
        await self._send_alert(
            alert_id,
            "CONDITION_MET",
            storm=False,
            alert_id=alert_id,
            delivery_ids=list(delivery_ids),
            channels=list(channels),
        )
        await self._settle(alert_id)

    async def _settle(self, alert_id: str) -> None:
        """Let the `deliver` invoke (a pure hand-off, no I/O) reach its outcome so the
        next firing finds a terminal chart. Bounded cooperative yields, never a timed wait."""
        for _ in range(_SETTLE_YIELDS):
            if self.leaf(alert_id) != "firing":
                return
            await asyncio.sleep(0)

    async def suppressed(self, alert_id: str, window_end_ms: int) -> None:
        await self._send_alert(
            alert_id,
            "CONDITION_MET",
            storm=True,
            alert_id=alert_id,
            storm_window_end_us=window_end_ms * 1000,
        )

    async def suppression_expired(self, alert_id: str) -> None:
        await self._send_alert(alert_id, "SUPPRESSION_EXPIRED")

    async def disabled(self, alert_id: str) -> None:
        await self._send_alert(alert_id, "DISABLE")

    async def stop(self) -> None:
        async with self._lock:
            for aid in list(self._charts):
                await self._drop(aid)
        if self._owns_hook:
            b10.set_hook(None)
