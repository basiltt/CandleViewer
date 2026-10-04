"""E35-S01 composition: `/rules` mounted in the real app, gated, fail-closed, step-up registered."""

from __future__ import annotations

from candleviewer.api.deny_by_default import served_operations
from candleviewer.api.step_up import HANDLER_GATED_ROUTES
from candleviewer.app import create_app


def test_rules_routes_mounted_and_declared_in_openapi() -> None:
    app = create_app()  # asserts every served route has an x-rbac declaration
    paths = served_operations(app)
    for op in [
        ("GET", "/rules"), ("POST", "/rules"), ("GET", "/rules/{ruleId}"),
        ("PUT", "/rules/{ruleId}"), ("DELETE", "/rules/{ruleId}"),
        ("GET", "/rules/{ruleId}/versions"), ("GET", "/rules/{ruleId}/versions/{versionId}"),
        ("PUT", "/rules/{ruleId}/active-version"), ("PUT", "/rules/{ruleId}/mode"),
    ]:  # fmt: skip
        assert op in paths, op


def test_live_arm_route_is_registered_as_step_up_gated() -> None:
    assert ("PUT", "/rules/{ruleId}/mode", "live_enablement") in HANDLER_GATED_ROUTES


def test_rules_fail_closed_without_identity() -> None:
    from fastapi.testclient import TestClient

    r = TestClient(create_app(), client=("127.0.0.1", 50000)).get("/rules")
    assert r.status_code in (401, 501)


def test_create_app_binds_postgres_rule_store_not_in_memory() -> None:
    from candleviewer.rules_store_pg import PostgresRuleStore

    app = create_app()
    assert isinstance(app.state.app_context.rules._store, PostgresRuleStore)


async def test_actor_consume_refuses_without_fresh_step_up() -> None:
    """The hard-coded `step_up_fresh=True` is safe only because `consume` is the real check."""
    from types import SimpleNamespace

    from starlette.requests import Request

    from candleviewer.api.rules_actor import SessionRulesActorResolver
    from candleviewer.auth.errors import StepUpRequired

    class _Sessions:
        async def authenticate_access_token(self, token: str, touch: bool = True) -> object:
            return SimpleNamespace(user_id="u1", id="s1")

    class _Identity:
        async def user(self, uid: str) -> dict[str, object]:
            return {"status": "active", "roles": ["manager"]}

        async def session_info(self, uid: str) -> dict[str, object]:
            return {"permissions": ["rules.arm.live"], "account_scope": []}

    pending: list[str] = []

    class _StepUp:
        async def consume_single_use(self, sid: str, cls: str) -> None:
            raise StepUpRequired("no fresh step-up")

        async def record_pending(self, sid: str, cls: str) -> None:
            pending.append(sid)

    req = Request({"type": "http", "headers": [(b"authorization", b"Bearer t")]})
    actor = await SessionRulesActorResolver(
        lambda: _Sessions(), lambda: _StepUp(), _Identity()
    ).resolve(req)
    assert actor is not None and actor.consume_step_up is not None
    assert await actor.consume_step_up() is False
    assert pending == ["s1"]


async def test_service_sink_records_simulation_for_simulating_rule() -> None:
    import asyncio

    from candleviewer.rules.evaluator.engine import EvaluationResult
    from candleviewer.rules.manager import Actor
    from candleviewer.rules.service import RulesService

    svc = RulesService()
    await svc.start(None)  # type: ignore[arg-type]
    m = svc.manager()
    assert m is not None
    owner = Actor("u1", "s1", frozenset({"rules:arm_live"}), is_owner=True, step_up_fresh=True)
    import json
    from pathlib import Path

    raw = json.loads(
        (Path(__file__).parents[1] / "fixtures/rule_ir/form_simple_0.json").read_text("utf-8"),
        parse_float=str,
    )
    raw["actions"][0]["params"] = {"channel": "ui", "severity": "info", "template": "x"}
    rid = (await m.create(raw, owner))["id"]
    await m.set_mode(rid, "simulate", owner, "k1")
    sink = svc.evaluation_sink()
    for i in range(5):
        sink(EvaluationResult(rid, 1, "BTCUSDT@*", "tick", i, True, None))
    await asyncio.gather(*svc._tasks)
    assert (await m.set_mode(rid, "armed", owner, "k2"))["mode"] == "armed"
    await svc.stop(1.0)
