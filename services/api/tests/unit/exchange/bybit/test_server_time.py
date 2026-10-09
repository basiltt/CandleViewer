"""`BybitRestClient.server_time()` / `ServerTime` (E12 #2139): recorded `/v5/market/time` payload
-> normalised value; malformed payload -> the adapter's typed error, never a `KeyError`."""

from __future__ import annotations

import httpx
import pytest
import respx

from candleviewer.exchange.base.errors import UnknownStateError
from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.models import ServerTime
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient
from tests._corpus import rest

BASE_URL = "https://api-demo.bybit.com"


def _client() -> BybitRestClient:
    return BybitRestClient(
        RestClientConfig(base_url=BASE_URL, max_retries=0),
        governor=TokenBucketGovernor(default_capacity=1000.0, default_refill_per_s=1000.0),
    )


@pytest.mark.asyncio
@respx.mock
async def test_server_time_recorded_payload_yields_microseconds() -> None:
    respx.get(f"{BASE_URL}/v5/market/time").mock(
        return_value=httpx.Response(200, json=rest("rest/server_time.json"))
    )
    client = _client()
    try:
        server_time = await client.server_time()
    finally:
        await client.aclose()
    assert server_time.time_us == 1_700_000_000_123_456


def test_server_time_prefers_nano_then_second_then_ms() -> None:
    assert ServerTime(timeSecond="5", timeNano="5000000123").time_us == 5_000_000
    assert ServerTime(timeSecond="5").time_us == 5_000_000
    assert ServerTime(time="1700000000000").time_us == 1_700_000_000_000_000
    assert ServerTime(time=1700000000000).time_us == 1_700_000_000_000_000


@pytest.mark.parametrize(
    "payload",
    [
        {"retCode": 0, "retMsg": "OK"},  # no `result`
        {"retCode": 0, "result": {}},  # no usable time field
        {"retCode": 0, "result": None},
        {"retCode": 0, "result": {"timeNano": "not-a-number"}},
        {"retCode": 0, "result": {"timeNano": "1", "surprise": 1}},  # extra="forbid"
        {"retCode": 0, "result": {"timeNano": ["1"]}},  # wrong type
    ],
)
def test_server_time_malformed_payload_raises_typed_error(payload: dict[str, object]) -> None:
    with pytest.raises(UnknownStateError):
        ServerTime.from_response(payload)


@pytest.mark.asyncio
@respx.mock
async def test_server_time_malformed_http_payload_is_not_a_keyerror() -> None:
    respx.get(f"{BASE_URL}/v5/market/time").mock(
        return_value=httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": {}})
    )
    client = _client()
    try:
        with pytest.raises(UnknownStateError):
            await client.server_time()
    finally:
        await client.aclose()
