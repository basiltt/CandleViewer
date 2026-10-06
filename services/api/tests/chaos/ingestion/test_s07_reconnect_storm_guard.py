"""Scenario 7 - reconnect-storm guard (SR-039). C-13.6 #1.

200 induced disconnects inside 5 minutes (TCP resets plus refused dials).
Declared: the connection-attempt token bucket (`ConnectionRateGuard`) keeps
dials under its configured budget in every sliding 300 s window - well under
Bybit's 500/5 min/IP - and when the budget is spent the B13 chart enters
`budget_blocked` (feed `degraded`, never a tight loop). Exceeding the bound is
an assertion failure, not a warning.
"""

from __future__ import annotations

import pytest

from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._rig import Rig
from tests.chaos.ingestion._stub_exchange import EXCHANGE_CONN_LIMIT

pytestmark = pytest.mark.chaos

WINDOW_S = 300.0
DISCONNECTS = 200


async def _storm(rig: Rig, *, disconnects: int, over_s: float) -> None:
    every = over_s / disconnects
    for i in range(disconnects):
        if i % 4 == 3:
            rig.ex.inject(Fault(FaultKind.REFUSE))  # a refused dial still counts
        rig.ex.inject(Fault(FaultKind.RESET))
        await rig.clock.advance(every)


async def test_s07_200_disconnects_in_5_min_stay_within_the_attempt_budget() -> None:
    budget = 120  # a deliberately tight bucket so the guard, not luck, bounds the dials
    rig = Rig(seed=7, conn_limit=budget)
    await rig.start()
    try:
        await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
        await _storm(rig, disconnects=DISCONNECTS, over_s=WINDOW_S)
        await rig.clock.advance(WINDOW_S)  # let any parked reconnects drain
        peak = rig.ex.conn_attempts_in_any_window(WINDOW_S)
        assert peak <= budget, f"{peak} dials in a 300 s window > budget {budget}"
        assert peak < EXCHANGE_CONN_LIMIT
        degraded = [f for f in rig.observe().feed if f.state == "degraded"]
        assert degraded, "budget exhaustion must be visible (feed degraded)"
    finally:
        await rig.stop()


async def test_s07_default_budget_stays_well_under_the_exchange_cap() -> None:
    """Production defaults (480/300 s): the storm never approaches 500."""
    rig = Rig(seed=8)
    await rig.start()
    try:
        await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
        await _storm(rig, disconnects=DISCONNECTS, over_s=WINDOW_S)
        peak = rig.ex.conn_attempts_in_any_window(WINDOW_S)
        assert peak < EXCHANGE_CONN_LIMIT
        assert peak <= 480
    finally:
        await rig.stop()
