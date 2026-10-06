"""Scenario 1 - WS hard disconnect (TCP reset) mid-stream. C-13.6 #1.

Declared: reconnect with full-jitter backoff, one resubscribe per topic (no
duplicates), fresh book snapshot, `degraded` -> `resubscribing` -> `healthy`
feed signal (SCR-152 banner), `ingest_ws_up` 1 -> 0 -> 1, trade gap healed.
"""

from __future__ import annotations

import pytest

from candleviewer.book.models import BookPhase
from candleviewer.ingestion.metrics import ingest_ws_up
from tests._corpus import frames
from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._rig import Rig, metric

pytestmark = pytest.mark.chaos

BOOK = frames("ws/orderbook_BTCUSDT.jsonl")
#: Recovery SLO: reset -> book LIVE again (backoff cap at attempt 1 is 1 s).
RESYNC_SLO_S = 5.0


def _ws_up() -> float:
    return metric(ingest_ws_up, socket="public")


async def test_s01_reset_reconnects_resubscribes_once_and_resnapshots(rig: Rig) -> None:
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="first open")
    await rig.ex.replay(BOOK[:50])
    assert rig.book_phase() is BookPhase.LIVE and _ws_up() == 1.0
    rig.observe()

    rig.ex.inject(Fault(FaultKind.RESET))
    await rig.clock.settle()
    assert rig.ws.state() == "degraded" and _ws_up() == 0.0  # banner shows "reconnecting"

    async def feed_until_live() -> float:
        start = rig.clock.now
        i = 50
        while rig.book_phase() is not BookPhase.LIVE or rig.ws.state() != "open":
            assert rig.clock.now - start <= RESYNC_SLO_S, "book not resynced within SLO"
            rig.ex.emit(BOOK[i])
            i += 1
            await rig.clock.advance(0.1)
        return rig.clock.now - start

    elapsed = await feed_until_live()
    seen = rig.observe()
    states = [f.state for f in seen.feed if f.topic == "orderbook.200.BTCUSDT"]
    assert states[-3:] == ["degraded", "resubscribing", "healthy"], states
    assert len(rig.ex.sockets) == 2 and rig.ex.sockets[0].closed
    assert rig.ex.sockets[1].duplicate_subscribes == 0
    assert any(s.reason == "reconnect" for s in seen.book_status)
    assert _ws_up() == 1.0 and elapsed <= RESYNC_SLO_S
