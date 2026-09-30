"""`PUT /admin/log-level` (E04-T02): scoped, self-reverting log-level override.

RBAC `admin:write`, resolved server-side via an injected `PrincipalResolver`
(same fail-closed pattern as `api/audit.py`: `501` when none is wired, `401`
when no session). Every attempt is audited as `settings.change` — a denied
attempt with outcome `denied`.
"""

from __future__ import annotations

from typing import Any, Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.observability.log_level import LogLevelOverrides, LogLevelRequest

ADMIN_WRITE = "admin:write"


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class _PrincipalResolver(Protocol):
    def resolve(self, request: Request) -> AuditPrincipal | None: ...


def _problem(status: int, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"type": "about:blank", "title": title, "status": status, "detail": detail},
        media_type="application/problem+json",
    )


def make_log_level_router(
    overrides: LogLevelOverrides,
    audit: _Emitter | None,
    principal_resolver: _PrincipalResolver | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["admin"])

    @router.put("/log-level")
    async def put_log_level(request: Request) -> JSONResponse:
        if principal_resolver is None:
            return _problem(501, "Not implemented", "no principal resolver wired")
        principal = principal_resolver.resolve(request)
        if principal is None:
            return _problem(401, "Unauthorized", "no verified session for this request")
        if audit is None:
            return _problem(503, "Service unavailable", "audit backend is not wired")
        common: dict[str, Any] = {
            "actor_label": principal.username,
            "actor_user_id": principal.user_id,
            "actor_ip": principal.ip,
            "session_id": principal.session_id,
            "object_kind": "log_level",
            "request_id": principal.request_id,
        }
        if not principal.has(ADMIN_WRITE):
            await audit.emit(
                "settings.change",
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
                reason=f"missing_permission:{ADMIN_WRITE}",
                **common,
            )
            return _problem(403, "Forbidden", f"requires {ADMIN_WRITE}")
        try:
            body = LogLevelRequest.model_validate_json(await request.body())
        except ValidationError:
            return _problem(400, "Bad request", "invalid log-level request")
        # Audit write-ahead (C-2.9): refuse the change if it cannot be recorded.
        await audit.emit(
            "settings.change",
            object_id=body.subsystem,
            after_state={"level": body.level, "ttl_seconds": body.ttl_seconds},
            **common,
        )
        await overrides.apply(body)
        return JSONResponse(
            status_code=200,
            content={
                "subsystem": body.subsystem,
                "level": body.level,
                "ttl_seconds": body.ttl_seconds,
            },
        )

    return router
