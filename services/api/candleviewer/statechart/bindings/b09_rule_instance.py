"""candleviewer.statechart.bindings.b09_rule_instance — MachineLogic stubs for B9 `rule_instance`
(E50-S01). Chart: `machines/B09.rule_instance.machine.json`.

Stubs only: business logic is owned by E24 rule engine (ticket "Out of scope").
Guards are pure, total and return `False` (catalogue A6); actions are
`async def` no-ops (CV-C67); services are idempotent `async def` that
return `None` without I/O. Owning epics replace bodies, never names —
the names are fixed by the chart contract.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from candleviewer.rules.mode import promotion_gate_met
from candleviewer.statechart.bindings import register_binding_module
from candleviewer.statechart.config import register_event_schemas


async def _noop_action(*_args: object, **_kwargs: object) -> None:
    return None


def _deny_guard(*_args: object, **_kwargs: object) -> bool:
    return False


async def _idempotent_service(*_args: object, **_kwargs: object) -> None:
    return None


def _ctx(args: tuple[object, ...]) -> Any:
    for a in args:
        c = getattr(a, "context", None)
        if isinstance(c, dict):
            return c
    return None


async def _reset_simulation_counters(*args: object, **_kwargs: object) -> None:
    ctx = _ctx(args)
    if ctx is not None:
        ctx["simulation_fires"] = 0
        ctx["simulation_started_us"] = None


async def _bump_simulation_fires(*args: object, **_kwargs: object) -> None:
    ctx = _ctx(args)
    if ctx is not None:
        ctx["simulation_fires"] = int(ctx.get("simulation_fires", 0)) + 1


def _payload(event: Any) -> dict[str, Any]:
    payload = getattr(event, "payload", event)
    return payload if isinstance(payload, dict) else {}


def _guard_args(args: tuple[object, ...]) -> tuple[dict[str, Any], dict[str, Any]]:
    """`(context, event payload)` from the library's positional guard arguments."""
    ctx = _ctx(args) or {}
    for a in args:
        if isinstance(a, dict) and a is not ctx:
            return ctx, a
    return ctx, _payload(args[-1]) if args else {}


def promotion_gate_satisfied_and_permitted(*args: object, **_kwargs: object) -> bool:
    """Deny-polarity (INV-B9-e): promote only on proven simulation + permission.

    The event carries the server-computed facts (`permitted`, set by the synchronous
    arming check in `rules.mode`/`RulesManager`; statecharts record, code enforces).
    Total: any malformed input yields False (catalogue A6)."""
    try:
        ctx, ev = _guard_args(args)
        if ev.get("permitted") is not True:
            return False
        if ev.get("owner_override_reason") and ev.get("is_owner") is True:
            return True
        hours = 0.0
        started, now = ctx.get("simulation_started_us"), ev.get("now_us")
        if started is not None and now is not None:
            hours = max(0, int(now) - int(started)) / 3_600_000_000
        return promotion_gate_met(int(ctx.get("simulation_fires", 0)), hours)
    except (TypeError, ValueError, AttributeError):
        return False


def rearm_permitted_and_elevated(*args: object, **_kwargs: object) -> bool:
    """INV-B9-d: leaving `kill_switched` needs a human with permission and fresh step-up."""
    try:
        _, ev = _guard_args(args)
        return ev.get("permitted") is True and ev.get("elevated") is True
    except (TypeError, ValueError, AttributeError):
        return False


ACTIONS: dict[str, Callable[..., Awaitable[None]]] = {
    "audit_guard_denied": _noop_action,
    "audit_kill": _noop_action,
    "arm_confirmation_ttl": _noop_action,
    "assert_safety_limits": _noop_action,
    "bump_consecutive_errors": _noop_action,
    "bump_simulation_fires": _bump_simulation_fires,
    "drain_deferred": _noop_action,
    "emit_armed_audit": _noop_action,
    "emit_kill_switch_audit": _noop_action,
    "emit_rules_paused_notice": _noop_action,
    "evaluate_and_record_simulated": _noop_action,
    "log_no_op_with_values": _noop_action,
    "queue_for_human_confirmation": _noop_action,
    "raise_critical_alert": _noop_action,
    "raise_partial_alert": _noop_action,
    "record_fire": _noop_action,
    "record_partial_fire": _noop_action,
    "record_skip_debounced": _noop_action,
    "record_skip_limit": _noop_action,
    "record_skip_rejected": _noop_action,
    "record_skip_stale_data": _noop_action,
    "record_skip_unconfirmed": _noop_action,
    "reject_promotion_with_reason": _noop_action,
    "reset_consecutive_errors": _noop_action,
    "reset_simulation_counters": _reset_simulation_counters,
    "stamp_cooldown_deadline": _noop_action,
    "stamp_simulation_start": _noop_action,
    "subscribe_triggers": _noop_action,
    "unsubscribe_triggers": _noop_action,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "condition_true": _deny_guard,
    "condition_true_and_requires_confirmation": _deny_guard,
    "data_stale": _deny_guard,
    "debounce_blocked": _deny_guard,
    "error_budget_exhausted": _deny_guard,
    "limits_blocked": _deny_guard,
    "once_satisfied": _deny_guard,
    "promotion_gate_satisfied_and_permitted": promotion_gate_satisfied_and_permitted,
    "rearm_permitted_and_elevated": rearm_permitted_and_elevated,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "dispatch_actions_in_order": _idempotent_service,
    "evaluate_condition_dag": _idempotent_service,
}

register_binding_module("rule_instance", __name__)

#: Permissive payload schemas (same shape as B16) so `strict=True` accepts
#: exactly the events this chart declares; owning epics tighten them.
_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    {
        "KILL": _ANY_PAYLOAD,
        "ARM_REQUESTED": _ANY_PAYLOAD,
        "CONFIRMED": _ANY_PAYLOAD,
        "CONFIRM_TIMEOUT": _ANY_PAYLOAD,
        "COOLDOWN_DUE": _ANY_PAYLOAD,
        "DISARM": _ANY_PAYLOAD,
        "EDIT": _ANY_PAYLOAD,
        "FEED_DEGRADED": _ANY_PAYLOAD,
        "FEED_HEALTHY": _ANY_PAYLOAD,
        "HUMAN_REARM": _ANY_PAYLOAD,
        "KILL_SWITCH": _ANY_PAYLOAD,
        "REJECTED": _ANY_PAYLOAD,
        "RESET_ONCE": _ANY_PAYLOAD,
        "SAVE": _ANY_PAYLOAD,
        "SIM_FIRE": _ANY_PAYLOAD,
        "TRIGGER": _ANY_PAYLOAD,
    }
)
