"""candleviewer.statechart.bindings.b11_recording — MachineLogic for B11 `recording`
(E16-T02). Chart: `machines/B11.recording.machine.json` (names fixed by the contract).

One chart per symbol. Statecharts record, synchronous code enforces (C-2.21):
`recorder.policy.RecordingPolicy` decides when a reason starts/ends and when the
grace window is over, then sends `REASON_ADDED` / `REASON_REMOVED` / `LINGER_DUE`
with the facts on the payload; guards only read those facts (event-aware, B11.5).
Side effects (audit, bus, metrics) go through an injected hook, because bindings
never import `recorder`/`audit` (same pattern as B10's `set_hook`). Guards are pure
and total (A6); actions/services are `async def` (CV-C67); services are idempotent
under re-entry (the hook owner de-duplicates by symbol).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from candleviewer.statechart.bindings import register_binding_module
from candleviewer.statechart.config import register_event_schemas


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


#: `hook(name, context)`; names: subscribe, unsubscribe, recording, gap, degraded,
#: error, killed. Installed by `recorder.policy`.
Hook = Callable[[str, dict[str, Any]], Awaitable[None]]


async def _no_hook(_name: str, _ctx: dict[str, Any]) -> None:
    return None


_hook: Hook = _no_hook


def set_hook(hook: Hook | None) -> None:
    global _hook
    _hook = hook or _no_hook


def _payload(event: Any) -> dict[str, Any]:
    for attr in ("payload", "data"):
        v = getattr(event, attr, None)
        if isinstance(v, dict):
            return v
    return event if isinstance(event, dict) else {}


def _guard_error(name: str, exc: Exception) -> bool:
    logger().error("b11_guard_error", guard=name, error=type(exc).__name__)
    return False


# --- guards: pure, total, event-aware (B11.5, R14-03) ---------------------------------


def reasons_remain(context: dict[str, Any], event: Any) -> bool:
    """Reasons left *after* this removal (`remove_reason` has not run yet)."""
    try:
        gone = _payload(event).get("reason")
        return any(r != gone for r in context.get("reasons") or ())
    except Exception as exc:
        return _guard_error("reasons_remain", exc)


def position_open_for_symbol(context: dict[str, Any], event: Any) -> bool:
    """INV-B11-a: the policy reports the OMS position fact on `LINGER_DUE`."""
    try:
        return _payload(event).get("position_open") is True
    except Exception as exc:
        return _guard_error("position_open_for_symbol", exc)


def all_streams_healthy(context: dict[str, Any], event: Any) -> bool:
    """INV-B11-d: every stream healthy once this event's stream is applied."""
    try:
        healthy = dict(context.get("streams_healthy") or {})
        stream = _payload(event).get("stream")
        if stream is not None:
            healthy[str(stream)] = True
        return all(bool(v) for v in healthy.values())
    except Exception as exc:
        return _guard_error("all_streams_healthy", exc)


# --- actions (CV-C67: coroutine functions registered directly) ------------------------


def _pin_identity(context: dict[str, Any], p: dict[str, Any]) -> None:
    if p.get("symbol") is not None and context.get("symbol") is None:
        context["symbol"] = str(p["symbol"])
    if p.get("streams"):
        context["streams"] = [str(s) for s in p["streams"]]


async def add_reason(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    p = _payload(event)
    _pin_identity(context, p)
    reasons = list(context.get("reasons") or ())
    reason = p.get("reason")
    if isinstance(reason, str) and reason not in reasons:
        reasons.append(reason)
    context["reasons"] = reasons


async def remove_reason(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    gone = _payload(event).get("reason")
    context["reasons"] = [r for r in context.get("reasons") or () if r != gone]


async def schedule_linger_deadline(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """The deadline is owned by `RecordingPolicy`'s evaluation tick (no chart timer, so
    a restart re-derives it); the chart records it for the status API (B11.8)."""
    context["linger_until_us"] = _payload(event).get("linger_until_us")


async def cancel_linger(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    context["linger_until_us"] = None


async def emit_recording_metric(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    await _hook("recording", context)


async def mark_stream_unhealthy(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    healthy = dict(context.get("streams_healthy") or {})
    healthy[str(_payload(event).get("stream", "unknown"))] = False
    context["streams_healthy"] = healthy


async def mark_stream_healthy(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    healthy = dict(context.get("streams_healthy") or {})
    healthy[str(_payload(event).get("stream", "unknown"))] = True
    context["streams_healthy"] = healthy


async def raise_degraded_alert(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    await _hook("degraded", context)


async def bump_gap_count(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    context["gap_count_24h"] = int(context.get("gap_count_24h", 0)) + 1


async def emit_gap_metric(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    await _hook("gap", context)  # INV-B11-c: every gap is metricised


async def record_error(_i: Any, context: dict[str, Any], event: Any, _a: Any) -> None:
    """onError arm: the library hands an `ErrorEvent`; read `event.error` (CV-C21)."""
    err = event.error if hasattr(event, "error") else _payload(event).get("error")
    context["error"] = type(err).__name__ if isinstance(err, BaseException) else str(err)
    await _hook("error", context)


async def audit_kill(_i: Any, context: dict[str, Any], _e: Any, _a: Any) -> None:
    await _hook("killed", context)


# --- services (idempotent under re-entry) ---------------------------------------------


async def subscribe_streams(_i: Any, context: dict[str, Any], _e: Any) -> dict[str, Any]:
    await _hook("subscribe", context)
    return {}


async def unsubscribe_and_flush(_i: Any, context: dict[str, Any], _e: Any) -> dict[str, Any]:
    await _hook("unsubscribe", context)
    return {}


ACTIONS: dict[str, Callable[..., Awaitable[None]]] = {
    "add_reason": add_reason,
    "audit_kill": audit_kill,
    "bump_gap_count": bump_gap_count,
    "cancel_linger": cancel_linger,
    "emit_gap_metric": emit_gap_metric,
    "emit_recording_metric": emit_recording_metric,
    "mark_stream_healthy": mark_stream_healthy,
    "mark_stream_unhealthy": mark_stream_unhealthy,
    "raise_degraded_alert": raise_degraded_alert,
    "record_error": record_error,
    "remove_reason": remove_reason,
    "schedule_linger_deadline": schedule_linger_deadline,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "all_streams_healthy": all_streams_healthy,
    "position_open_for_symbol": position_open_for_symbol,
    "reasons_remain": reasons_remain,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "subscribe_streams": subscribe_streams,
    "unsubscribe_and_flush": unsubscribe_and_flush,
}

register_binding_module("recording", __name__)

_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    {
        "GAP_DETECTED": _ANY_PAYLOAD,
        "KILL": _ANY_PAYLOAD,
        "LINGER_DUE": _ANY_PAYLOAD,
        "REASON_ADDED": _ANY_PAYLOAD,
        "REASON_REMOVED": _ANY_PAYLOAD,
        "RETRY": _ANY_PAYLOAD,
        "STREAM_HEALTHY": _ANY_PAYLOAD,
        "STREAM_UNHEALTHY": _ANY_PAYLOAD,
    }
)
