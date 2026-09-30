"""Private-bind `/metrics` listener and runtime wiring (E04-T03 PR 2, US-OBS-001).

The listener serves the process-wide registry on `CV_METRICS_BIND` and refuses
to start on a public interface (`20-architecture.md` 13.1: an exposed
`/metrics` leaks order rates and trading activity). The loop-lag sampler,
cardinality check and fallback-snapshot ticker run alongside it.
"""

from __future__ import annotations

import asyncio
import ipaddress
from contextlib import suppress
from typing import Final

import uvicorn
from fastapi import FastAPI, Response

from candleviewer.observability.metrics import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Metrics,
    generate_latest,
)
from candleviewer.observability.metrics_catalogue import register_r0
from candleviewer.observability.metrics_runtime import (
    run_cardinality_check,
    run_fallback_snapshots,
    run_loop_lag_sampler,
)

#: Tailscale CGNAT range; private for our purposes though not `is_private`.
_CGNAT: Final = ipaddress.ip_network("100.64.0.0/10")


class MetricsBindError(ValueError):
    """`CV_METRICS_BIND` is malformed or names a non-private interface."""


def parse_private_bind(bind: str) -> tuple[str, int]:
    """Split `host:port`; reject anything that is not loopback/private/mesh."""
    host, sep, port_s = bind.rpartition(":")
    if not sep or not host or not port_s.isdigit() or not 0 < int(port_s) < 65536:
        raise MetricsBindError(f"CV_METRICS_BIND must be host:port, got {bind!r}")
    try:
        addr = ipaddress.ip_address(host.strip("[]"))
    except ValueError as exc:
        raise MetricsBindError(f"CV_METRICS_BIND host must be an IP literal, got {host!r}") from exc
    if addr.is_unspecified or not (addr.is_loopback or addr.is_private or addr in _CGNAT):
        raise MetricsBindError(f"CV_METRICS_BIND {host!r} is not a private interface")
    return host.strip("[]"), int(port_s)


def make_metrics_app(registry: CollectorRegistry) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    return app


class MetricsRuntime:
    """Owns the private listener and the three background metric tasks."""

    def __init__(self, metrics: Metrics, bind: str) -> None:
        self._host, self._port = parse_private_bind(bind)
        self.metrics = metrics
        self._r0 = register_r0(metrics)
        self._server: uvicorn.Server | None = None
        self._tasks: list[asyncio.Task[None]] = []

    @property
    def address(self) -> tuple[str, int]:
        return self._host, self._port

    def start(self) -> None:
        config = uvicorn.Config(
            make_metrics_app(self.metrics.registry),
            host=self._host,
            port=self._port,
            log_config=None,
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        loop_lag = self._r0["event_loop_lag_seconds"]
        self._tasks = [
            asyncio.create_task(self._server.serve(), name="metrics-listener"),
            asyncio.create_task(
                run_loop_lag_sampler(loop_lag, self.metrics.clock), name="metrics-loop-lag"
            ),
            asyncio.create_task(run_cardinality_check(self.metrics), name="metrics-cardinality"),
            asyncio.create_task(run_fallback_snapshots(self.metrics), name="metrics-fallback"),
        ]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        for task in self._tasks[1:]:
            task.cancel()
        for task in self._tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._tasks = []
        self._server = None
