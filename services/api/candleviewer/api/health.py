"""Health/build-info routes (E02-T05 acceptance criteria 3).

`/healthz` and `/readyz` are static responses here; E04 replaces the readyz
checks array with real probes (Postgres, QuestDB, exchange connectivity).
Neither route touches a datastore or the network — `create_app()` must be
constructible and servable with fakes only.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest

from candleviewer.api.models import LivenessResponse, ReadinessResponse
from candleviewer.settings import Settings


def _build_info(settings: Settings) -> dict[str, str]:
    return {
        "git_sha": settings.git_sha,
        "version": settings.version,
        "environment": settings.environment.value,
    }


def make_health_router(settings: Settings, metrics: CollectorRegistry | None = None) -> APIRouter:
    """Bind the health/metrics routes to a concrete `Settings` instance.

    Returned as a fresh router (rather than reusing the module-level
    `router`) so `create_app()` can inject settings without a global.
    `metrics` is the `AppContext.metrics` registry (E02-T05); `/metrics` is
    the Prometheus scrape target `infra/prometheus/prometheus.yml` polls at
    `api:8000/metrics` (E02-T08 acceptance criteria). Falls back to the
    default global registry when not supplied so this router stays usable
    standalone (e.g. in unit tests that only exercise `make_health_router`).
    """
    bound = APIRouter(tags=["health"])
    registry = metrics if metrics is not None else CollectorRegistry()

    @bound.get("/healthz", response_model=LivenessResponse)
    def healthz() -> LivenessResponse:
        return LivenessResponse(**_build_info(settings))

    @bound.get("/readyz", response_model=ReadinessResponse)
    def readyz() -> ReadinessResponse:
        return ReadinessResponse(checks=[], **_build_info(settings))

    @bound.get("/metrics")
    def metrics_endpoint() -> Response:
        return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    return bound
