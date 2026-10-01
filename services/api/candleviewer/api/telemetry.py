"""`POST /telemetry/frontend` (E04-T06, ADR-0014 §2, threat A-17).

Authenticated via an injected session resolver (same fail-closed pattern as
`api/log_level.py`: `501` until wired, `401` with no session). The body is
size-capped *before* parsing, rate-limited per session, schema-closed, and
every rejection is counted under a closed reason — never logged verbatim.
"""

from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from candleviewer.observability.telemetry import (
    MAX_PAYLOAD_BYTES,
    PUSH_INTERVAL_S,
    FrontendTelemetry,
    SessionRateLimiter,
    TelemetrySink,
)


class _SessionResolver(Protocol):
    async def resolve_session_key(self, request: Request) -> str | None: ...


class _Principal(Protocol):
    @property
    def user_id(self) -> object: ...

    @property
    def session_id(self) -> object | None: ...


class _PrincipalResolver(Protocol):
    async def resolve(self, request: Request) -> _Principal | None: ...


class SessionKeyResolver:
    """Adapts the session-backed principal resolver to a rate-limit key.

    The key is the session id (falling back to the user id); it is used only
    as an in-memory limiter key, never as a metric label or log field.
    """

    def __init__(self, principals: _PrincipalResolver) -> None:
        self._principals = principals

    async def resolve_session_key(self, request: Request) -> str | None:
        principal = await self._principals.resolve(request)
        if principal is None:
            return None
        return str(principal.session_id or principal.user_id)


def _problem(
    status: int, title: str, code: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"type": "about:blank", "title": title, "status": status, "code": code},
        media_type="application/problem+json",
        headers=headers,
    )


def make_telemetry_router(
    sink: TelemetrySink,
    limiter: SessionRateLimiter,
    session_resolver: _SessionResolver | None = None,
    *,
    enabled: bool = True,
) -> APIRouter:
    router = APIRouter(tags=["admin"])

    @router.post("/telemetry/frontend", response_model=None)
    async def post_frontend_telemetry(request: Request) -> Response:
        if not enabled:
            return Response(status_code=204)
        if session_resolver is None:
            return _problem(501, "Not implemented", "not_implemented")
        key = await session_resolver.resolve_session_key(request)
        if key is None:
            sink.reject("unauthenticated")
            return _problem(401, "Unauthorized", "unauthenticated")
        declared = request.headers.get("content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > MAX_PAYLOAD_BYTES):
            sink.reject("too_large")
            return _problem(400, "Bad request", "payload_too_large")
        if not limiter.allow(key):
            sink.reject("rate_limited")
            return _problem(
                429,
                "Too many requests",
                "rate_limited",
                headers={"Retry-After": str(int(PUSH_INTERVAL_S))},
            )
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_PAYLOAD_BYTES:
                sink.reject("too_large")
                return _problem(400, "Bad request", "payload_too_large")
        try:
            payload = FrontendTelemetry.model_validate_json(bytes(body))
        except ValidationError:
            sink.reject("invalid")
            return _problem(400, "Bad request", "validation_failed")
        if not payload.bucket_lengths_ok():
            sink.reject("invalid")
            return _problem(400, "Bad request", "validation_failed")
        sink.ingest(payload)
        return Response(status_code=204)

    return router
