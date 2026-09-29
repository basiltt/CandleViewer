"""Domain models for the audit module (M19).

Pydantic v2 models for the WAL envelope (`AuditWalRecord`) and the query/verify
API surface (`AuditEntry`, `AuditPage`, `VerifyResult`, `ExportResult`),
matching `docs/plan/22-api-openapi.yaml` `AuditEntry`/`AuditOutcome`/`Severity`
schemas and `services/api/candleviewer/db/models.py`'s `audit_log` columns.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"


class Severity(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ExchangeEnv(StrEnum):
    LIVE = "live"
    DEMO = "demo"
    TESTNET = "testnet"


class AuditEmission(BaseModel):
    """The fully-validated, not-yet-persisted shape `audit.emit()` builds
    before it ever reaches the WAL or a connection. `before_state`/
    `after_state` here are already redacted (`candleviewer.audit.redact`) —
    the WAL never holds an unredacted secret."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: uuid.UUID
    action: str
    actor_user_id: uuid.UUID | None = None
    actor_label: str
    actor_ip: str | None = None
    session_id: uuid.UUID | None = None
    object_kind: str | None = None
    object_id: str | None = None
    object_label: str | None = None
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    severity: Severity = Severity.INFO
    reason: str | None = None
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    request_id: uuid.UUID | None = None
    env: ExchangeEnv | None = None
    event_ts: datetime


class AuditEntry(BaseModel):
    """Mirrors `docs/plan/22-api-openapi.yaml` `#/components/schemas/AuditEntry`."""

    model_config = ConfigDict(frozen=True)

    id: int
    ts: datetime
    actor_user_id: uuid.UUID | None
    actor_username: str | None = None
    action: str
    subject_type: str | None = None
    subject_id: str | None = None
    outcome: AuditOutcome
    severity: Severity
    ip: str | None
    user_agent: str | None = None
    request_id: str | None
    detail: dict[str, Any] = Field(default_factory=dict)
    entry_hash: str
    prev_hash: str | None


#: Upper bound on one `GET /admin/audit` page (PR #1561 finding 5).
AUDIT_QUERY_MAX_LIMIT = 1000


class AuditQueryRequest(BaseModel):
    """Validated filter set for `AuditQueryService.query` — `limit` bounded
    to 1..`AUDIT_QUERY_MAX_LIMIT`, unknown keys rejected."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor_user_id: str | None = None
    actions: list[str] | None = None
    severity: Severity | None = None
    outcome: AuditOutcome | None = None
    from_ts: datetime | None = None
    to_ts: datetime | None = None
    cursor: int | None = Field(default=None, ge=1)
    limit: int = Field(default=50, ge=1, le=AUDIT_QUERY_MAX_LIMIT)


class AuditPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[AuditEntry]
    chain_verified: bool
    next_cursor: str | None = None
    has_more: bool = False
    count: int = 0


class VerifyResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    verified: bool
    entries_checked: int
    first_bad_id: int | None
    checked_at: datetime


class ExportResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: uuid.UUID
    download_url: str | None = None
