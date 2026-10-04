"""E35-S04: runtime scope enforcement. Scenario names in docstrings."""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest

from candleviewer.rules.errors import ScopeForbiddenError
from candleviewer.rules.ir.models import RuleScope
from candleviewer.rules.scope import AccountState, ScopeResolver, summarize_scope

OWNER = uuid.UUID(int=1)
A, B, C = (uuid.UUID(int=i) for i in (10, 11, 12))


class FakeState:
    def __init__(self) -> None:
        self.grants = {OWNER: {A, B}}
        self.accounts = {A: AccountState("demo"), B: AccountState("demo"), C: AccountState("demo")}
        self.frozen: set[uuid.UUID] = set()
        self.live_open = False
        self.arm_live = False

    def granted_accounts(self, owner: UUID) -> frozenset[UUID]:
        return frozenset(self.grants.get(owner, set()))

    def account(self, account_id: UUID) -> AccountState | None:
        return self.accounts.get(account_id)

    def owner_frozen(self, owner: UUID) -> bool:
        return owner in self.frozen

    def live_gate_open(self) -> bool:
        return self.live_open

    def can_arm_live(self, owner: UUID) -> bool:
        return self.arm_live


def scope(**kw: Any) -> RuleScope:
    return RuleScope.model_validate({"level": "account", **kw})


def test_scope_is_rechecked_on_every_action() -> None:
    """Scenario: Scope is re-checked on every action"""
    st = FakeState()
    r = ScopeResolver(st)
    sc = scope(account_ids=[str(A), str(B)])
    res = r.resolve(sc, OWNER, "demo")
    assert len(res.instances) == 2
    st.grants[OWNER].discard(B)  # revoked after arming, no re-save
    ia = next(i for i in res.instances if i.account_id == A)
    ib = next(i for i in res.instances if i.account_id == B)
    assert r.check_action(sc, OWNER, "demo", ia) is None
    assert r.check_action(sc, OWNER, "demo", ib) == "grant_revoked"
    nxt = r.resolve(sc, OWNER, "demo")
    assert [s.reason for s in nxt.suppressed] == ["grant_revoked"]
    assert nxt.suppressed[0].skipped_reason == "scope"
    assert r.suppressions_total["grant_revoked"] == 2


def test_out_of_permission_account_is_invisible_and_forbidden() -> None:
    """Scenario: Out-of-permission account is invisible and unusable"""
    st = FakeState()
    audits: list[str] = []
    r = ScopeResolver(st, lambda a, _d: audits.append(a))
    assert C not in r.listable_accounts(OWNER)
    with pytest.raises(ScopeForbiddenError) as ex1:
        r.authorize_accounts(OWNER, [C])
    with pytest.raises(ScopeForbiddenError) as ex2:
        r.authorize_accounts(OWNER, [uuid.UUID(int=999)])  # nonexistent
    assert str(ex1.value) == str(ex2.value) == "Forbidden"
    assert audits == ["rule_scope_denied", "rule_scope_denied"]


def test_live_requires_explicit_opt_in() -> None:
    """Scenario: Live requires explicit opt-in"""
    st = FakeState()
    st.accounts[A] = AccountState("live")
    r = ScopeResolver(st)
    res = r.resolve(scope(account_ids=[str(A)]), OWNER, "live")
    assert res.env_skipped and not res.instances
    assert r.env_skips_total == 1


def test_live_gate_closed_blocks_even_when_scoped() -> None:
    st = FakeState()
    st.accounts[A] = AccountState("live")
    st.arm_live = True
    r = ScopeResolver(st)
    sc = scope(account_ids=[str(A)], environments=["live"])
    assert r.resolve(sc, OWNER, "live").env_skipped
    st.live_open = True
    res = r.resolve(sc, OWNER, "live")
    assert len(res.instances) == 1
    st.live_open = False
    assert r.check_action(sc, OWNER, "live", res.instances[0]) == "live_gate"


def test_live_scope_needs_arm_permission_and_audit() -> None:
    st = FakeState()
    audits: list[tuple[str, dict[str, str]]] = []
    r = ScopeResolver(st, lambda a, d: audits.append((a, d)))
    sc = scope(environments=["demo", "live"])
    with pytest.raises(ScopeForbiddenError):
        r.authorize_environments(OWNER, sc)
    st.arm_live = True
    r.authorize_environments(OWNER, sc)
    assert audits[-1] == ("rule_live_scope_armed", {"caller": str(OWNER), "severity": "high"})


def test_per_symbol_instances_are_independent() -> None:
    """Scenario: Per-symbol instances are independent"""
    r = ScopeResolver(FakeState())
    res = r.resolve(
        scope(level="symbol", account_ids=[str(A)], symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"]),
        OWNER,
        "demo",
    )
    keys = {i.key for i in res.instances}
    assert len(keys) == 3 and f"BTCUSDT@{A}" in keys


def test_frozen_manager_stops_acting() -> None:
    """Scenario: A frozen manager's rules stop acting"""
    st = FakeState()
    r = ScopeResolver(st)
    sc = scope(account_ids=[str(A)])
    inst = r.resolve(sc, OWNER, "demo").instances[0]
    st.frozen.add(OWNER)
    assert r.check_action(sc, OWNER, "demo", inst) == "manager_frozen"
    assert r.resolve(sc, OWNER, "demo").suppressed[0].reason == "manager_frozen"


def test_disabled_account_and_symbol_allowlist() -> None:
    st = FakeState()
    st.accounts[A] = AccountState("demo", allowed_symbols=frozenset({"BTCUSDT"}))
    st.accounts[B] = AccountState("demo", enabled=False)
    r = ScopeResolver(st)
    res = r.resolve(
        scope(account_ids=[str(A), str(B)], symbols=["BTCUSDT", "ETHUSDT"]), OWNER, "demo"
    )
    assert sorted(s.reason for s in res.suppressed) == [
        "account_disabled",
        "account_disabled",
        "symbol_not_allowed",
    ]
    assert len(res.instances) == 1


def test_applies_to_and_algo_children() -> None:
    r = ScopeResolver(FakeState())
    sc = scope(account_ids=[str(A)], applies_to="open_positions")
    inst = r.resolve(sc, OWNER, "demo").instances[0]
    assert r.check_action(sc, OWNER, "demo", inst, "open_position") is None
    assert r.check_action(sc, OWNER, "demo", inst, "pending_order") == "applies_to"
    assert (
        r.check_action(sc, OWNER, "demo", inst, "open_position", is_algo_child=True) == "algo_child"
    )
    sc2 = scope(account_ids=[str(A)], exclude_algo_children=False)
    assert r.check_action(sc2, OWNER, "demo", inst, "open_position", is_algo_child=True) is None


def test_summary_matches_scope() -> None:
    s = summarize_scope(
        scope(account_ids=[str(A), str(B)], symbols=["BTCUSDT"], applies_to="open_positions")
    )
    assert s == "2 accounts · BTCUSDT · open positions only · demo"
    assert "all permitted accounts" in summarize_scope(scope(), account_count=None)
    assert summarize_scope(scope(), account_count=1).startswith("1 account ·")
