"""Private-bind listener, runtime wiring, import contract and scrape latency (E04-T03)."""

from __future__ import annotations

import asyncio
import re
import socket
import time
from pathlib import Path

import httpx
import pytest
from prometheus_client.parser import text_string_to_metric_families

from candleviewer.observability.metrics import Metrics, generate_latest
from candleviewer.observability.metrics_catalogue import live_specs, register_r0
from candleviewer.observability.metrics_server import (
    MetricsBindError,
    MetricsRuntime,
    make_metrics_app,
    parse_private_bind,
)


@pytest.mark.parametrize(
    "bind", ["127.0.0.1:9108", "10.0.0.5:9108", "100.64.1.2:9108", "[::1]:9108"]
)
def test_parse_private_bind_accepts_private(bind: str) -> None:
    host, port = parse_private_bind(bind)
    assert port == 9108 and host


@pytest.mark.parametrize(
    "bind",
    ["0.0.0.0:9108", "8.8.8.8:9108", "example.com:9108", "127.0.0.1", "127.0.0.1:0", ":9108"],
)
def test_parse_private_bind_rejects_public_or_malformed(bind: str) -> None:
    with pytest.raises(MetricsBindError):
        parse_private_bind(bind)


def test_no_module_outside_observability_imports_prometheus_client() -> None:
    root = Path(__file__).resolve().parents[3] / "candleviewer"
    pat = re.compile(r"^\s*(from|import)\s+prometheus_client\b", re.M)
    offenders = [
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if p.parent != root / "observability" and pat.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def test_runtime_serves_live_metrics_and_stops() -> None:
    metrics = Metrics("dev", process_collectors=True)
    runtime = MetricsRuntime(metrics, f"127.0.0.1:{_free_port()}")
    assert runtime.address[0] == "127.0.0.1"
    runtime.start()
    try:
        body = ""
        async with httpx.AsyncClient() as client:
            for _ in range(100):
                try:
                    r = await client.get(
                        f"http://{runtime.address[0]}:{runtime.address[1]}/metrics"
                    )
                    body = r.text
                    break
                except httpx.TransportError:
                    await asyncio.sleep(0.05)
        families = {f.name for f in text_string_to_metric_families(body)}
        for spec in live_specs():
            assert spec.name.removesuffix("_total") in families, spec.name
    finally:
        await runtime.stop()


@pytest.mark.perf
def test_scrape_latency_under_50ms_at_max_cardinality() -> None:
    metrics = Metrics("dev", process_collectors=True)
    r0 = register_r0(metrics)
    for spec in live_specs():
        if not spec.labels:
            continue
        metric = r0[spec.name]
        for i in range(spec.max_series):
            child = metric.labels(*[f"v{i}"] * len(spec.labels))
            if spec.kind == "histogram":
                child.observe(0.01)
            elif spec.kind == "counter":
                child.inc()
            else:
                child.set(1)
    app = make_metrics_app(metrics.registry)
    handler = next(r.endpoint for r in app.routes if getattr(r, "path", "") == "/metrics")
    samples = []
    for _ in range(10):
        t0 = time.perf_counter()
        handler()
        samples.append(time.perf_counter() - t0)
    samples.sort()
    median = samples[len(samples) // 2]
    print(f"scrape median={median * 1000:.1f}ms bytes={len(generate_latest(metrics.registry))}")
    assert median < 0.05
