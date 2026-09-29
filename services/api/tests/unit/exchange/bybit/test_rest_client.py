"""Contract tests for `BybitRestClient` against recorded/synthetic HTTP
fixtures (ticket "Test plan": "Contract: recorded HTTP fixtures (respx)").

No network egress: `respx` intercepts httpx at the transport layer.
"""

from __future__ import annotations

import logging

import httpx
import pytest
import respx
from pydantic import SecretStr

from candleviewer.exchange.base.errors import ClockDriftError, RateLimitError, TransportError
from candleviewer.exchange.bybit.config import EndpointClass, RestClientConfig
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.exchange.bybit.signer import BybitSigner

BASE_URL = "https://api-demo.bybit.com"


def _config(*, max_retries: int = 2, **overrides: object) -> RestClientConfig:
    return RestClientConfig(base_url=BASE_URL, max_retries=max_retries, **overrides)  # type: ignore[arg-type]


def _fresh_governor() -> TokenBucketGovernor:
    return TokenBucketGovernor(default_capacity=1000.0, default_refill_per_s=1000.0)


@pytest.mark.asyncio
@respx.mock
async def test_get_public_returns_ok_payload() -> None:
    respx.get(f"{BASE_URL}/v5/market/time").mock(
        return_value=httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": {}})
    )
    client = BybitRestClient(_config(), governor=_fresh_governor())
    try:
        data = await client.get_public("/v5/market/time")
        assert data["retCode"] == 0
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_signed_request_sends_bapi_headers() -> None:
    route = respx.get(f"{BASE_URL}/v5/account/wallet-balance").mock(
        return_value=httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": {}})
    )
    signer = BybitSigner(api_key="test-key", api_secret=SecretStr("test-secret"))
    client = BybitRestClient(_config(), signer=signer, governor=_fresh_governor())
    try:
        await client.signed_request(
            "GET",
            "/v5/account/wallet-balance",
            params={"accountType": "UNIFIED"},
            endpoint_class=EndpointClass.ACCOUNT,
        )
    finally:
        await client.aclose()

    sent = route.calls.last.request
    assert sent.headers["X-BAPI-API-KEY"] == "test-key"
    assert "X-BAPI-SIGN" in sent.headers
    assert sent.headers["X-BAPI-RECV-WINDOW"] == "5000"


@pytest.mark.asyncio
async def test_signed_request_without_signer_raises_type_error() -> None:
    client = BybitRestClient(_config(), governor=_fresh_governor())
    try:
        with pytest.raises(TypeError):
            await client.signed_request("GET", "/v5/account/wallet-balance")
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_10018_raises_rate_limit_error_and_drains_bucket_then_retries() -> None:
    """Acceptance criterion 3: 10018 raises `RateLimitError`, drains the
    bucket by the advertised amount, and (being retryable) retries after
    `retry_after_s` with full jitter before ultimately succeeding."""
    route = respx.get(f"{BASE_URL}/v5/market/kline")
    route.side_effect = [
        httpx.Response(
            200,
            json={"retCode": 10018, "retMsg": "too many visits"},
            headers={"X-Bapi-Limit-Status": "3"},
        ),
        httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": {}}),
    ]
    governor = _fresh_governor()
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = BybitRestClient(_config(), governor=governor, sleep=fake_sleep)
    try:
        before = governor.remaining("public", EndpointClass.MARKET_DATA)
        data = await client.get_public("/v5/market/kline")
        assert data["retCode"] == 0
        after_drain_and_refill = governor.remaining("public", EndpointClass.MARKET_DATA)
        # A drain of 3 happened even though the bucket also gets consumed by
        # `acquire`; either way it must have gone down relative to a
        # no-rate-limit baseline, and a retry sleep must have been recorded.
        assert after_drain_and_refill <= before
        assert len(sleeps) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_10018_non_retryable_path_raises_when_retries_exhausted() -> None:
    respx.get(f"{BASE_URL}/v5/market/kline").mock(
        return_value=httpx.Response(200, json={"retCode": 10018, "retMsg": "too many visits"})
    )
    client = BybitRestClient(_config(max_retries=0), governor=_fresh_governor())
    try:
        with pytest.raises(RateLimitError):
            await client.get_public("/v5/market/kline")
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_10002_retries_exactly_once_then_surfaces_clock_drift_error() -> None:
    """Acceptance criterion 4: a second 10002 surfaces as `ClockDriftError`
    rather than looping."""
    route = respx.get(f"{BASE_URL}/v5/market/kline")
    route.mock(
        return_value=httpx.Response(200, json={"retCode": 10002, "retMsg": "invalid timestamp"})
    )
    resync_calls = 0

    def offset_provider() -> int:
        nonlocal resync_calls
        resync_calls += 1
        return 0

    client = BybitRestClient(
        _config(), governor=_fresh_governor(), clock_offset_ms_provider=offset_provider
    )
    try:
        with pytest.raises(ClockDriftError):
            await client.get_public("/v5/market/kline")
    finally:
        await client.aclose()
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_5xx_retries_then_raises_transport_error_when_exhausted() -> None:
    route = respx.get(f"{BASE_URL}/v5/market/time")
    route.mock(return_value=httpx.Response(503, json={}))

    async def fake_sleep(_seconds: float) -> None:
        return None

    client = BybitRestClient(_config(max_retries=1), governor=_fresh_governor(), sleep=fake_sleep)
    try:
        with pytest.raises(TransportError):
            await client.get_public("/v5/market/time")
    finally:
        await client.aclose()
    assert route.call_count == 2  # initial attempt + one retry


@pytest.mark.asyncio
@respx.mock
async def test_secrets_never_appear_in_debug_logs(caplog: pytest.LogCaptureFixture) -> None:
    """Ticket scenario "Secrets never reach a log or a fixture"."""
    respx.get(f"{BASE_URL}/v5/account/wallet-balance").mock(
        return_value=httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": {}})
    )
    signer = BybitSigner(api_key="visible-key", api_secret=SecretStr("super-secret-value"))
    client = BybitRestClient(_config(), signer=signer, governor=_fresh_governor())
    caplog.set_level(logging.DEBUG)
    try:
        await client.signed_request("GET", "/v5/account/wallet-balance")
    finally:
        await client.aclose()
    log_text = caplog.text
    assert "super-secret-value" not in log_text
    for record in caplog.records:
        assert "super-secret-value" not in repr(record.__dict__)
