"""Factories for the protected modules the composition root must inject.

CONSTITUTION.md C-3.2 lets only M4/M21 import M2 (`secrets`) and C-3.3 lets
only M21/M23 read M19 (`audit`). The composition root (`candleviewer.app`)
is neither, so it never imports those packages: it asks this M21 module to
construct them and injects the returned instances into `AppContext`
(`docs/plan/20-architecture.md` Sec.6.1, "everything is injected").

The type aliases let `app` annotate its fields without a direct import edge.
"""

from __future__ import annotations

from candleviewer.audit.repository import AuditRepository
from candleviewer.audit.service import AuditService
from candleviewer.secrets.service import SecretsService

SecretsHandle = SecretsService
AuditHandle = AuditService


def build_secrets_service() -> SecretsHandle:
    """Construct the M2 scaffold. No I/O; no key material is touched."""
    return SecretsService()


def build_audit_service(repository: AuditRepository | None = None) -> AuditHandle:
    """Construct M19. No I/O. With a repository (storage_backend=real, QA
    #1658) `start()` wires the real WAL-backed `AuditWriter`; without one it
    stays the scaffold."""
    return AuditService(repository)
