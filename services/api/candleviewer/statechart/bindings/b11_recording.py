"""candleviewer.statechart.bindings.b11_recording — MachineLogic stubs for B11 `recording`
(E50-S02). Chart: `machines/B11.recording.machine.json`.

Stubs only: business logic is owned by E35 recorder (ticket "Out of scope").
Guards are pure, total and return `False` (catalogue A6); actions are
`async def` no-ops (CV-C67); services are idempotent `async def` that
return `None` without I/O. Owning epics replace bodies, never names —
the names are fixed by the chart contract.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from candleviewer.statechart.bindings import register_binding_module
from candleviewer.statechart.config import register_event_schemas


async def _noop_action(*_args: object, **_kwargs: object) -> None:
    return None


def _deny_guard(*_args: object, **_kwargs: object) -> bool:
    return False


async def _idempotent_service(*_args: object, **_kwargs: object) -> None:
    return None


ACTIONS: dict[str, Callable[..., Awaitable[None]]] = {
    "add_reason": _noop_action,
    "audit_kill": _noop_action,
    "bump_gap_count": _noop_action,
    "cancel_linger": _noop_action,
    "emit_gap_metric": _noop_action,
    "emit_recording_metric": _noop_action,
    "mark_stream_healthy": _noop_action,
    "mark_stream_unhealthy": _noop_action,
    "raise_degraded_alert": _noop_action,
    "record_error": _noop_action,
    "remove_reason": _noop_action,
    "schedule_linger_deadline": _noop_action,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "all_streams_healthy": _deny_guard,
    "position_open_for_symbol": _deny_guard,
    "reasons_remain": _deny_guard,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "subscribe_streams": _idempotent_service,
    "unsubscribe_and_flush": _idempotent_service,
}

register_binding_module("recording", __name__)

#: Permissive payload schemas (same shape as B16) so `strict=True` accepts
#: exactly the events this chart declares; owning epics tighten them.
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
