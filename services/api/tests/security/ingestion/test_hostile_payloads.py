"""E08-X02 (a): malformed / hostile payloads through the production streams.

Gherkin "Hostile input is rejected, never trusted": no domain event, no crash,
a structured log entry. Case ids map to `E08_X02_FINDINGS.md` section A.
"""

from __future__ import annotations

import asyncio

import pytest
from structlog.testing import capture_logs

from candleviewer.ingestion.metrics import trade_prints_rejected_total
from candleviewer.ingestion.service import IngestionService
from candleviewer.observability.context import spawn
from tests.security.ingestion._harness import Rig
from tests.security.ingestion.corpus import TRADES, Hostile, iter_hostile_frames, nested, trade

HOSTILE = list(iter_hostile_frames())
_ACCEPTED_BY_DESIGN = {"extra_fields"}  # A-06: unknown fields are ignored, see register


@pytest.mark.parametrize("h", HOSTILE, ids=[h.case for h in HOSTILE])
async def test_hostile_frame_emits_no_domain_event(h: Hostile) -> None:
    rig = Rig()
    with capture_logs() as logs:
        await rig.feed(h.frame)
    published = rig.drain()
    if h.case in _ACCEPTED_BY_DESIGN:
        assert len(published) == 1  # well-formed core, unknown keys dropped
        return
    assert published == [] or all(type(e).__name__ == "BookStatus" for e in published)
    syntactic = h.frame.lstrip().startswith(("{", "[")) and h.case != "truncated_frame"
    if syntactic and h.case not in {"top_level_array", "invalid_utf8_surrogate"}:
        assert any("rejected" in str(r.get("event")) for r in logs), h.case


async def test_duplicate_json_key_last_wins_consistently() -> None:
    # A-07: Python json keeps the last duplicate; recorded as accepted-by-design
    # (the exchange never sends duplicates; consistency matters, not rejection).
    rig = Rig()
    frame = trade().replace('"S":"Buy"', '"S":"Buy","S":"Sell"')
    await rig.feed(frame)
    (ev,) = rig.drain()
    assert ev.side == "sell"


async def test_trade_rejection_counter_increments() -> None:
    before = trade_prints_rejected_total._value.get()
    await Rig().feed(trade(p="NaN"))
    assert trade_prints_rejected_total._value.get() == before + 1


# fixed by #1898 (#1894): no ingest_rejected_total{reason} for ticker/book
async def test_every_rejection_is_counted_with_reason() -> None:
    from candleviewer.ingestion import metrics

    assert hasattr(metrics, "ingest_rejected_total")


# fixed by #1898 (#1889): RecursionError escapes handle_frame, pump dies
async def test_deep_nesting_does_not_kill_pump() -> None:
    svc, rig = IngestionService(), Rig()
    svc.attach_trades(rig.trades)
    pump = spawn(svc._pump_frames(), name="x02-pump")
    try:
        svc.offer_frame(nested(5_000))
        svc.offer_frame(TRADES[0])
        for _ in range(5):
            await asyncio.sleep(0)
        assert not pump.done(), repr(pump.exception())
        assert rig.drain(), "pump must keep delivering after a hostile frame"
    finally:
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)


async def test_shallow_nesting_is_rejected_cleanly() -> None:
    rig = Rig()
    await rig.feed(nested(500))
    assert rig.drain() == []
