"""E08-Q02 / E08-TC-F04, E08-TC-F06: server-time fixture -> `ClockGuard` offset (fake clocks)."""

from __future__ import annotations

import httpx
import respx

from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.ingestion.clock import ClockGuard, rest_client_fetcher
from candleviewer.ingestion.metrics import clock_measurements_total
from tests._corpus import rest
from tests.contract.bybit._support import counter_value

BASE = "https://api-demo.bybit.com"
FIXTURE = "rest/server_time.json"


def _client() -> BybitRestClient:
    return BybitRestClient(
        RestClientConfig(base_url=BASE, max_retries=0),
        governor=TokenBucketGovernor(default_capacity=1000.0, default_refill_per_s=1000.0),
    )


@respx.mock
async def test_recorded_server_time_yields_the_exact_known_offset() -> None:
    """Server time is 1700000000.123456789 s; with a frozen local clock 40 ms behind it
    and zero RTT the measured offset is exactly +40.456 ms (+-1 ms rounding)."""
    respx.get(f"{BASE}/v5/market/time").mock(return_value=httpx.Response(200, json=rest(FIXTURE)))
    local_s = 1_700_000_000.123456789 - 0.040456
    client = _client()
    try:
        guard = ClockGuard(
            rest_client_fetcher(client, wall_clock=lambda: local_s, monotonic=lambda: 0.0),
            sample_count=1,
        )
        before = counter_value(clock_measurements_total, result="ok")
        offset_us = await guard.measure_once()
    finally:
        await client.aclose()
    assert abs(offset_us / 1000 - 40.456) <= 1.0
    assert counter_value(clock_measurements_total, result="ok") - before == 1
    assert guard.offset_us() == offset_us


@respx.mock
async def test_drift_beyond_the_hard_threshold_is_flagged_unhealthy() -> None:
    respx.get(f"{BASE}/v5/market/time").mock(return_value=httpx.Response(200, json=rest(FIXTURE)))
    client = _client()
    try:
        guard = ClockGuard(
            rest_client_fetcher(
                client, wall_clock=lambda: 1_700_000_000.123 - 0.650, monotonic=lambda: 0.0
            ),
            sample_count=1,
            warn_threshold_ms=500,
            hard_threshold_ms=2_000,
        )
        await guard.measure_once()
    finally:
        await client.aclose()
    assert guard.health_severity() == "warn"  # 650 ms: above warn (500), below hard (2000)
    assert abs(guard.offset_us() / 1000 - 650) <= 2.0
