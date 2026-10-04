"""E35-S04: scope enforcement wired through RulesService, the router and the evaluator."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.api.rules import make_rules_router
from candleviewer.rules.ir.models import RuleScope
from candleviewer.rules.scope import ScopeInstanceRef, summarize_scope
from candleviewer.rules.service import RulesService
from candleviewer.rules.vocabulary import default_registry
from tests.rules.test_validator_endpoints import PRICE, _cmp, _doc

OWNER = uuid.UUID(int=1)
A, B, C = (uuid.UUID(int=i) for i in (10, 11, 12))


class Source:
    def __init__(self) -> None:
        self.grants = [(A, True, False), (B, True, False)]
        self.perms: frozenset[str] = frozenset({"rules:read"})

    async def load_grants(self, owner: uuid.UUID) -> list[tuple[uuid.UUID, bool, bool]]:
        return list(self.grants)

    async def load_permissions(self, owner: uuid.UUID) -> frozenset[str]:
        return self.perms


class Principal:
    user_id = OWNER

    def has(self, p: str) -> bool:
        return p == "rules:read"


class Resolver:
    def resolve(self, request: object) -> Principal:
        return Principal()


def _svc(src: Source, audits: list[str]) -> RulesService:
    async def audit(event: str, data: dict[str, str]) -> None:
        audits.append(event)

    svc = RulesService()
    svc.wire_scope(src, "demo", audit)
    return svc


def _client(svc: RulesService | None) -> TestClient:
    app = FastAPI()
    kw: dict[str, Any] = {}
    if svc is not None:
        kw = {"scope_resolver": svc.scope_resolver, "scope_refresh": svc.refresh_scope}
    reg = default_registry()
    app.include_router(make_rules_router(lambda: reg, principal_resolver=Resolver(), **kw))
    return TestClient(app)


def _body(**scope: Any) -> dict[str, Any]:
    rule = _doc(_cmp(PRICE, {"const": 1}), scope={"level": "account", **scope})
    return {"ir": rule.model_dump(mode="json")}


def test_unwired_router_fails_closed_for_scoped_rule() -> None:
    r = _client(None).post("/rules/validate", json=_body(account_ids=[str(A)]))
    assert r.status_code == 501


def test_granted_account_validates_and_ungranted_is_403_without_leak() -> None:
    audits: list[str] = []
    c = _client(_svc(Source(), audits))
    assert c.post("/rules/validate", json=_body(account_ids=[str(A)])).status_code == 200
    r1 = c.post("/rules/validate", json=_body(account_ids=[str(C)]))  # exists, not granted
    r2 = c.post("/rules/validate", json=_body(account_ids=[str(uuid.UUID(int=999))]))
    assert r1.status_code == r2.status_code == 403
    assert r1.json() == r2.json()
    assert audits == ["rule_scope_denied", "rule_scope_denied"]


def test_live_requires_arm_permission_through_app_wiring() -> None:
    src, audits = Source(), list[str]()
    c = _client(_svc(src, audits))
    live = _body(account_ids=[str(A)], environments=["demo", "live"])
    assert c.post("/rules/validate", json=live).status_code == 403
    src.perms = frozenset({"rules:read", "rules.arm_live"})
    assert c.post("/rules/validate", json=live).status_code == 200
    assert audits[-1] == "rule_live_scope_armed"


def test_revoked_grant_is_picked_up_on_next_request() -> None:
    src = Source()
    c = _client(_svc(src, []))
    assert c.post("/rules/validate", json=_body(account_ids=[str(B)])).status_code == 200
    src.grants = [(A, True, False)]
    assert c.post("/rules/validate", json=_body(account_ids=[str(B)])).status_code == 403


async def test_production_evaluator_is_always_gated() -> None:
    from candleviewer.rules.evaluator import SnapshotBuilder
    from tests.rules.test_evaluator import Clock, cmp, rule
    from tests.rules.test_evaluator import Source as Mkt

    src = Source()
    svc = _svc(src, [])
    await svc.refresh_scope(OWNER)
    clk = Clock()
    r = rule(cmp("c1", "gt", {"metric": "last_price"}, {"const": 1}), cooldown_ms=0)
    r = r.model_copy(
        update={"scope": RuleScope.model_validate({"level": "account", "account_ids": [str(B)]})}
    )
    ev = svc.build_evaluator(
        r, SnapshotBuilder(Mkt(clk, last_price=100)), clk, clk, owner=OWNER, environment="demo"
    )
    inst = f"BTCUSDT@{B}"
    ev._snapshots.new_tick()
    assert ev.on_trigger(inst, "on_price_update").fired
    src.grants = [(B, True, True)]  # manager frozen
    await svc.refresh_scope(OWNER)
    ev._snapshots.new_tick()
    assert ev.on_trigger(inst, "on_price_update").skipped_reason == "scope"
    with pytest.raises(RuntimeError):
        RulesService().build_evaluator(
            r, SnapshotBuilder(Mkt(clk, last_price=1)), clk, clk, owner=OWNER, environment="demo"
        )


@given(
    n=st.integers(0, 3),
    syms=st.lists(st.sampled_from(["BTCUSDT", "ETHUSDT"]), unique=True, max_size=2),
    applies=st.sampled_from(["any", "account", "open_positions", "pending_orders"]),
    envs=st.sampled_from([["demo"], ["demo", "live"]]),
)
async def test_summary_matches_enforcement(
    n: int, syms: list[str], applies: str, envs: list[str]
) -> None:
    """Property: the server-derived chip never claims more than resolution enforces."""
    src = Source()
    svc = _svc(src, [])
    await svc.refresh_scope(OWNER)
    ids = [uuid.UUID(int=10 + i) for i in range(n)]
    sc = RuleScope.model_validate(
        {
            "level": "account",
            "account_ids": [str(i) for i in ids],
            "symbols": syms,
            "applies_to": applies,
            "environments": envs,
        }
    )
    chip = summarize_scope(sc)
    res = svc.scope_resolver.resolve(sc, OWNER, "demo")  # type: ignore[union-attr]
    permitted = {i for i in ids if i in (A, B)} if ids else {A, B}  # empty = all granted
    assert {i.account_id for i in res.instances} <= permitted
    assert len(res.instances) + len(res.suppressed) == len(permitted | set(ids)) * max(len(syms), 1)
    assert (f"{n} account" in chip) if ids else ("all permitted accounts" in chip)
    for s in syms:
        assert s in chip
    for i in res.instances:
        assert isinstance(i, ScopeInstanceRef)
