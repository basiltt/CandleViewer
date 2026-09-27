"""Prometheus gauge for the mesh-guard boot self-check."""

from __future__ import annotations

from prometheus_client import Gauge

net_binding_safe = Gauge(
    "net_binding_safe",
    "1 if the process's actual listening sockets are all loopback/mesh-only, 0 if a "
    "public wildcard bind (0.0.0.0 / ::) was detected. Set by the mesh-guard self-check.",
)
