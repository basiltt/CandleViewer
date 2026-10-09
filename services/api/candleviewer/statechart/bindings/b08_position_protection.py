"""candleviewer.statechart.bindings.b08_position_protection — MachineLogic stubs for B8
`position_protection` (#1650, E50). Chart: `machines/B08.position_protection.machine.json`.

Stubs only: business logic is owned by E32 (native-SL invariant). Guards are pure,
total and return `False` (catalogue A6 — `tightens_only` is deny-polarity, INV-B8-b);
actions are `async def` (CV-C67); services are idempotent `async def` with no I/O.

KILL semantics (owner decision #1778 item X): `sl.on.KILL` → `sl.frozen`, which is
NOT terminal and never touches the native stop-loss (C-2.6, C-4.14). `frozen` entry
audits and publishes a plain `bool` (C-2.20) that synchronous order code consults;
nothing on a hot path queries the interpreter. No action in this module cancels,
amends or detaches an SL.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from candleviewer.statechart.bindings import register_binding_module
from candleviewer.statechart.config import register_event_schemas

#: Audit hook injected by the owning module (B10/B16 pattern). Must not raise.
AuditHook = Callable[[str, dict[str, Any]], Awaitable[None]]


async def _no_hook(_name: str, _ctx: dict[str, Any]) -> None:
    return None


_hook: AuditHook = _no_hook


def set_audit_hook(hook: AuditHook | None) -> None:
    global _hook
    _hook = hook or _no_hook


#: Plain-bool frozen flags keyed by (account_id, symbol) — C-2.20: published on
#: state entry, read by synchronous code; never an interpreter query.
_FROZEN: dict[tuple[str | None, str | None], bool] = {}


def _key(context: dict[str, Any]) -> tuple[str | None, str | None]:
    acc, sym = context.get("account_id"), context.get("symbol")
    return (None if acc is None else str(acc)), (None if sym is None else str(sym))


def is_frozen(account_id: str | None, symbol: str | None) -> bool:
    return _FROZEN.get((account_id, symbol), False)


def clear_frozen_flags() -> None:
    """Test/boot helper: drop every published flag."""
    _FROZEN.clear()


async def _noop_action(*_args: object, **_kwargs: object) -> None:
    return None


def _deny_guard(*_args: object, **_kwargs: object) -> bool:
    return False


async def _idempotent_service(*_args: object, **_kwargs: object) -> None:
    return None


# --- KILL / frozen arm (#1650) ---------------------------------------------------------


async def audit_kill(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    await _hook("frozen_by_kill", context)


async def publish_frozen_flag(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    context["frozen"] = True
    _FROZEN[_key(context)] = True


async def audit_amend_refused_frozen(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    await _hook("amend_refused_frozen", context)


async def audit_frozen_event(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    await _hook("frozen_event_ignored", context)


async def audit_guard_denied(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    await _hook("guard_denied", context)


_STUB_ACTIONS = (
    "arm_sl_deadline",
    "bump_attach_attempts",
    "bump_fallback_attempts",
    "bump_miss_counter",
    "consider_reduce_only_close",
    "emit_naked_metric",
    "maybe_raise_watchdog_miss",
    "page_owner",
    "raise_critical_alert",
    "reset_fallback_attempts",
    "reset_miss_counter",
    "stamp_naked_since",
)

ACTIONS: dict[str, Callable[..., Awaitable[None]]] = {
    **{name: _noop_action for name in _STUB_ACTIONS},
    "audit_amend_refused_frozen": audit_amend_refused_frozen,
    "audit_frozen_event": audit_frozen_event,
    "audit_guard_denied": audit_guard_denied,
    "audit_kill": audit_kill,
    "publish_frozen_flag": publish_frozen_flag,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "attach_attempts_left": _deny_guard,
    "exchange_reports_sl": _deny_guard,
    "explicit_audited_override": _deny_guard,
    "fallback_attempts_left": _deny_guard,
    "sl_observed": _deny_guard,
    "tightens_only": _deny_guard,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "attach_fallback_sl": _idempotent_service,
    "attach_native_sl": _idempotent_service,
    "read_position_sl": _idempotent_service,
    "set_trading_stop": _idempotent_service,
}

register_binding_module("position_protection", __name__)

_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    {
        name: _ANY_PAYLOAD
        for name in (
            "KILL",
            "LOOSEN_SL",
            "POSITION_FLAT",
            "POSITION_OPENED",
            "SCAN_DUE",
            "SL_DEADLINE",
            "SL_OBSERVED",
            "TIGHTEN_SL",
            "WATCHDOG_MISS",
        )
    }
)
