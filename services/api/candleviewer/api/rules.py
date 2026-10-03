"""`GET /rules/vocabulary`, `GET /schemas/rule-ir.json` (E35-T03).

RBAC (C-12.4): `rules:read`, fail-closed like `api/ticker.py`. The response
varies per caller (availability annotations), hence `Cache-Control: private`
and an ETag over content + permission set. An empty registry -> `503` problem
document, never an empty catalogue (SCR-081 engine-offline state).
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from candleviewer.api.ticker import _Principal, _problem, _Resolver
from candleviewer.rules.ir.schema import to_json_schema
from candleviewer.rules.vocabulary import (
    MetricRegistry,
    VocabularyUnavailableError,
    build_vocabulary,
    etag_for,
)

_REQUIRED = "rules:read"
_ADVISORY_PERMISSIONS = ("orders:write", "rules.loosen_stop", "rules.arm_live")
_CACHE = "private, max-age=60"
_Counter = Callable[[str], None]


def make_rules_router(
    registry_provider: Callable[[], MetricRegistry | None],
    *,
    principal_resolver: _Resolver | None = None,
    recorded_symbols: Callable[[], frozenset[str]] = lambda: frozenset(),
    on_request: _Counter = lambda cache: None,
) -> APIRouter:
    router = APIRouter(tags=["rules"])

    async def _authorize(request: Request) -> tuple[_Principal | None, JSONResponse | None]:
        if principal_resolver is None:
            return None, _problem(501, "Not implemented", "no principal resolver wired")
        resolved = principal_resolver.resolve(request)
        principal: _Principal | None = await resolved if inspect.isawaitable(resolved) else resolved
        if principal is None:
            return None, _problem(401, "Unauthorized", "no verified session for this request")
        if not principal.has(_REQUIRED):
            return None, _problem(403, "Forbidden", f"requires {_REQUIRED}")
        return principal, None

    @router.get("/rules/vocabulary")
    async def get_vocabulary(request: Request, symbol: str | None = None) -> Response:
        principal, denied = await _authorize(request)
        if denied is not None or principal is None:
            return denied or _problem(401, "Unauthorized", "no session")
        if symbol is not None:
            if not (4 <= len(symbol) <= 20 and symbol.isascii() and symbol.isalnum()):
                return _problem(400, "Bad request", "invalid symbol")
            symbol = symbol.upper()
        registry = registry_provider()
        perms = frozenset(p for p in _ADVISORY_PERMISSIONS if principal.has(p))
        try:
            if registry is None:
                raise VocabularyUnavailableError("metric registry not wired")
            body: dict[str, Any] = build_vocabulary(
                registry, permissions=perms, symbol=symbol, recorded_symbols=recorded_symbols()
            )
        except VocabularyUnavailableError:
            return _problem(503, "Service unavailable", "rule engine vocabulary unavailable")
        etag = etag_for(body, perms, symbol)
        headers = {"ETag": etag, "Cache-Control": _CACHE, "Vary": "Authorization"}
        if request.headers.get("if-none-match") == etag:
            on_request("hit")
            return Response(status_code=304, headers=headers)
        on_request("miss")
        return Response(json.dumps(body), media_type="application/json", headers=headers)

    @router.get("/schemas/rule-ir.json")
    async def get_rule_ir_schema(request: Request) -> Response:
        _, denied = await _authorize(request)
        if denied is not None:
            return denied
        return JSONResponse(to_json_schema(), headers={"Cache-Control": _CACHE})

    return router


__all__ = ["make_rules_router"]
