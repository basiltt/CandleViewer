"""Health/build-info routes (E02-T05 acceptance criteria 3).

`/healthz` and `/readyz` are static responses here; E04 replaces the readyz
checks array with real probes (Postgres, QuestDB, exchange connectivity).
Neither route touches a datastore or the network — `create_app()` must be
constructible and servable with fakes only.
"""

from __future__ import annotations

from fastapi import APIRouter

from candleviewer.api.models import LivenessResponse, ReadinessResponse
from candleviewer.settings import Settings


def _build_info(settings: Settings) -> dict[str, str]:
    return {
        "git_sha": settings.git_sha,
        "version": settings.version,
        "environment": settings.environment.value,
    }


def make_health_router(settings: Settings) -> APIRouter:
    """Bind the health routes to a concrete `Settings` instance.

    Returned as a fresh router (rather than reusing the module-level
    `router`) so `create_app()` can inject settings without a global.
    """
    bound = APIRouter(tags=["health"])

    @bound.get("/healthz", response_model=LivenessResponse)
    def healthz() -> LivenessResponse:
        return LivenessResponse(**_build_info(settings))

    @bound.get("/readyz", response_model=ReadinessResponse)
    def readyz() -> ReadinessResponse:
        return ReadinessResponse(checks=[], **_build_info(settings))

    return bound
