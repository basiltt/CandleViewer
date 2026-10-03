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
from typing import Any, Protocol
from uuid import UUID

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from candleviewer.rules.compiler import compile_form, compile_graph
from candleviewer.rules.compiler.common import build_rule, check_bounds
from candleviewer.rules.ir import ir_hash
from candleviewer.rules.ir.schema import to_json_schema
from candleviewer.rules.issues import RuleCompileError
from candleviewer.rules.validator import validate_rule
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


class _Principal(Protocol):
    def has(self, permission: str) -> bool: ...


class _Resolver(Protocol):
    """Sync or async resolver (`resolve(request)` may return an awaitable)."""

    def resolve(self, request: Request) -> Any: ...


def _problem(status: int, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={"type": "about:blank", "title": title, "status": status, "detail": detail},
    )


def make_rules_router(
    registry_provider: Callable[[], MetricRegistry | None],
    *,
    principal_resolver: _Resolver | None = None,
    recorded_symbols: Callable[[], frozenset[str]] = lambda: frozenset(),
    on_request: _Counter = lambda cache: None,
    on_compile: Callable[[str, str], None] = lambda editor, result: None,
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

    async def _json_body(request: Request) -> dict[str, Any] | None:
        try:
            body = await request.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    def _invalid(exc: RuleCompileError) -> JSONResponse:
        n = len(exc.issues)
        return JSONResponse(
            status_code=422,
            media_type="application/problem+json",
            content={
                "type": "https://candleviewer.local/errors/rule_ir_invalid",
                "title": "Rule intermediate representation failed semantic validation",
                "status": 422,
                "detail": f"{n} error{'s' if n != 1 else ''} in the rule IR.",
                "code": "rule_ir_invalid",
                "errors": [
                    {"field": i.path, "rule": i.code, "message": i.message,
                     "node_ids": list(i.node_ids)}
                    for i in exc.issues
                ],
            },
        )  # fmt: skip

    @router.post("/rules/validate")
    async def post_validate(request: Request) -> Response:
        principal, denied = await _authorize(request)
        if denied is not None or principal is None:
            return denied or _problem(401, "Unauthorized", "no session")
        registry = registry_provider()
        if registry is None:
            return _problem(503, "Service unavailable", "rule engine vocabulary unavailable")
        body = await _json_body(request)
        if body is None or not isinstance(body.get("ir"), dict) or set(body) - {"ir", "scope"}:
            return _problem(400, "Bad request", "body must be an object with an 'ir' object")
        perms = frozenset(p for p in _ADVISORY_PERMISSIONS if principal.has(p))
        try:
            check_bounds(body["ir"], "rule")
            rule = build_rule(body["ir"])
        except RuleCompileError as exc:  # a failing IR is still a 200 with valid=false
            errs = [i.to_dict() for i in exc.issues]
            return JSONResponse(
                {"valid": False, "errors": errs, "warnings": [], "referenced_variables": [],
                 "referenced_actions": [], "estimated_evaluations_per_minute": 0}
            )  # fmt: skip
        result = validate_rule(rule, registry, perms)
        return JSONResponse(result.to_dict())

    @router.post("/rules/{ruleId}/compile")
    async def post_compile(ruleId: UUID, request: Request) -> Response:  # noqa: N803
        principal, denied = await _authorize(request)
        if denied is not None or principal is None:
            return denied or _problem(401, "Unauthorized", "no session")
        registry = registry_provider()
        if registry is None:
            return _problem(503, "Service unavailable", "rule engine vocabulary unavailable")
        body = await _json_body(request)
        editor = body.get("editor") if body else None
        model = body.get("model") if body else None
        if body is None or editor not in ("form", "graph") or not isinstance(model, dict):
            return _problem(400, "Bad request", "body needs 'editor' (form|graph) and 'model'")
        perms = frozenset(p for p in _ADVISORY_PERMISSIONS if principal.has(p))
        compile_fn = compile_form if editor == "form" else compile_graph
        try:
            rule = compile_fn(model, ruleId)
        except RuleCompileError as exc:
            on_compile(editor, "invalid")
            return _invalid(exc)
        result = validate_rule(rule, registry, perms)
        on_compile(editor, "ok" if result.valid else "issues")
        issues = [*result.errors, *result.warnings]
        return JSONResponse(
            {"ir": json.loads(rule.model_dump_json()), "ir_hash": ir_hash(rule),
             "issues": [i.to_dict() for i in issues]}
        )  # fmt: skip

    @router.get("/schemas/rule-ir.json")
    async def get_rule_ir_schema(request: Request) -> Response:
        _, denied = await _authorize(request)
        if denied is not None:
            return denied
        return JSONResponse(to_json_schema(), headers={"Cache-Control": _CACHE})

    return router


__all__ = ["make_rules_router"]
