"""SR-E12-09 / #2046: the REST body is byte-capped while streaming, before JSON decode."""

from __future__ import annotations

import json
import tracemalloc
from collections.abc import AsyncIterator, Callable

import httpx
import pytest

from candleviewer.exchange.base.errors import ExchangeError
from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient, RestBodyTooLarge

BASE_URL = "https://api-demo.bybit.com"
CAP = 2 * 1024 * 1024
CHUNK = 64 * 1024


class _Stream(httpx.AsyncByteStream):
    def __init__(self, total: int) -> None:
        self.total = total
        self.sent = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        while self.sent < self.total:
            n = min(CHUNK, self.total - self.sent)
            self.sent += n
            yield b"x" * n


def _client(
    handler: Callable[[httpx.Request], httpx.Response], sleeps: list[float]
) -> BybitRestClient:
    async def _sleep(s: float) -> None:
        sleeps.append(s)

    return BybitRestClient(
        RestClientConfig(base_url=BASE_URL, max_retries=3),
        governor=TokenBucketGovernor(default_capacity=1000.0, default_refill_per_s=1000.0),
        transport=httpx.MockTransport(handler),
        sleep=_sleep,
    )


@pytest.mark.asyncio
async def test_oversized_body_raises_typed_error_no_retry_no_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    stream = _Stream(200 * 1024 * 1024)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, stream=stream)

    def _boom(*_a: object, **_k: object) -> object:
        raise AssertionError("json decode attempted")

    monkeypatch.setattr("candleviewer.exchange.bybit.rest.json.loads", _boom)
    sleeps: list[float] = []
    client = _client(handler, sleeps)
    tracemalloc.start()
    try:
        with pytest.raises(RestBodyTooLarge) as ei:
            await client.get_public("/v5/market/kline")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        await client.aclose()
    assert isinstance(ei.value, ExchangeError)
    assert ei.value.retryable is False
    assert calls == 1 and sleeps == []
    assert stream.sent <= CAP + CHUNK  # aborted early, not drained
    assert peak < CAP + 4 * CHUNK + 1024 * 1024


@pytest.mark.asyncio
async def test_content_length_lie_is_still_capped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Length": "10"}, stream=_Stream(CAP + 1))

    client = _client(handler, [])
    try:
        with pytest.raises(RestBodyTooLarge):
            await client.get_public("/v5/market/kline")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_declared_oversize_rejected_early() -> None:
    stream = _Stream(CAP * 4)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Length": str(CAP * 4)}, stream=stream)

    client = _client(handler, [])
    try:
        with pytest.raises(RestBodyTooLarge):
            await client.get_public("/v5/market/kline")
    finally:
        await client.aclose()
    assert stream.sent == 0


@pytest.mark.asyncio
async def test_normal_kline_page_unaffected() -> None:
    rows = [["1700000000000", "1", "2", "0.5", "1.5", "10", "15"]] * 1000
    body = {"retCode": 0, "retMsg": "OK", "result": {"list": rows}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(body).encode())

    client = _client(handler, [])
    try:
        data = await client.get_public("/v5/market/kline")
    finally:
        await client.aclose()
    assert len(data["result"]["list"]) == 1000
