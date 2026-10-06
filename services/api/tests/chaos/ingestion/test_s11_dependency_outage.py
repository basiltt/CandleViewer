"""Scenario 11 - dependency outage (QuestDB / Postgres restarted under load).
C-13.6 #10 (ingestion side; storage-internal chaos is E07-Q04).

Declared: while the hot tier is down ingestion keeps publishing live data (the
write-behind never blocks the reader), the write failures are visible
(`trade write-behind failed` log), and nothing is counted as persisted that was
not; after the outage the stream keeps persisting new data, and the instrument
catalogue (Postgres-backed) keeps serving its last snapshot, marked stale.
"""

from __future__ import annotations

import pytest
from structlog.testing import capture_logs

from candleviewer.book.models import BookPhase
from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._feed import Feeder
from tests.chaos.ingestion._rig import Rig

pytestmark = pytest.mark.chaos

OUTAGE_S = 10.0
DEFECT_LOSS = "#1918"


def _ids(events: list[object]) -> set[str]:
    return {str(getattr(e, "trade_id", "")) for e in events if hasattr(e, "trade_id")}


async def _outage(rig: Rig) -> tuple[Feeder, set[str]]:
    feed = Feeder(rig.ex)
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    await feed.run(2.0)
    published_before = _ids(rig.observe().trades)
    rig.writer.down = True
    await feed.run(OUTAGE_S)
    return feed, published_before


async def test_s11_hot_tier_outage_keeps_ingest_live_and_never_over_acknowledges(rig: Rig) -> None:
    with capture_logs() as logs:
        feed, _ = await _outage(rig)
    during = _ids(rig.observe().trades)
    assert len(during) >= OUTAGE_S * 2 - 2  # live publication never waited on storage
    assert rig.book_phase() is BookPhase.LIVE
    assert rig.writer.failed_batches > 0
    assert any(e.get("event") == "trade write-behind failed" for e in logs)
    assert _ids(rig.writer.persisted_trades) < during  # never acknowledged what failed

    rig.writer.down = False
    marker = len(rig.writer.persisted_trades)
    await feed.run(3.0)
    assert len(rig.writer.persisted_trades) > marker  # writes resume after recovery


async def test_s11_catalogue_outage_serves_last_snapshot_marked_stale(rig: Rig) -> None:
    rig.ex.inject(Fault(FaultKind.HTTP_STATUS, status=503, count=40,
                        path="/v5/market/instruments-info"))  # fmt: skip
    with pytest.raises(Exception, match="refresh failed"):
        await rig.call(rig.instruments.refresh_now(), within_s=300)
    snap = rig.instruments.snapshot()
    assert snap is not None and snap.get("BTCUSDT") is not None  # still serving
    assert snap.stale_since_us is not None  # and visibly stale (SCR health)
    assert rig.is_listed("BTCUSDT")


@pytest.mark.xfail(strict=True, reason=f"{DEFECT_LOSS}: failed write-behind batches are dropped")
async def test_s11_buffered_writes_drain_after_the_outage(rig: Rig) -> None:
    feed, _ = await _outage(rig)
    published = _ids(rig.observe().trades)
    rig.writer.down = False
    await feed.run(5.0)
    assert published <= _ids(rig.writer.persisted_trades), "outage-window prints never persisted"
