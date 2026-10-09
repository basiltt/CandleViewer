"""SR-041 CSRF enforcement at the HTTP edge (E09-X02 F-1, #2090).

`make_csrf_guard` is an HTTP middleware body (same shape as
`api.step_up.make_read_only_guard`). On every state-changing request
(anything but GET/HEAD/OPTIONS) it requires the `X-CSRF-Token` header to
equal the `cv_csrf` cookie (double-submit, constant-time compare). SR-041
names no auth-scheme exemption, so this applies to bearer-header requests
too; when a bearer session resolves, the token must also be bound to that
session (`CsrfTokens.bound_to`). Refusals are 403 problems with type
`CSRF_PROBLEM_TYPE` and an `auth.csrf_refused` audit record (C-2.9).

Exempt: the pre-session routes in `CSRF_EXEMPT_PATHS` (login and MFA
completion run before any session or token exists; they mint the first one).

`set_csrf_cookie` is called wherever a session is minted (login, MFA
verify, refresh) so the token rotates with the session. The cookie is NOT
HttpOnly (the web client must read it), `Secure`, `SameSite=Strict`, `Path=/`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER, CsrfTokens, tokens_match
from candleviewer.auth.errors import AuthError

CSRF_PROBLEM_TYPE = "https://candleviewer.local/errors/csrf_token_invalid"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_EXEMPT_PATHS = frozenset(
    {"/api/v1/auth/login", "/api/v1/auth/mfa/verify", "/api/v1/auth/mfa/recovery"}
)


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class _SessionsLike(Protocol):
    async def authenticate_access_token(self, raw_access_token: str) -> Any: ...


def set_csrf_cookie(response: Response, token: str, *, max_age: int) -> None:
    response.set_cookie(
        CSRF_COOKIE,
        token,
        max_age=max_age,
        httponly=False,
        secure=True,
        samesite="strict",
        path="/",
    )


def clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(CSRF_COOKIE, path="/", secure=True, samesite="strict")


def csrf_problem(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"type": CSRF_PROBLEM_TYPE, "title": "Forbidden", "status": 403, "detail": detail},
        media_type="application/problem+json",
    )


def _bearer(request: Request) -> str | None:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    return value.strip() or None if scheme.lower() == "bearer" else None


def make_csrf_guard(
    tokens: CsrfTokens,
    emitter: _Emitter,
    sessions: _SessionsLike | None = None,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    async def _refuse(request: Request, reason: str) -> Response:
        client = request.client.host if request.client is not None else None
        await emitter.emit(
            "auth.csrf_refused",
            actor_label="(unknown)",
            actor_ip=client,
            outcome=AuditOutcome.DENIED,
            severity=Severity.WARNING,
            reason=reason,
        )
        return csrf_problem(reason)

    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method in _SAFE_METHODS or request.url.path in CSRF_EXEMPT_PATHS:
            return await call_next(request)
        cookie = request.cookies.get(CSRF_COOKIE)
        header = request.headers.get(CSRF_HEADER)
        if not cookie or not header:
            return await _refuse(request, "csrf_token_missing")
        if not tokens_match(cookie, header):
            return await _refuse(request, "csrf_token_mismatch")
        bearer = _bearer(request)
        if bearer is not None and sessions is not None:
            try:
                record = await sessions.authenticate_access_token(bearer)
            except AuthError:
                record = None  # unauthenticated: the route answers 401 itself
            if record is not None and not tokens.bound_to(header, str(record.id)):
                return await _refuse(request, "csrf_token_unbound")
        return await call_next(request)

    return guard
