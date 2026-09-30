"""`POST /auth/login` (E09-S01, US-ONB-001) and the E09-S02 (US-ONB-002/003)
MFA endpoints: `/auth/mfa/verify`, `/auth/mfa/enroll`,
`/auth/mfa/enroll/confirm`, `/auth/mfa/recovery`.

Thin HTTP adapter over `candleviewer.auth.login_service.LoginService` /
`candleviewer.auth.mfa_service.MfaService`: translates typed domain errors
to the RFC 7807-shaped problem responses the tickets' acceptance criteria
specify, and — when a live `AuditWriter` is injected — emits the
`auth.mfa_*` actions already registered in
`candleviewer.audit.actions.AUDIT_ACTIONS`. `api` (M23) is on the allow-list
to import `candleviewer.audit`; `auth` itself is not (see
`auth/login_service.py`'s module docstring) — that boundary is exactly why
the audit calls live in this router. On the fake/CI default backend
(`audit_writer=None`) the routes still work; they just skip the audit call.

**Deviation (documented per this repo's multi-agent protocol §5, "minor
gaps ... noted in the PR under Deviations"):** `/auth/mfa/enroll`,
`/auth/mfa/enroll/confirm` and `/auth/mfa/recovery`'s regeneration sibling
are `x-rbac scope: self` per `22-api-openapi.yaml`, which normally means
"the authenticated caller, resolved from their session". Real session
authentication (the `cv_refresh` cookie / bearer access token / RBAC
middleware) is E09-S03 scope, not yet merged. Pending that, these three
routes resolve the acting user from an `X-User-Id` header the composition
root's own auth middleware will supply once E09-S03 lands (today, in
tests, the caller passes it directly) — never from an unauthenticated
request body field. `/auth/mfa/verify` and `/auth/mfa/recovery`'s login
path need no such header: they resolve the user from the `mfa_token`
challenge alone, exactly like `/auth/login` needs no prior session.

Source IP resolution intentionally does not trust `X-Forwarded-For` unless
the deployment topology has a trusted reverse proxy configured elsewhere
(out of this ticket's scope, C-2.11); it reads `request.client.host`, which
is correct for CandleViewer's binding model (`127.0.0.1`/Tailscale — see
`50-security.md`).
"""

from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.errors import (
    AccountDisabled,
    AccountLocked,
    InvalidCredentials,
    MfaChallengeInvalid,
    MfaChallengeLocked,
    MfaCodeInvalid,
    MfaCodeReused,
    MfaEnrollmentNotFound,
    RecoveryCodeInvalid,
    RecoveryCodesExhausted,
)
from candleviewer.auth.models import (
    LoginRequest,
    MfaChallengeResult,
    MfaEnrollConfirmRequest,
    MfaEnrollRequest,
    MfaEnrollResult,
    MfaMethodKind,
    MfaRecoveryRequest,
    MfaVerifiedResult,
    MfaVerifyRequest,
)


class LoginServiceLike(Protocol):
    """Structural type for `candleviewer.auth.login_service.LoginService`
    (no import edge needed beyond the one `auth.models`/`auth.errors`
    already require for the request/response/error shapes)."""

    async def login(self, request: LoginRequest, *, source_ip: str) -> MfaChallengeResult: ...


class MfaServiceLike(Protocol):
    """Structural type for `candleviewer.auth.mfa_service.MfaService`."""

    async def verify(
        self, request: MfaVerifyRequest, *, account_name: str
    ) -> MfaVerifiedResult: ...

    async def enroll(
        self, user_id: str, request: MfaEnrollRequest, *, account_name: str
    ) -> MfaEnrollResult: ...

    async def confirm_enrollment(
        self, user_id: str, *, method_id: str, code: str
    ) -> tuple[MfaMethodKind, tuple[str, ...]]: ...

    async def recover(self, mfa_token: str, recovery_code: str) -> MfaVerifiedResult: ...


class AuthServiceLike(Protocol):
    @property
    def is_active(self) -> bool: ...

    @property
    def login(self) -> LoginServiceLike: ...

    @property
    def mfa_is_active(self) -> bool: ...

    @property
    def mfa(self) -> MfaServiceLike: ...


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
        severity: Severity = Severity.INFO,
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
    severity: Severity = Severity.INFO,
) -> None:
    if audit_service is None or not audit_service.is_active:
        return
    await audit_service.writer.emit(
        action, actor_label=actor_label, actor_ip=actor_ip, outcome=outcome, severity=severity
    )


def _problem(status_code: int, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"type": "about:blank", "title": title, "status": status_code, "detail": detail},
        media_type="application/problem+json",
    )


def _redact_identifier(identifier: str) -> str:
    """Best-effort redaction for the audit `actor_label` on a *failed*
    login (C-12.6: "never log ... into an audit record" anything that
    might be a credential). A failed attempt's identifier field may
    actually hold a password the user pasted into the wrong box, so unlike
    the success path (which audits the real, validated username) failure
    audit records only ever get a short, truncated, non-reversible label —
    enough to correlate repeated attempts, never enough to leak a secret."""
    if not identifier:
        return "(empty)"
    return f"{identifier[:3]}***(len={len(identifier)})"


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
                actor_label=_redact_identifier(body.identifier),
                actor_ip=source_ip,
                outcome=AuditOutcome.FAILURE,
            )
            return _problem(401, "Invalid credentials", str(exc))
        except AccountDisabled as exc:
            await _audit(
                audit_service,
                "auth.login_failed",
                actor_label=_redact_identifier(body.identifier),
                actor_ip=source_ip,
                outcome=AuditOutcome.DENIED,
            )
            return _problem(403, "Account disabled", str(exc))
        except AccountLocked as exc:
            await _audit(
                audit_service,
                "auth.account_locked",
                actor_label=_redact_identifier(body.identifier),
                actor_ip=source_ip,
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
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

    @router.post("/auth/mfa/verify")
    async def mfa_verify(body: MfaVerifyRequest) -> JSONResponse:
        if not auth_service.mfa_is_active:
            return _problem(503, "Service unavailable", "mfa backend is not wired")
        try:
            # `account_name` is not knowable from the challenge alone at
            # this layer without a user lookup this router does not own;
            # `MfaService.verify()` only needs it for `enroll()`'s
            # `otpauth_uri`, so a placeholder is harmless here.
            result = await auth_service.mfa.verify(body, account_name="")
        except (MfaChallengeInvalid, MfaChallengeLocked, MfaCodeInvalid, MfaCodeReused) as exc:
            await _audit(
                audit_service,
                "auth.mfa_failed",
                actor_label="(mfa_token)",
                actor_ip="unknown",
                outcome=AuditOutcome.FAILURE,
            )
            return _problem(401, "MFA verification failed", str(exc))

        await _audit(
            audit_service,
            "auth.mfa_verified",
            actor_label=str(result.user_id),
            actor_ip="unknown",
            outcome=AuditOutcome.SUCCESS,
        )
        return JSONResponse(status_code=200, content={"status": "authenticated"})

    @router.post("/auth/mfa/recovery")
    async def mfa_recovery(body: MfaRecoveryRequest) -> JSONResponse:
        if not auth_service.mfa_is_active:
            return _problem(503, "Service unavailable", "mfa backend is not wired")
        try:
            result = await auth_service.mfa.recover(body.mfa_token, body.recovery_code)
        except RecoveryCodesExhausted as exc:
            await _audit(
                audit_service,
                "auth.recovery_codes_exhausted",
                actor_label="(mfa_token)",
                actor_ip="unknown",
                outcome=AuditOutcome.DENIED,
                severity=Severity.ERROR,
            )
            return _problem(401, "Recovery codes exhausted", str(exc))
        except (MfaChallengeInvalid, MfaChallengeLocked, RecoveryCodeInvalid) as exc:
            await _audit(
                audit_service,
                "auth.mfa_failed",
                actor_label="(mfa_token)",
                actor_ip="unknown",
                outcome=AuditOutcome.FAILURE,
            )
            return _problem(401, "Recovery failed", str(exc))

        await _audit(
            audit_service,
            "auth.recovery_code_used",
            actor_label=str(result.user_id),
            actor_ip="unknown",
            outcome=AuditOutcome.SUCCESS,
            severity=Severity.WARNING,
        )
        return JSONResponse(
            status_code=200,
            content={
                "status": "authenticated",
                "forced_totp_reenroll": result.forced_totp_reenroll,
            },
        )

    @router.post("/auth/mfa/enroll", status_code=201)
    async def mfa_enroll(
        body: MfaEnrollRequest, x_user_id: str = Header(...), x_username: str = Header(...)
    ) -> JSONResponse:
        if not auth_service.mfa_is_active:
            return _problem(503, "Service unavailable", "mfa backend is not wired")
        result = await auth_service.mfa.enroll(x_user_id, body, account_name=x_username)
        return JSONResponse(
            status_code=201,
            content={
                "method_id": str(result.method_id),
                "method": result.method,
                "otpauth_uri": result.otpauth_uri,
                "recovery_codes": list(result.recovery_codes),
            },
        )

    @router.post("/auth/mfa/enroll/confirm")
    async def mfa_enroll_confirm(
        body: MfaEnrollConfirmRequest, x_user_id: str = Header(...)
    ) -> JSONResponse:
        if not auth_service.mfa_is_active:
            return _problem(503, "Service unavailable", "mfa backend is not wired")
        try:
            kind, recovery_codes = await auth_service.mfa.confirm_enrollment(
                x_user_id, method_id=str(body.method_id), code=body.code
            )
        except MfaEnrollmentNotFound as exc:
            return _problem(422, "Enrolment not found", str(exc))
        except MfaCodeInvalid as exc:
            return _problem(422, "Invalid code", str(exc))

        await _audit(
            audit_service,
            "auth.mfa_enrolled",
            actor_label=x_user_id,
            actor_ip="unknown",
            outcome=AuditOutcome.SUCCESS,
        )
        return JSONResponse(
            status_code=200,
            content={
                "id": str(body.method_id),
                "kind": kind,
                "active": True,
                "recovery_codes": list(recovery_codes),
            },
        )

    return router
