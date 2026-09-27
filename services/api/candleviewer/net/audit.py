"""Narrow audit-emission protocol for the mesh guard.

The real audit module (append-only, hash-chained, C-2.9/C-3.3) is owned by
its own ticket and is not yet built. This module defines the minimal
`AuditSink` protocol the mesh guard depends on so it can be wired to the
real implementation later without churn, per each ticket's `## Agent-delivery
adaptations` on inter-ticket sequencing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class AuditSink(Protocol):
    """Minimal audit-emission surface the mesh guard depends on."""

    def emit(self, event: str, *, severity: str, **fields: object) -> None:
        """Emit one audit event. Implementations must never raise on I/O
        failure in a way that blocks the request path — the ticket's
        acceptance criteria require rejection to happen regardless of audit
        durability; a real sink is expected to buffer/retry out-of-band.
        """
        ...


class NullAuditSink:
    """Default no-op sink; used only until the real audit module is wired."""

    def emit(self, event: str, *, severity: str, **fields: object) -> None:
        return None


@dataclass
class InMemoryAuditSink:
    """Test double that records emitted events for assertions."""

    events: list[dict[str, object]] = field(default_factory=list)

    def emit(self, event: str, *, severity: str, **fields: object) -> None:
        self.events.append({"event": event, "severity": severity, **fields})
