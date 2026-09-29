"""Response models for the api module (M23)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class BuildInfo(BaseModel):
    """Build/version metadata returned by health probes.

    Deliberately minimal (C-2.9 / security notes in E02-T05): no datastore
    versions or internal hostnames are exposed to an unauthenticated caller.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    git_sha: str
    version: str
    environment: str


class ReadyCheck(BaseModel):
    """A single named readiness sub-check (filled in by E04)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    ok: bool


class LivenessResponse(BuildInfo):
    """`GET /healthz` response body."""

    status: str = "ok"


class ReadinessResponse(BuildInfo):
    """`GET /readyz` response body.

    `mesh_binding_safe`/`mesh_reason_code` (E09-T04 deliverable: "the
    self-check result exposed on the health payload consumed by SCR-137
    Admin security centre and SCR-016 first-run wizard") surface the mesh
    guard's current `ReadOnlyGate` state so those screens have a data
    source without needing a second, mesh-specific endpoint. `None` when no
    mesh guard is wired (e.g. a bare `make_health_router()` call in a unit
    test that does not pass one) rather than a misleading default of
    `True`.
    """

    status: str = "ok"
    checks: list[ReadyCheck] = []
    mesh_binding_safe: bool | None = None
    mesh_reason_code: str | None = None
