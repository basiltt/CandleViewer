"""E35-X02: automated abuse-case suite (AC-a..n). Each case asserts refusal, no state change
and (where the control exists today) an audit row. Cases whose control is not built yet are
strict-xfail so they flip to a failure the day the feature lands without a test (see
docs/security/e35/abuse-case-suite.md)."""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.rules.ir.models import RuleScope
from candleviewer.rules.scope import (
    AccountState,
    ActionRequest,
    ScopedActionEmitter,
    ScopeInstanceRef,
    ScopeResolver,
)
from tests.rules.test_rules_routes import ARM, _Env, _ir
from tests.rules.test_scope import OWNER as SCOPE_OWNER
from tests.rules.test_scope import A, B, C, FakeState
from tests.rules.test_scope_crud import _scoped, _setup

LIVE_SCOPE = {"level": "symbol", "symbols": ["BTCUSDT"], "environments": ["demo", "live"]}


def _audit_actions(e: _Env) -> list[str]:
    return [a for a, _ in e.audits]


def _rules(e: _Env) -> list[dict[str, Any]]:
    return list(e.c.get("/rules").json()["items"])


def test_ac_a_arm_on_account_caller_lacks_is_refused() -> None:
    """Abuse case a: crafted API call targeting an ungranted account."""
    c, audits, _src, mgr = _setup()
    assert c.post("/rules", json={"ir": _scoped(C)}).status_code == 403
    assert audits == ["rule_scope_denied"]  # audit row
    assert c.get("/rules").json()["items"] == []  # no state change
    rid = c.post("/rules", json={"ir": _scoped(A)}).json()["id"]
    c.put(f"/rules/{rid}", json={"ir": _scoped(C)}, headers={"If-Match": "1"})
    assert c.get(f"/rules/{rid}").json()["latest_version"] == 1
    assert mgr is not None


def test_ac_b_arm_without_simulation_on_current_hash_is_refused() -> None:
    e = _Env()
    rid = e.create()
    assert e.mode(rid, "simulate", "s").status_code == 200
    r = e.mode(rid, "armed", "a")
    assert r.status_code == 422 and r.json()["code"] == "simulation_required"
    assert e.c.get(f"/rules/{rid}").json()["mode"] == "simulate"
    assert "rule.mode_refused" in _audit_actions(e) and "rule.armed" not in _audit_actions(e)
    # a simulation on an OLD hash does not count after a new version is saved
    e.ready(rid)
    assert (
        e.c.put(f"/rules/{rid}", json={"ir": _ir("77")}, headers={"If-Match": "1"}).status_code
        == 200
    )
    vid = e.c.get(f"/rules/{rid}/versions").json()["items"][0]["id"]
    e.c.put(f"/rules/{rid}/active-version", json={"version_id": vid})
    assert e.mode(rid, "armed", "a2").status_code in (409, 422)
    assert e.c.get(f"/rules/{rid}").json()["mode"] != "armed"


def test_ac_c_arm_with_open_safety_warning_is_refused() -> None:
    from candleviewer.rules.arming import ArmingFacts, check_arming

    f = ArmingFacts(True, 0, 1, True, 5, 0.0, ("demo",), False, False)
    ref = check_arming(f)
    assert ref is not None and ref.code == "safety_warning_open" and ref.status == 422
    # same decision reached through the manager when the stored rule carries the warning
    e = _Env()
    rid = e.create(trigger={"type": "on_price_update"}, limits={"cooldown_ms": 0})
    e.ready(rid)
    r = e.mode(rid, "armed", "a")
    assert r.status_code == 422 and r.json()["code"] == "safety_warning_open"
    assert e.c.get(f"/rules/{rid}").json()["mode"] == "simulate"
    assert "rule.armed" not in _audit_actions(e)


def test_ac_d_live_needs_arm_live_permission_and_fresh_step_up() -> None:
    low = _Env({"rules:read", "rules:write"})
    rid = low.create(scope=LIVE_SCOPE)
    low.ready(rid)
    r = low.mode(rid, "armed", "k")
    assert r.status_code == 403 and r.json()["code"] == "permission_required"
    assert low.c.get(f"/rules/{rid}").json()["mode"] == "simulate"
    assert "rule.mode_refused" in _audit_actions(low)

    stale = _Env({"rules:read", "rules:write", ARM})
    rid = stale.create(scope=LIVE_SCOPE)
    stale.ready(rid)
    stale.grants = 0  # no fresh one-shot step-up grant to consume
    r = stale.mode(rid, "armed", "k2")
    assert r.status_code == 403 and r.json()["code"] == "step_up_required"
    assert stale.c.get(f"/rules/{rid}").json()["mode"] == "simulate"
    assert "rule.armed" not in _audit_actions(stale)


@pytest.mark.parametrize("params", [{"only_tighten": False}])
def test_ac_e_loosening_a_stop_is_refused_at_save(params: dict[str, Any]) -> None:
    e = _Env()
    stop = {
        "node_id": "a1",
        "type": "modify_stop_loss",
        "params": {"mode": "pct", "value": 1, **params},
    }
    r = e.c.post("/rules", json={"ir": _ir(actions=[stop])})
    assert r.status_code == 422 and r.json()["code"] == "rule_ir_invalid"
    widen = {"node_id": "a1", "type": "widen_stop", "params": {"mode": "pct", "value": 1}}
    assert e.c.post("/rules", json={"ir": _ir(actions=[widen])}).status_code == 422
    assert _rules(e) == []


@pytest.mark.xfail(strict=True, reason="E35-FR: targets=all_accounts widest-grant check not built")
def test_ac_f_all_accounts_needs_widest_grant() -> None:
    e = _Env({"rules:read", "rules:write"}, owner=False, granted=frozenset({str(A)}))
    act = {
        "node_id": "a1",
        "type": "send_notification",
        "targets": "all_accounts",
        "params": {"channel": "ui", "severity": "info", "template": "x"},
    }
    assert e.c.post("/rules", json={"ir": _ir(actions=[act])}).status_code in (403, 422)


def _emitter(
    st: FakeState, audits: list[tuple[str, dict[str, str]]]
) -> tuple[ScopedActionEmitter, list[Any]]:
    sent: list[Any] = []

    async def audit(a: str, d: dict[str, str]) -> None:
        audits.append((a, d))

    async def sink(req: ActionRequest) -> None:
        sent.append(req)

    return ScopedActionEmitter(ScopeResolver(st, audit), audit, sink), sent


def _req(inst: ScopeInstanceRef, sc: RuleScope) -> ActionRequest:
    return ActionRequest(sc, SCOPE_OWNER, "demo", inst, "flatten_position")


async def test_ac_g_act_after_grant_revoked_post_arming_is_denied_and_audited() -> None:
    """Abuse case g (E35-S04 central claim): grant revoked while armed, then an evaluation."""
    st = FakeState()
    audits: list[tuple[str, dict[str, str]]] = []
    em, sent = _emitter(st, audits)
    sc = RuleScope.model_validate({"level": "account", "account_ids": [str(B)]})
    inst = ScopeInstanceRef(f"BTCUSDT@{B}", "BTCUSDT", B)
    assert await em.emit(_req(inst, sc)) is True  # armed and granted: acts
    st.grants[SCOPE_OWNER].discard(B)  # revoked after arming, no re-save
    assert await em.emit(_req(inst, sc)) is False
    assert len(sent) == 1  # no further action reached the sink
    assert (
        audits[-1][0] == "rule_action_scope_denied" and audits[-1][1]["reason"] == "grant_revoked"
    )


@pytest.mark.parametrize("freeze", ["owner", "account"])
async def test_ac_h_act_while_frozen_is_denied_and_audited(freeze: str) -> None:
    st = FakeState()
    audits: list[tuple[str, dict[str, str]]] = []
    em, sent = _emitter(st, audits)
    sc = RuleScope.model_validate({"level": "account", "account_ids": [str(B)]})
    inst = ScopeInstanceRef(f"BTCUSDT@{B}", "BTCUSDT", B)
    if freeze == "owner":
        st.frozen.add(SCOPE_OWNER)
    else:
        st.accounts[B] = AccountState("demo", frozen=True)
    assert await em.emit(_req(inst, sc)) is False
    assert sent == [] and audits[-1][1]["reason"] == "manager_frozen"


@pytest.mark.xfail(
    strict=True,
    reason="sys.native_sl_watchdog / sys.clock_drift_block built-ins not in the repo yet (E35-S08)",
)
def test_ac_i_system_builtins_cannot_be_disabled() -> None:
    e = _Env()
    r = e.c.put(
        "/rules/00000000-0000-4000-8000-0000000000aa/mode",
        json={"mode": "disabled"},
        headers={"Idempotency-Key": "k"},
    )
    assert r.status_code in (403, 409)  # a missing rule is 404 today, so this stays red until built


@pytest.mark.xfail(strict=True, reason="rule export/import endpoints not built yet (E35-S06)")
def test_ac_j_k_export_import_hygiene() -> None:
    e = _Env()
    rid = e.create()
    assert e.c.get(f"/rules/{rid}/export").status_code == 200


def test_ac_l_schema_bound_ir_is_bounded_and_slow_evaluation_is_aborted_then_auto_disabled() -> (
    None
):
    from candleviewer.rules.ir.models import MAX_ACTIONS, MAX_BOOLEAN_CHILDREN
    from tests.rules.test_evaluator import c, cmp, m, make, run

    # at the bound: accepted by the schema (and still evaluable)
    kids = [cmp(f"k{i}", "gt", m("pv"), c(0)) for i in range(MAX_BOOLEAN_CHILDREN)]
    from tests.rules.test_evaluator import rule

    rule({"node_id": "b", "op": "all_of", "children": kids})
    # one beyond the bound: refused by the schema
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        rule({"node_id": "b", "op": "all_of", "children": [*kids, cmp("x", "gt", m("pv"), c(0))]})
    e = _Env()
    over = [
        {"node_id": f"a{i}", "type": "send_notification", "params": {}}
        for i in range(MAX_ACTIONS + 1)
    ]
    assert e.c.post("/rules", json={"ir": _ir(actions=over)}).status_code == 422
    assert _rules(e) == []

    # expensive evaluation: the rule's own timeout bounds it, repeated errors auto-disable it
    ev, src, clk, alerts = make(
        {"node_id": "b", "op": "all_of", "children": kids},
        {"pv": 1},
        evaluation_timeout_ms=10,
        kill_switch_on_error_count=3,
    )
    orig = src.read

    def slow(ref: Any) -> Any:
        clk.t += 50
        return orig(ref)

    src.read = slow  # type: ignore[method-assign]
    for _ in range(3):
        res = run(ev)
        assert res.error == "evaluation_timeout" and res.fired is False
    assert alerts and alerts[-1][1].startswith("auto_disabled")
    assert run(ev).skipped_reason == "disabled"
    assert src.reads < 3 * MAX_BOOLEAN_CHILDREN  # cost was cut short, not run to completion


def test_ac_m_signal_loop_is_refused_at_save() -> None:
    e = _Env()
    sig = {"node_id": "a1", "type": "emit_signal", "params": {"signal_name": "s"}}
    r = e.c.post("/rules", json={"ir": _ir(trigger={"type": "on_signal"}, actions=[sig])})
    assert r.status_code == 422
    assert any(i["code"] == "feedback_loop" for i in r.json().get("issues", [])), r.text
    assert _rules(e) == []


def test_ac_n_other_users_rules_are_invisible() -> None:
    owner = _Env()
    rid = owner.create(scope={"level": "account", "account_ids": [str(A)]})
    other = _Env(
        {"rules:read", "rules:write"}, owner=False, granted=frozenset({str(B)}), mgr=owner.mgr
    )
    assert other.c.get("/rules").json()["items"] == []
    for path in (f"/rules/{rid}", f"/rules/{rid}/versions"):
        assert other.c.get(path).status_code == 404
    vid = owner.c.get(f"/rules/{rid}/versions").json()["items"][0]["id"]
    assert other.c.get(f"/rules/{rid}/versions/{vid}").status_code == 404
    assert other.c.delete(f"/rules/{rid}").status_code == 404
    assert (
        other.c.put(
            f"/rules/{rid}/mode", json={"mode": "simulate"}, headers={"Idempotency-Key": "k"}
        ).status_code
        == 404
    )
    assert owner.c.get(f"/rules/{rid}").json()["mode"] == "disabled"  # untouched
