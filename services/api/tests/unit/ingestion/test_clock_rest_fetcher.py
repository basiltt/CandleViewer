"""Contract test for `rest_client_fetcher` — the adapter that turns
`BybitRestClient.get_public("/v5/market/time")` into the `ServerTimeFetcher`
protocol `ClockGuard` consumes (Test plan: "Contract: the `10002` path
exercised end-to-end with the REST client fixture" — this covers the
happy-path wiring; the retry/10002 path is covered in
`test_rest_client.py::test_signed_request_retries_once_on_clock_drift`,
E08-T02)."""

from __future__ import annotations

import httpx
import pytest
import respx

from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.ingestion.clock import (
    ClockGuard,
    ClockMeasurementUnavailableError,
    rest_client_fetcher,
)

BASE_URL = "https://api-demo.bybit.com"


def _client() -> BybitRestClient:
    return BybitRestClient(
        RestClientConfig(base_url=BASE_URL),
        governor=TokenBucketGovernor(default_capacity=1000.0, default_refill_per_s=1000.0),
    )


@pytest.mark.asyncio
@respx.mock
async def test_rest_client_fetcher_reads_timenano_and_feeds_clock_guard() -> None:
    respx.get(f"{BASE_URL}/v5/market/time").mock(
        return_value=httpx.Response(
            200,
            json={
                "retCode": 0,
                "retMsg": "OK",
                "result": {
                    "timeSecond": "1700000000",
                    "timeNano": "1700000000123456789",
                },
            },
        )
    )
    client = _client()
    try:
        guard = ClockGuard(rest_client_fetcher(client), sample_count=1)
        offset_us = await guard.measure_once()
        # server time is fixed; offset just needs to be a finite integer
        # derived from the mocked timeNano field, not raise.
        assert isinstance(offset_us, int)
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_rest_client_fetcher_falls_back_to_time_field_in_ms() -> None:
    respx.get(f"{BASE_URL}/v5/market/time").mock(
        return_value=httpx.Response(
            200, json={"retCode": 0, "retMsg": "OK", "result": {"time": "1700000000000"}}
        )
    )
    client = _client()
    try:
        guard = ClockGuard(rest_client_fetcher(client), sample_count=1)
        offset_us = await guard.measure_once()
        assert isinstance(offset_us, int)
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_rest_client_fetcher_offset_reflects_injected_skew_not_epoch() -> None:
    """Regression test for the review finding that `rest_client_fetcher`
    once sent `time.monotonic()` (arbitrary origin) as the "sent" timestamp
    compared against the server's real epoch time — that bug makes the
    computed offset roughly the size of the whole epoch (~1.7e9 s), which
    would make `assert_healthy()` always raise. Here the mocked server time
    is a real epoch value skewed by a known +250 ms from *now*, so a
    correct implementation reports an offset within a tight tolerance of
    250 ms, while the monotonic-origin bug would report an offset of
    roughly `time.time() - time.monotonic()` (many years)."""
    injected_skew_ms = 250
    fake_now_s = 1_700_000_000.0
    server_epoch_s = fake_now_s + injected_skew_ms / 1_000
    respx.get(f"{BASE_URL}/v5/market/time").mock(
        return_value=httpx.Response(
            200,
            json={
                "retCode": 0,
                "retMsg": "OK",
                "result": {"timeNano": str(int(server_epoch_s * 1_000_000_000))},
            },
        )
    )
    client = _client()
    try:
        guard = ClockGuard(
            rest_client_fetcher(client, wall_clock=lambda: fake_now_s, monotonic=lambda: 0.0),
            sample_count=1,
        )
        offset_us = await guard.measure_once()
        offset_ms = offset_us / 1_000
        # Fake wall clock and zero RTT: the offset is exact (±1 ms rounding),
        # and nowhere near the ~1.7e9 s error of the monotonic-origin bug.
        assert abs(offset_ms - injected_skew_ms) <= 1
        assert abs(offset_us) < 1_000_000_000
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_rest_client_fetcher_raises_when_no_time_field_present() -> None:
    respx.get(f"{BASE_URL}/v5/market/time").mock(
        return_value=httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": {}})
    )
    client = _client()
    try:
        guard = ClockGuard(rest_client_fetcher(client), sample_count=1)
        with pytest.raises(ClockMeasurementUnavailableError):
            await guard.measure_once()
    finally:
        await client.aclose()
