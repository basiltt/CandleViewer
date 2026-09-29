"""Server-side RBAC for the `/admin/audit*` operations (C-12.4).

`docs/plan/22-api-openapi.yaml` declares `x-rbac: {permissions: [audit:read],
scope: none}` for query/verify and `[audit:export]` for export; the role →
permission table is `candleviewer/auth/rbac_seed.json` (owner `*`, viewer has
`audit:read`, manager has neither). `scope: none` means there is no
per-account narrowing: a caller either holds the permission for the whole
log or is refused — a manager can never read another account's (or any)
audit rows through this surface (ticket AC "Non-owner cannot read the audit
log").

Every denial is itself audited (`admin.audit_denied`, severity `warning`,
outcome `denied`) *before* `AuditAccessDenied` propagates to the HTTP edge,
which maps it to RFC 7807 `403`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal, Protocol

from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome, Severity

AuditPermission = Literal["audit:read", "audit:export"]

_OPERATION_PERMISSION: dict[str, AuditPermission] = {
    "query": "audit:read",
    "verify": "audit:read",
    "export": "audit:export",
}


@dataclass(frozen=True, slots=True)
class AuditPrincipal:
    """The authenticated caller, as resolved server-side from the session."""

    user_id: uuid.UUID
    username: str
    permissions: frozenset[str]
    session_id: uuid.UUID | None = None
    ip: str | None = None
    request_id: uuid.UUID | None = None

    def has(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions


class _Emitter(Protocol):
    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_user_id: uuid.UUID | None = ...,
        actor_ip: str | None = ...,
        session_id: uuid.UUID | None = ...,
        object_kind: str | None = ...,
        outcome: AuditOutcome = ...,
        severity: Severity = ...,
        reason: str | None = ...,
        request_id: uuid.UUID | None = ...,
    ) -> None: ...


class AuditAccessDenied(AuditError):
    """The caller lacks the permission for an `/admin/audit*` operation (→ 403)."""

    def __init__(self, operation: str, permission: str) -> None:
        super().__init__(f"audit {operation} requires {permission}")
        self.operation = operation
        self.permission = permission


async def authorize(principal: AuditPrincipal, operation: str, emitter: _Emitter) -> None:
    """Allow `operation` (`query`/`verify`/`export`) for `principal` or
    audit the denial and raise `AuditAccessDenied`. Unknown operations are
    denied (fail closed)."""
    permission = _OPERATION_PERMISSION.get(operation)
    if permission is not None and principal.has(permission):
        return
    required = permission or "<unknown-operation>"
    await emitter.emit(
        "admin.audit_denied",
        actor_label=principal.username,
        actor_user_id=principal.user_id,
        actor_ip=principal.ip,
        session_id=principal.session_id,
        object_kind="audit_log",
        outcome=AuditOutcome.DENIED,
        severity=Severity.WARNING,
        reason=f"missing_permission:{required}",
        request_id=principal.request_id,
    )
    raise AuditAccessDenied(operation, required)
