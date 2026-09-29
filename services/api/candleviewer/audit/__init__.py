"""audit module (M19).

Append-only, hash-chained audit writer and query API (E09-T02).

Public interface only — internal implementation modules are not re-exported.
Allowed dependencies (CONSTITUTION.md C-3.1): M1, M10. Only M21 (`admin`) and
M23 (`api`) may import this module's public names (C-3.3) to build the
`/admin/audit*` router; nothing else emits events by importing internals —
every other module reaches `AuditService` only via `AppContext.audit`.
"""

from __future__ import annotations

from candleviewer.audit.access import AuditAccessDenied, AuditPrincipal
from candleviewer.audit.models import (
    AuditEntry,
    AuditOutcome,
    AuditPage,
    ExportResult,
    Severity,
    VerifyResult,
)
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.service import AuditService
from candleviewer.audit.writer import AuditWriter

__all__: list[str] = [
    "AuditAccessDenied",
    "AuditEntry",
    "AuditOutcome",
    "AuditPage",
    "AuditPrincipal",
    "AuditQueryService",
    "AuditService",
    "AuditWriter",
    "ExportResult",
    "Severity",
    "VerifyResult",
]
