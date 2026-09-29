"""`POST /auth/login` (E09-S01, US-ONB-001).

Thin HTTP adapter over `candleviewer.auth.login_service.LoginService`:
translates typed domain errors to the RFC 7807-shaped problem responses the
ticket's acceptance criteria specify, and — when a live `AuditWriter` is
injected — emits `auth.login`/`auth.login_failed` (both already registered
in `candleviewer.audit.actions.AUDIT_ACTIONS`) per the Gherkin ("... is
audited" / "the attempt is audited with the source IP"). `api` (M23) is on
the allow-list to import `candleviewer.audit`; `auth` itself is not (see
`auth/login_service.py`'s module docstring) — that boundary is exactly why
the audit call lives in this router, not in `LoginService`. On the fake/CI
default backend (`audit_writer=None`) the route still works; it just skips
the audit call rather than failing the request (mirrors `AuthServiceLike`'s
own optionality).

Source IP resolution intentionally does not trust `X-Forwarded-For` unless
the deployment topology has a trusted reverse proxy configured elsewhere
(out of this ticket's scope, C-2.11); it reads `request.client.host`, which
is correct for CandleViewer's binding model (`127.0.0.1`/Tailscale — see
`50-security.md`).
"""

from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from candleviewer.audit.models import AuditOutcome
from candleviewer.auth.errors import AccountDisabled, AccountLocked, InvalidCredentials
from candleviewer.auth.models import LoginRequest, MfaChallengeResult


class LoginServiceLike(Protocol):
    """Structural type for `candleviewer.auth.login_service.LoginService`
    (no import edge needed beyond the one `auth.models`/`auth.errors`
    already require for the request/response/error shapes)."""

    async def login(self, request: LoginRequest, *, source_ip: str) -> MfaChallengeResult: ...


class AuthServiceLike(Protocol):
    @property
    def is_active(self) -> bool: ...

    @property
    def login(self) -> LoginServiceLike: ...


class AuditWriterLike(Protocol):
    """Structural type for `candleviewer.audit.writer.AuditWriter` (only the
    subset of its `emit()` keyword arguments this router actually passes)."""

    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_ip: str | None = None,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
    ) -> None: ...


class AuditServiceLike(Protocol):
    @property
    def is_active(self) -> bool: ...

    @property
    def writer(self) -> AuditWriterLike: ...


async def _audit(
    audit_service: AuditServiceLike | None,
    action: str,
    *,
    actor_label: str,
    actor_ip: str,
    outcome: AuditOutcome,
) -> None:
    if audit_service is None or not audit_service.is_active:
        return
    await audit_service.writer.emit(
        action, actor_label=actor_label, actor_ip=actor_ip, outcome=outcome
    )


def _problem(status_code: int, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"type": "about:blank", "title": title, "status": status_code, "detail": detail},
        media_type="application/problem+json",
    )


def make_auth_router(
    auth_service: AuthServiceLike, audit_service: AuditServiceLike | None = None
) -> APIRouter:
    """Bind `/auth/login` to a concrete `AuthService` instance."""
    router = APIRouter(tags=["auth"])

    @router.post("/auth/login")
    async def login(request: Request, body: LoginRequest) -> JSONResponse:
        if not auth_service.is_active:
            return _problem(503, "Service unavailable", "auth backend is not wired")

        source_ip = request.client.host if request.client is not None else "unknown"
        try:
            result = await auth_service.login.login(body, source_ip=source_ip)
        except InvalidCredentials as exc:
            await _audit(
                audit_service,
                "auth.login_failed",
                actor_label=body.identifier,
                actor_ip=source_ip,
                outcome=AuditOutcome.FAILURE,
            )
            return _problem(401, "Invalid credentials", str(exc))
        except AccountDisabled as exc:
            await _audit(
                audit_service,
                "auth.login_failed",
                actor_label=body.identifier,
                actor_ip=source_ip,
                outcome=AuditOutcome.DENIED,
            )
            return _problem(403, "Account disabled", str(exc))
        except AccountLocked as exc:
            await _audit(
                audit_service,
                "auth.login_failed",
                actor_label=body.identifier,
                actor_ip=source_ip,
                outcome=AuditOutcome.DENIED,
            )
            response = _problem(423, "Account locked", str(exc))
            response.headers["Retry-After"] = str(exc.retry_after_s)
            return response
        except NotImplementedError as exc:
            return _problem(501, "Not implemented", str(exc))

        await _audit(
            audit_service,
            "auth.login",
            actor_label=body.identifier,
            actor_ip=source_ip,
            outcome=AuditOutcome.SUCCESS,
        )
        return JSONResponse(
            status_code=200,
            content={
                "status": "mfa_required",
                "mfa_token": result.mfa_token,
                "methods": list(result.methods),
                "expires_in": result.expires_in,
            },
        )

    return router
