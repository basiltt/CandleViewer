"""api module (M23) — HTTP routers.

Contract-first routers, WS topics, serialisation, authz enforcement.

Public interface only — internal implementation modules are not re-exported.
Allowed dependencies (CONSTITUTION.md C-3.1): all modules' public interfaces.

This module is a conforming EMPTY module scaffolded by E02-T05
(docs/plan/backlog/all-tickets.json), except for the `/healthz`, `/readyz`
and build-info routes which E02-T05 implements per its acceptance criteria.
Real business routers land in the epics that own each resource (see
docs/plan/22-api-openapi.yaml and docs/plan/20-architecture.md Sec.3).
"""

from __future__ import annotations

from candleviewer.api.audit import make_audit_router
from candleviewer.api.auth import make_auth_router
from candleviewer.api.health import make_health_router
from candleviewer.api.instruments import make_instruments_router
from candleviewer.api.log_level import make_log_level_router
from candleviewer.api.market import make_market_router
from candleviewer.api.rbac_conformance import (
    assert_vocabulary_single_source,
    find_undeclared_routes,
)

__all__ = [
    "assert_vocabulary_single_source",
    "find_undeclared_routes",
    "make_audit_router",
    "make_auth_router",
    "make_health_router",
    "make_instruments_router",
    "make_log_level_router",
    "make_market_router",
]
