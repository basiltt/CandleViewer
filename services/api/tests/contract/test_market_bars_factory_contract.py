"""#2191: `/market/bars` for range:20 and delta:500 is backed by a live builder set composed
with the production factory (the E12-T05 black-box only exercised stored rows)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from candleviewer.api.market_bars import parse_bar_request
from candleviewer.bars.builder_set import BarBuilderSet, production_factory
from candleviewer.bars.emit import EmitRouter
from candleviewer.bars.state_store import StateStore
from candleviewer.bus.bus import Bus
from tests.contract.test_market_bars_contract import _P, _client
from tests.unit.bars._set_harness import ENV, TOPIC, Clock, settle
from tests.unit.bars._trades import SYM, trade, us


@pytest.mark.parametrize(("bar_type", "param"), [("range", "20"), ("delta", "500")])
async def test_market_bars_range_and_delta_compose_a_live_builder_set(
    bar_type: str, param: str, tmp_path: Path
) -> None:
    bus = Bus()
    s = BarBuilderSet(
        bus, ENV, EmitRouter([]), StateStore(tmp_path), now_us=Clock(),
        factory=production_factory(lambda _s: Decimal("0.1"), renko_enabled=False),
    )  # fmt: skip
    await s.register(parse_bar_request(bar_type, param), SYM, "c1")
    await bus.publish(TOPIC, trade(us("10:00:00"), seq=1))
    await settle(bus, s)
    resp = _client().get("/market/bars", params={**_P, "bar_type": bar_type, "param": param})
    assert resp.status_code == 200, resp.text
    await s.stop()
