"""Domain models for the observability module (M24).

`HealthReport`/`HealthStatus` are used by every module's `health()` lifecycle
method (docs/plan/20-architecture.md Sec.3 "Common conventions") so they live
here rather than being duplicated per module.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class HealthStatus(StrEnum):
    """Module health states surfaced by the supervisor and `/readyz`."""

    OK = "ok"
    DEGRADED = "degraded"
    STOPPED = "stopped"


class HealthReport(BaseModel):
    """A single module's health, as returned by its `health()` method."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    module: str
    status: HealthStatus
    detail: str = ""
