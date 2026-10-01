"""Prometheus bindings for the health registry (E04-T04 "Observability")."""

from __future__ import annotations

from candleviewer.observability.health_probes import ComponentState, HealthRegistry
from candleviewer.observability.metrics import CollectorRegistry, Gauge, Histogram
from candleviewer.settings import Settings

_GAUGE_VALUE = {
    ComponentState.HEALTHY: 0,
    ComponentState.NOT_DEPLOYED: 0,
    ComponentState.DEGRADED: 1,
    ComponentState.WARNING: 2,
    ComponentState.DOWN: 3,
}


def bind_health_metrics(
    registry: HealthRegistry, metrics: CollectorRegistry, settings: Settings
) -> None:
    """`build_info{version,commit,env}` (const 1), `health_component_state`
    (0 healthy .. 3 down) and `health_probe_duration_seconds`."""
    build_info = Gauge(
        "build_info",
        "Build metadata; constant 1.",
        ["version", "commit", "env"],
        registry=metrics,
    )
    build_info.labels(settings.version, settings.git_sha, settings.environment.value).set(1)
    state = Gauge(
        "health_component_state",
        "Component state: 0 healthy, 1 degraded, 2 warning, 3 down.",
        ["component"],
        registry=metrics,
    )
    duration = Histogram(
        "health_probe_duration_seconds",
        "Wall time of one health probe.",
        ["component"],
        registry=metrics,
    )
    registry.state_observer = lambda name, st: state.labels(name).set(_GAUGE_VALUE[st])
    registry.duration_observer = lambda name, secs: duration.labels(name).observe(secs)
