"""`POST /admin/support-bundle`, `GET /admin/support-bundle/{id}` (E04-S02).

RBAC `admin:read` (Owner-scoped), resolved server-side; denied attempts are
audited. Generation runs in the background (concurrency 1 -> 409). Success is
audited as `health.diagnostics_exported`. Nothing is ever uploaded.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.observability.support_bundle import BundleError, BundleJob, SupportBundleService

ADMIN_READ = "admin:read"
_STATUS = {
    "BUNDLE_ALREADY_RUNNING": 409,
    "BUNDLE_WINDOW_TOO_LARGE": 400,
    "BUNDLE_WINDOW_INVALID": 400,
}


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class _PrincipalResolver(Protocol):
    async def resolve(self, request: Request) -> AuditPrincipal | None: ...


class SupportBundleRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    from_: datetime
    to: datetime

    @classmethod
    def parse(cls, raw: bytes) -> SupportBundleRequest:
        import json

        data = json.loads(raw)
        if not isinstance(data, dict) or "from" not in data:
            raise ValueError("from/to required")
        data["from_"] = data.pop("from")
        return cls.model_validate(data)


def _problem(status: int, title: str, detail: str, code: str | None = None) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
    }
    if code:
        body["code"] = code
    return JSONResponse(status_code=status, content=body, media_type="application/problem+json")


def make_support_bundle_router(
    service: SupportBundleService,
    audit: _Emitter | None,
    principal_resolver: _PrincipalResolver | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["admin"])

    @router.post("/support-bundle")
    async def create(request: Request) -> JSONResponse:
        if principal_resolver is None:
            return _problem(501, "Not implemented", "no principal resolver wired")
        principal = await principal_resolver.resolve(request)
        if principal is None:
            return _problem(401, "Unauthorized", "no verified session for this request")
        if audit is None:
            return _problem(503, "Service unavailable", "audit backend is not wired")
        common: dict[str, Any] = {
            "actor_label": principal.username,
            "actor_user_id": principal.user_id,
            "actor_ip": principal.ip,
            "session_id": principal.session_id,
            "object_kind": "support_bundle",
            "request_id": principal.request_id,
        }
        if not principal.has(ADMIN_READ):
            await audit.emit(
                "health.diagnostics_exported",
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
                reason=f"missing_permission:{ADMIN_READ}",
                **common,
            )
            return _problem(403, "Forbidden", f"requires {ADMIN_READ}")
        try:
            body = SupportBundleRequest.parse(await request.body())
        except (ValidationError, ValueError):
            return _problem(400, "Bad request", "invalid support-bundle request")

        async def done(job: BundleJob) -> None:
            if job.status != "succeeded":
                await audit.emit(
                    "health.diagnostics_exported",
                    outcome=AuditOutcome.FAILURE,
                    severity=Severity.ERROR,
                    reason=job.error_code,
                    object_id=job.id,
                    **common,
                )
                return
            await audit.emit(
                "health.diagnostics_exported",
                object_id=job.id,
                after_state={
                    "from": body.from_.isoformat(),
                    "to": body.to.isoformat(),
                    "size_bytes": job.size_bytes,
                },
                **common,
            )

        try:
            job = service.start(body.from_, body.to, on_complete=done)
        except BundleError as exc:
            return _problem(_STATUS.get(exc.code, 400), "Bundle refused", str(exc), exc.code)
        return JSONResponse(status_code=202, content={"job_id": job.id})

    @router.get("/support-bundle/{job_id}")
    async def status(job_id: str, request: Request) -> JSONResponse:
        if principal_resolver is None:
            return _problem(501, "Not implemented", "no principal resolver wired")
        principal = await principal_resolver.resolve(request)
        if principal is None:
            return _problem(401, "Unauthorized", "no verified session for this request")
        if not principal.has(ADMIN_READ):
            return _problem(403, "Forbidden", f"requires {ADMIN_READ}")
        job = service.get(job_id)
        if job is None:
            return _problem(404, "Not found", "unknown support bundle job")
        return JSONResponse(job.view())

    return router
