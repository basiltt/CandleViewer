"""Harness guards (E08-Q03 security notes; C-13.5, SR-140).

* The suite cannot reach live Bybit: the REST client runs on the stub's
  in-process transport, and a raw dial to the live host is refused by the
  session network guard.
* Same seed => same fault trace (determinism AC).
"""

from __future__ import annotations

import socket

import pytest

from tests._ci_network_guard import NetworkGuardViolation
from tests._corpus import frames
from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._rig import Rig

pytestmark = pytest.mark.chaos

BOOK = frames("ws/orderbook_BTCUSDT.jsonl")


def test_live_exchange_host_is_unreachable_from_the_suite() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(NetworkGuardViolation):
            sock.connect(("api.bybit.com", 443))
    finally:
        sock.close()


async def test_rest_traffic_is_answered_by_the_stub_transport(rig: Rig) -> None:
    body = await rig.rest.get_public("/v5/market/time")
    assert body["retCode"] == 0
    assert rig.ex.rest_calls[-1][1] == "/v5/market/time"


async def _scripted_run(seed: int) -> list[tuple[float, str, str]]:
    r = Rig(seed=seed)
    await r.start()
    try:
        await r.clock.run_until(lambda: r.ws.state() == "open", within_s=5, what="open")
        await r.ex.replay(BOOK[:20])
        r.ex.inject(Fault(FaultKind.REFUSE, count=3))
        r.ex.inject(Fault(FaultKind.RESET))
        await r.clock.run_until(lambda: r.ws.state() == "open", within_s=60, what="reopen")
        await r.ex.replay(BOOK[20:40])
        return list(r.ex.trace.events)
    finally:
        await r.stop()


async def test_same_seed_gives_an_identical_fault_trace() -> None:
    first, second = await _scripted_run(7), await _scripted_run(7)
    assert first == second
    assert any(kind == "ws.refused" for _, kind, _ in first)


async def test_drop_duplicate_and_reorder_faults_act_on_the_wire_only(rig: Rig) -> None:
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    topic = "orderbook.200.BTCUSDT"
    rig.ex.inject(Fault(FaultKind.DUPLICATE, topic=topic))
    rig.ex.inject(Fault(FaultKind.REORDER, topic=topic))
    await rig.ex.replay(BOOK[:4])
    kinds = [k for _, k, _ in rig.ex.trace.events if k.startswith("fault.")]
    assert kinds == ["fault.reorder", "fault.duplicate"]  # reorder holds frame 1 first
    assert rig.ex.books[topic].u == 4  # the venue's truth is untouched by wire faults
