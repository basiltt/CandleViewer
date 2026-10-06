"""Scenario 1 (demand churn) - topic changes while the socket is LIVE.

Declared (E08-T04): a demand change on an open connection re-plans the
subscription (`TOPICS_CHANGED` -> `subscribing`), so a newly acquired symbol is
subscribed without a reconnect and the caller never sees an exception.
"""

from __future__ import annotations

import pytest

from tests.chaos.ingestion._feed import Feeder
from tests.chaos.ingestion._rig import Rig

pytestmark = pytest.mark.chaos

DEFECT_TOPICS_CHANGED = "#1915"


@pytest.mark.xfail(strict=True, reason=f"{DEFECT_TOPICS_CHANGED}: set_desired raises while open")
async def test_s01b_new_demand_on_a_live_socket_is_subscribed_without_reconnect() -> None:
    rig = Rig(seed=11, symbols=("BTCUSDT",))
    await rig.start()
    try:
        feed = Feeder(rig.ex)
        await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
        await feed.run(1.0)
        rig.trades.acquire("chart-2", "ETHUSDT")  # must not raise
        await rig.clock.run_until(
            lambda: "publicTrade.ETHUSDT" in rig.ex.live_sockets()[0].topics,
            within_s=2,
            what="ETH subscribed",
        )
        assert len(rig.ex.sockets) == 1  # no reconnect needed for a demand change
    finally:
        await rig.stop()
