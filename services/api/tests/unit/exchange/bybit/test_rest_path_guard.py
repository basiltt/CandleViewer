"""#1891 / SR-040a: request paths can never steer a signed request off-host."""

from __future__ import annotations

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import SecretStr

from candleviewer.exchange.base.errors import ExchangeError
from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.rest import BybitRestClient, RestPathRejected, validate_rest_path
from candleviewer.exchange.bybit.signer import BybitSigner

BASE = "https://api.bybit.com"
BAD = [
    "https://api-demo.bybit.com/v5/x",
    "//evil.example/x",
    "//evil.example/v5/x",
    "https://evil.example/v5/y",
    "v5/market/time",
    "/v5/../x",
    "/v5/a//b",
    "/v5/" + chr(92) + "x",
    "/v5/a b",
    "/v5/a\n",
    "/v5/a\x00",
    "/v5/a?x=1",
    "/v5/%2e%2e/x",
    "/v5/",
    "",
]


def _client(hosts: list[str]) -> BybitRestClient:
    def handler(req: httpx.Request) -> httpx.Response:
        hosts.append(req.url.host)
        return httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": {}})

    signer = BybitSigner("DUMMYKEY" + "q" * 10, SecretStr("s" * 24))
    return BybitRestClient(
        RestClientConfig(base_url=BASE), signer=signer, transport=httpx.MockTransport(handler)
    )


@pytest.mark.parametrize("path", BAD)
async def test_signed_request_bad_path_rejected_before_send(path: str) -> None:
    hosts: list[str] = []
    async with _client(hosts) as c:
        with pytest.raises(RestPathRejected) as ei:
            await c.signed_request("GET", path)
    assert isinstance(ei.value, ExchangeError)
    assert "DUMMYKEY" not in str(ei.value) and "evil" not in str(ei.value)
    assert hosts == []


@pytest.mark.parametrize("path", BAD)
async def test_public_request_bad_path_rejected_before_send(path: str) -> None:
    hosts: list[str] = []
    async with _client(hosts) as c:
        with pytest.raises(RestPathRejected):
            await c.get_public(path)
    assert hosts == []


async def test_happy_path_unchanged() -> None:
    hosts: list[str] = []
    async with _client(hosts) as c:
        await c.get_public("/v5/market/time")
        await c.signed_request("GET", "/v5/account/wallet-balance")
    assert hosts == ["api.bybit.com", "api.bybit.com"]


@given(st.text())
def test_any_accepted_path_targets_base_host(path: str) -> None:
    try:
        validate_rest_path(path)
    except RestPathRejected:
        return
    client = httpx.Client(base_url=BASE)
    assert client.build_request("GET", path).url.host == "api.bybit.com"
