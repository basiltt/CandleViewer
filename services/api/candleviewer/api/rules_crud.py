"""`/rules` store, versions, active-version and mode routes (E35-S01).

Thin HTTP adapter over `rules.manager.RulesManager` (`22-api-openapi.yaml`
`listRules`..`setRuleMode`). Authorization is server-side (C-12.4): the injected
`actor_resolver` returns the caller's `Actor` (permissions, granted accounts, owner flag,
fresh step-up) or `None` (401). `rules:read` gates reads, `rules:write` gates writes;
live arming additionally needs `rules:arm_live` + a fresh one-shot step-up, enforced by the
manager's synchronous arming check (statecharts record, code enforces - C-2.21).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from candleviewer.rules.manager import Actor, RuleError, RulesManager

_READ = "rules:read"
_WRITE = "rules:write"


def _problem(status: int, code: str, title: str, detail: str, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"https://candleviewer.local/errors/{code}",
            "title": title,
            "status": status,
            "code": code,
            "detail": detail,
            **extra,
        },
    )


def _from_error(exc: RuleError) -> JSONResponse:
    return _problem(
        exc.status, exc.code, exc.code.replace("_", " ").capitalize(), exc.message, **exc.extra
    )


def _doc(body: dict[str, Any]) -> dict[str, Any] | None:
    ir = body.get("ir")
    if not isinstance(ir, dict):
        return None
    doc = dict(ir)
    if isinstance(body.get("name"), str):
        doc["name"] = body["name"]
    if "scope" not in doc and isinstance(body.get("scope"), str):
        doc["scope"] = {"level": body["scope"]}
    return doc


def make_rules_crud_router(
    manager_provider: Callable[[], RulesManager | None],
    actor_resolver: Callable[[Request], Any] | None,
) -> APIRouter:
    router = APIRouter(tags=["rules"])

    async def _gate(request: Request, perm: str) -> tuple[Actor, RulesManager] | JSONResponse:
        if actor_resolver is None:
            return _problem(
                501, "not_implemented", "Not implemented", "no principal resolver wired"
            )
        got = actor_resolver(request)
        actor: Actor | None = await got if inspect.isawaitable(got) else got
        if actor is None:
            return _problem(401, "unauthorized", "Unauthorized", "no verified session")
        if perm not in actor.perms:
            return _problem(403, "forbidden", "Forbidden", f"requires {perm}")
        mgr = manager_provider()
        if mgr is None:
            return _problem(503, "service_unavailable", "Unavailable", "rule engine unavailable")
        return actor, mgr

    async def _body(request: Request) -> dict[str, Any] | None:
        try:
            body = await request.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    def _bad(detail: str) -> JSONResponse:
        return _problem(400, "validation_failed", "Bad request", detail)

    @router.get("/rules")
    async def list_rules(
        request: Request,
        mode: str | None = None,
        scope: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Response:
        g = await _gate(request, _READ)
        if isinstance(g, JSONResponse):
            return g
        actor, mgr = g
        page = await mgr.list_rules(actor, mode, scope, cursor, max(1, min(limit, 200)))
        return JSONResponse(
            {
                "items": page["items"],
                "meta": {
                    "next_cursor": page["next_cursor"],
                    "has_more": page["next_cursor"] is not None,
                    "count": len(page["items"]),
                },
            }
        )

    @router.post("/rules")
    async def create_rule(request: Request) -> Response:
        g = await _gate(request, _WRITE)
        if isinstance(g, JSONResponse):
            return g
        actor, mgr = g
        body = await _body(request)
        doc = _doc(body) if body is not None else None
        if body is None or doc is None:
            return _bad("body needs an 'ir' object")
        try:
            return JSONResponse(await mgr.create(doc, actor, str(body.get("note", ""))), 201)
        except RuleError as exc:
            return _from_error(exc)

    @router.get("/rules/{ruleId}")
    async def get_rule(ruleId: UUID, request: Request) -> Response:
        g = await _gate(request, _READ)
        if isinstance(g, JSONResponse):
            return g
        actor, mgr = g
        try:
            return JSONResponse(await mgr.get(str(ruleId), actor))
        except RuleError as exc:
            return _from_error(exc)

    @router.put("/rules/{ruleId}")
    async def update_rule(ruleId: UUID, request: Request) -> Response:
        g = await _gate(request, _WRITE)
        if isinstance(g, JSONResponse):
            return g
        actor, mgr = g
        body = await _body(request)
        doc = _doc(body) if body is not None else None
        raw = request.headers.get("if-match", "").strip().strip('"')
        if raw == "" and body is not None:
            raw = str(body.get("expected_version", ""))
        if body is None or doc is None:
            return _bad("body needs an 'ir' object")
        if not raw.isdigit():
            return _bad("send the version you edited in If-Match (or expected_version)")
        try:
            out = await mgr.update(str(ruleId), doc, int(raw), actor, str(body.get("note", "")))
        except RuleError as exc:
            return _from_error(exc)
        return JSONResponse(out)

    @router.delete("/rules/{ruleId}")
    async def delete_rule(ruleId: UUID, request: Request) -> Response:
        g = await _gate(request, _WRITE)
        if isinstance(g, JSONResponse):
            return g
        actor, mgr = g
        try:
            await mgr.delete(str(ruleId), actor)
        except RuleError as exc:
            return _from_error(exc)
        return Response(status_code=204)

    @router.get("/rules/{ruleId}/versions")
    async def list_versions(ruleId: UUID, request: Request) -> Response:
        g = await _gate(request, _READ)
        if isinstance(g, JSONResponse):
            return g
        actor, mgr = g
        try:
            await mgr.get(str(ruleId), actor)  # visibility (IDOR) check
            items = await mgr.versions(str(ruleId))
        except RuleError as exc:
            return _from_error(exc)
        return JSONResponse(
            {"items": items, "meta": {"next_cursor": None, "has_more": False, "count": len(items)}}
        )

    @router.get("/rules/{ruleId}/versions/{versionId}")
    async def get_version(ruleId: UUID, versionId: UUID, request: Request) -> Response:
        g = await _gate(request, _READ)
        if isinstance(g, JSONResponse):
            return g
        actor, mgr = g
        try:
            await mgr.get(str(ruleId), actor)
            return JSONResponse(await mgr.version(str(ruleId), str(versionId)))
        except RuleError as exc:
            return _from_error(exc)

    @router.put("/rules/{ruleId}/active-version")
    async def set_active(ruleId: UUID, request: Request) -> Response:
        g = await _gate(request, _WRITE)
        if isinstance(g, JSONResponse):
            return g
        actor, mgr = g
        body = await _body(request)
        if body is None or not isinstance(body.get("version_id"), str):
            return _bad("body needs 'version_id'")
        try:
            out = await mgr.set_active_version(
                str(ruleId), body["version_id"], str(body.get("note", "")), actor
            )
        except RuleError as exc:
            return _from_error(exc)
        return JSONResponse(out)

    @router.put("/rules/{ruleId}/mode")
    async def set_mode(ruleId: UUID, request: Request) -> Response:
        g = await _gate(request, _WRITE)
        if isinstance(g, JSONResponse):
            return g
        actor, mgr = g
        body = await _body(request)
        if (
            body is None
            or not isinstance(body.get("mode"), str)
            or set(body)
            - {
                "mode",
                "reason",
                "acknowledge_flatten_all",
            }
        ):
            return _bad("body must be {mode, reason?, acknowledge_flatten_all?}")
        try:
            out = await mgr.set_mode(
                str(ruleId),
                body["mode"],
                actor,
                request.headers.get("idempotency-key"),
                flatten_ack=body.get("acknowledge_flatten_all") is True,
                override_reason=body.get("reason") if isinstance(body.get("reason"), str) else None,
            )
        except RuleError as exc:
            return _from_error(exc)
        return JSONResponse(out)

    return router


__all__ = ["make_rules_crud_router"]
