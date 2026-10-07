"""Scenario 5 - rate limit `10018` burst. C-13.6 #5 (public-data side; the
stop/cancel reserve half belongs to the OMS chaos tickets E29-Q04/E45-T07).

Declared: each 10018 maps to `RateLimitError`, the local bucket is set from
`X-Bapi-Limit-Status` (headroom gauge dips to 0), `bybit_rate_limited_total`
counts it, every caller is held for the IP-level backoff (>= 600 s, #1908; retries
also wait until `X-Bapi-Limit-Reset-Timestamp`), the WS
is never recycled by a REST rate limit (no reconnect storm), and headroom
recovers on the next good response.
"""

from __future__ import annotations

import pytest

from candleviewer.exchange.base.errors import RateLimitError

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.config import EndpointClass

# nosemgrep: cv-adapter-isolation reason=Q03 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.metrics import bybit_rate_limit_remaining, bybit_rate_limited_total
from candleviewer.observability.context import spawn
from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._feed import Feeder
from tests.chaos.ingestion._rig import Rig, metric

pytestmark = pytest.mark.chaos

PATH = "/v5/market/recent-trade"
PARAMS = {"category": "linear", "symbol": "BTCUSDT", "limit": 1000}
RESET_IN_S = 30.0
ATTEMPTS = 4  # 1 + RestClientConfig.max_retries
IP_HOLD_S = 600.0  # 24-internal-schemas §8.6: 10018 holds the whole IP >= 10 min


def _headroom() -> float:
    return metric(bybit_rate_limit_remaining, scope="public", endpoint_class="market_data")


async def test_s05_burst_drains_bucket_counts_and_headroom_recovers(rig: Rig) -> None:
    feed = Feeder(rig.ex)
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    limited = metric(bybit_rate_limited_total, code="10018")
    rig.ex.inject(Fault(FaultKind.RATE_LIMIT, count=ATTEMPTS, path=PATH, reset_in_s=RESET_IN_S))

    call = spawn(rig.rest.get_public(PATH, params=PARAMS), name="s05-call")
    await feed.run_while(
        call, within_s=ATTEMPTS * (IP_HOLD_S + 60)
    )  # the venue keeps streaming meanwhile
    with pytest.raises(RateLimitError):
        call.result()
    assert metric(bybit_rate_limited_total, code="10018") == limited + ATTEMPTS
    assert _headroom() == 0.0  # IngestionRateLimitHeadroomExhausted fires (<= 1)
    assert rig.governor.remaining("public", EndpointClass.MARKET_DATA) < 1.0
    assert len(rig.ex.sockets) == 1, "a REST rate limit must never recycle the WS"

    await feed.run(IP_HOLD_S + 2.0)  # the IP hold lapses and the bucket refills (5 tokens/s)
    ok = spawn(rig.rest.get_public(PATH, params=PARAMS), name="s05-ok")
    await feed.run_while(ok, within_s=10)  # fault exhausted: 200 OK
    assert ok.result()["retCode"] == 0
    assert _headroom() > 1.0  # headroom recovered


async def test_s05_retry_waits_for_the_advertised_reset(rig: Rig) -> None:
    rig.ex.inject(Fault(FaultKind.RATE_LIMIT, count=1, path=PATH, reset_in_s=RESET_IN_S))
    start, first = rig.clock.now, len(rig.ex.rest_calls)
    await rig.call(rig.rest.get_public(PATH, params=PARAMS), within_s=IP_HOLD_S * 2)
    retry_at = rig.ex.rest_calls[first + 1][0]
    waited = retry_at - start
    assert waited >= max(RESET_IN_S, IP_HOLD_S), f"retried {waited:.1f}s after 10018"
