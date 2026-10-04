"""Factories for the protected modules the composition root must inject.

CONSTITUTION.md C-3.2 lets only M4/M21 import M2 (`secrets`) and C-3.3 lets
only M21/M23 read M19 (`audit`). The composition root (`candleviewer.app`)
is neither, so it never imports those packages: it asks this M21 module to
construct them and injects the returned instances into `AppContext`
(`docs/plan/20-architecture.md` Sec.6.1, "everything is injected").

The type aliases let `app` annotate its fields without a direct import edge.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from candleviewer.audit.models import Severity
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


def audit_writer_sink(writer: Any) -> Callable[[str, dict[str, str]], Awaitable[None]]:
    """Adapt `AuditWriter.emit` (durable, write-ahead) to the scope audit port."""
    names = {
        "rule_scope_denied": "rules.scope_denied",
        "rule_live_scope_armed": "rules.live_scope_armed",
    }

    async def sink(event: str, data: dict[str, str]) -> None:
        await writer.emit(
            names[event],
            actor_label=data.get("caller", "unknown"),
            actor_user_id=data.get("caller"),
            object_kind="rule_scope",
            object_id=data.get("account") or data.get("environment"),
            severity=Severity.ERROR if data.get("severity") == "high" else Severity.WARNING,
            after_state=dict(data),
        )

    return sink
