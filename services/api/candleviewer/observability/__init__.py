"""observability module (M24).

Structured logging, redaction filters, metrics, tracing.

Public interface only — internal implementation modules are not re-exported.
Allowed dependencies (CONSTITUTION.md C-3.1): M1.

This module is a conforming EMPTY module scaffolded by E02-T05
(docs/plan/backlog/all-tickets.json). Real logic lands in the epic that owns
this module (see docs/plan/20-architecture.md Sec.3 and the module table in
CONSTITUTION.md Sec.3). Do not add business logic here without a linked
ticket.
"""

from __future__ import annotations

from candleviewer.observability.health import HealthReport, HealthStatus

__all__ = ["HealthReport", "HealthStatus"]
