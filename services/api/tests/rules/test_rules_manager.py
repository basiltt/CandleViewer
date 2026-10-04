"""E35-S01: store, version and mode-switch rules (manager + mode matrix)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from candleviewer.rules.manager import Actor, InMemoryRuleStore, RuleError, RulesManager
from candleviewer.rules.mode import (
    LEGAL,
    MODES,
    ArmingFacts,
    check_arming,
    check_transition,
    promotion_gate_met,
)
from candleviewer.rules.vocabulary import default_registry

FIX = Path(__file__).parents[1] / "fixtures/rule_ir"
OWNER = Actor("u1", "s1", frozenset({"rules.arm.live"}), is_owner=True, step_up_fresh=True)
MGR = Actor("u2", "s2", frozenset({"orders:write"}), frozenset({"acc1"}))


def _ir(threshold: str = "65000.50", **over: Any) -> dict[str, Any]:
    raw = json.loads((FIX / "form_simple_0.json").read_text(encoding="utf-8"), parse_float=str)
    raw["conditions"]["right"]["const"] = threshold
    raw["actions"][0]["params"] = {"channel": "ui", "severity": "info", "template": "x"}
    return {**raw, **over}


def _mgr() -> tuple[RulesManager, list[tuple[str, dict[str, Any]]], list[dict[str, Any]]]:
    audits: list[tuple[str, dict[str, Any]]] = []
    bcs: list[dict[str, Any]] = []
    m = RulesManager(
        InMemoryRuleStore(),
        default_registry(),
        audit=lambda a, p: audits.append((a, p)),
        broadcast=bcs.append,
    )
    return m, audits, bcs


def _active_hash(m: RulesManager, rid: str) -> str:
    active = m.get(rid, OWNER)["active_version_id"]
    return str(next(v["ir_hash"] for v in m.versions(rid) if v["id"] == active))


def _ready_to_arm(m: RulesManager, rid: str) -> None:
    m.set_mode(rid, "simulate", OWNER, "k-sim")
    m.record_simulation(rid, _active_hash(m, rid), 5, 0.0)


def test_create_stores_version_1_disabled() -> None:
    m, audits, _ = _mgr()
    out = m.create(_ir(), OWNER)
    assert out["mode"] == "disabled" and out["version"]["version"] == 1
    assert audits[0][0] == "rule.created"


def test_every_save_is_a_new_immutable_version() -> None:
    """Scenario: Every save is a new immutable version"""
    m, _, _ = _mgr()
    rid = m.create(_ir(), OWNER)["id"]
    for i, n in enumerate(("1", "2", "3"), start=2):
        assert m.update(rid, _ir(n), i - 1, OWNER)["version"]["version"] == i
    v3 = m.versions(rid)[1]
    assert v3["version"] == 3 and v3["compiler_version"]
    assert m.update(rid, _ir("9"), 4, OWNER)["version"]["version"] == 5
    assert m.versions(rid)[2]["ir_hash"] == v3["ir_hash"]


def test_version_chain_and_rollback() -> None:
    m, _, _ = _mgr()
    rid = m.create(_ir(), OWNER)["id"]
    for i in range(1, 10):
        m.update(rid, _ir(str(i)), i, OWNER)
    vs = m.versions(rid)
    assert [v["version"] for v in vs] == list(range(10, 0, -1))
    first = vs[-1]["id"]
    m.set_active_version(rid, first, "rollback", OWNER)
    assert m.get(rid, OWNER)["active_version_id"] == first
    assert m.version(rid, first)["ir"]["version"] == 1


def test_armed_rule_keeps_active_version_when_saved() -> None:
    """Scenario: Every save is a new immutable version (armed keeps running it)"""
    m, _, _ = _mgr()
    rid = m.create(_ir(), OWNER)["id"]
    _ready_to_arm(m, rid)
    m.set_mode(rid, "armed", OWNER, "k-arm")
    active = m.get(rid, OWNER)["active_version_id"]
    m.update(rid, _ir("7"), 1, OWNER)
    assert m.get(rid, OWNER)["active_version_id"] == active
    assert m.get(rid, OWNER)["mode"] == "armed"
    other = m.versions(rid)[0]["id"]
    assert m.set_active_version(rid, other, "n", OWNER)["mode"] == "simulate"


def test_arming_requires_simulation_on_exact_hash() -> None:
    """Scenario: Arming requires proof the rule was simulated"""
    m, _, _ = _mgr()
    rid = m.create(_ir(), OWNER)["id"]
    m.set_mode(rid, "simulate", OWNER, "ks")
    with pytest.raises(RuleError) as e:
        m.set_mode(rid, "armed", OWNER, "k1")
    assert e.value.status == 422 and e.value.code == "simulation_required"
    assert "Run a simulation" in e.value.message
    assert m.get(rid, OWNER)["mode"] == "simulate"


def test_arming_live_is_audited_with_ir_hash_and_broadcast_first() -> None:
    """Scenario: Arming live needs step-up and is provably audited"""
    m, audits, bcs = _mgr()
    scope = {"level": "symbol", "symbols": ["BTCUSDT"], "environments": ["demo", "live"]}
    rid = m.create(_ir(scope=scope), OWNER)["id"]
    _ready_to_arm(m, rid)
    stale = Actor("u1", "s1", frozenset({"rules.arm.live"}), is_owner=True)
    with pytest.raises(RuleError) as e:
        m.set_mode(rid, "armed", stale, "k0")
    assert e.value.code == "step_up_required"
    noperm = Actor("u1", "s1", frozenset(), is_owner=True, step_up_fresh=True)
    with pytest.raises(RuleError) as e2:
        m.set_mode(rid, "armed", noperm, "k00")
    assert e2.value.code == "permission_required"
    m.set_mode(rid, "armed", OWNER, "k1")
    armed = next(p for a, p in audits if a == "rule.armed")
    assert armed["ir_hash"] == _active_hash(m, rid) and "live" in armed["environments"]
    assert bcs[-1]["mode"] == "armed" and bcs[-1]["topic"] == "rules"
    assert any(a == "rule.mode_refused" for a, _ in audits)


def test_concurrent_edit_is_rejected_naming_other_session() -> None:
    """Scenario: Concurrent edits never silently overwrite"""
    m, _, _ = _mgr()
    rid = m.create(_ir(), OWNER)["id"]
    m.update(rid, _ir("2"), 1, OWNER)
    other = Actor("u3", "s-other", frozenset(), is_owner=True)
    with pytest.raises(RuleError) as e:
        m.update(rid, _ir("3"), 1, other)
    assert e.value.status == 409 and e.value.code == "version_conflict"
    assert e.value.extra["session"] == "s1"
    assert e.value.extra["action"] == "reload_and_reapply"


def test_unchanged_save_creates_nothing() -> None:
    """Scenario: Saving an unchanged rule creates nothing"""
    m, _, _ = _mgr()
    rid = m.create(_ir(), OWNER)["id"]
    r = m.update(rid, _ir(), 1, OWNER)
    assert r["created"] is False and r["version"]["version"] == 1
    assert len(m.versions(rid)) == 1


def test_corrupt_stored_rule_is_quarantined() -> None:
    """Scenario: A corrupt stored rule is quarantined"""
    m, _, _ = _mgr()
    rid = m.create(_ir(), OWNER)["id"]
    row = m._s.get(rid)
    assert row is not None
    row.versions[0].ir["conditions"] = {"bogus": 1}
    row.mode = "armed"
    view = m.get(rid, OWNER)
    assert view["read_only"] and view["mode"] == "disabled"
    assert view["failing_path"].startswith("/") and "export_json" in view
    with pytest.raises(RuleError):
        m.set_mode(rid, "simulate", OWNER, "kq")


def test_armed_rule_cannot_be_deleted_and_soft_delete_reuses_name() -> None:
    """Scenario: An armed rule cannot be deleted"""
    m, _, _ = _mgr()
    rid = m.create(_ir(), OWNER)["id"]
    _ready_to_arm(m, rid)
    m.set_mode(rid, "armed", OWNER, "ka")
    with pytest.raises(RuleError) as e:
        m.delete(rid, OWNER)
    assert e.value.status == 409 and "Disarm" in e.value.message
    m.set_mode(rid, "disabled", OWNER, "kd")
    m.delete(rid, OWNER)
    assert m.create(_ir(), OWNER)["mode"] == "disabled"
    kept = m._s.get(rid)
    assert kept is not None and len(kept.versions) == 1


def test_mode_endpoint_requires_idempotency_key_and_replays() -> None:
    m, audits, _ = _mgr()
    rid = m.create(_ir(), OWNER)["id"]
    with pytest.raises(RuleError) as e:
        m.set_mode(rid, "simulate", OWNER, None)
    assert e.value.status == 400
    a = m.set_mode(rid, "simulate", OWNER, "same")
    n = len(audits)
    assert m.set_mode(rid, "simulate", OWNER, "same") == a and len(audits) == n


def test_list_is_account_scoped_filterable_and_paginated() -> None:
    m, _, _ = _mgr()
    m.create(_ir(name="open"), OWNER)
    acct = {"level": "account", "account_ids": ["00000000-0000-4000-8000-0000000000a2"]}
    m.create(_ir(name="acct", scope=acct), OWNER)
    names = [r["name"] for r in m.list_rules(MGR)["items"]]
    assert names == ["open"]
    assert len(m.list_rules(OWNER, mode="disabled")["items"]) == 2
    assert len(m.list_rules(OWNER, scope="account")["items"]) == 1
    assert m.list_rules(OWNER, limit=1)["next_cursor"] is not None


def test_invalid_ir_rejected_422() -> None:
    m, _, _ = _mgr()
    with pytest.raises(RuleError) as e:
        m.create({"name": "x"}, OWNER)
    assert e.value.status == 422


@pytest.mark.parametrize("cur", MODES)
@pytest.mark.parametrize("tgt", MODES)
def test_transition_matrix(cur: str, tgt: str) -> None:
    r = check_transition(cur, tgt)
    assert (r is None) == (cur == tgt or (cur, tgt) in LEGAL)


def test_unknown_mode_and_disabled_to_armed_refused() -> None:
    bad = check_transition("disabled", "bogus")
    assert bad is not None and bad.code == "invalid_mode"
    direct = check_transition("disabled", "armed")
    assert direct is not None and direct.code == "illegal_transition"


def _facts(**kw: Any) -> ArmingFacts:
    base: dict[str, Any] = {
        "has_valid_active_version": True,
        "validation_errors": 0,
        "open_safety_warnings": 0,
        "simulated_on_ir_hash": True,
        "simulation_fires": 5,
        "simulation_hours": 0.0,
        "environments": ("demo",),
        "sends_orders": False,
        "has_flatten_all": False,
    }
    return ArmingFacts(**{**base, **kw})


@pytest.mark.parametrize(
    ("kw", "code"),
    [
        ({"has_valid_active_version": False}, "rule_invalid"),
        ({"validation_errors": 1}, "rule_invalid"),
        ({"open_safety_warnings": 1}, "safety_warning_open"),
        ({"simulated_on_ir_hash": False}, "simulation_required"),
        ({"simulation_fires": 1}, "promotion_gate"),
        ({"sends_orders": True, "unauthorised_accounts": ("a",)}, "orders_write_required"),
        ({"environments": ("live",)}, "permission_required"),
        ({"environments": ("live",), "perms": frozenset({"rules.arm.live"})}, "step_up_required"),
        ({"has_flatten_all": True}, "acknowledgement_required"),
    ],
)
def test_each_arming_precondition_refuses(kw: dict[str, Any], code: str) -> None:
    r = check_arming(_facts(**kw))
    assert r is not None and r.code == code


def test_arming_ok_override_and_gate() -> None:
    assert check_arming(_facts()) is None
    assert check_arming(_facts(simulation_fires=0, simulation_hours=24)) is None
    owner = _facts(simulation_fires=0, is_owner=True, owner_override_reason="why")
    assert check_arming(owner) is None
    assert not promotion_gate_met(4, 23.9)
