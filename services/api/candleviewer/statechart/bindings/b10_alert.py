"""candleviewer.statechart.bindings.b10_alert — MachineLogic stubs for B10 `alert`
(E50-S02). Chart: `machines/B10.alert.machine.json`.

Stubs only: business logic is owned by E40 alerts & notifications (ticket "Out of scope").
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
    "audit_kill": _noop_action,
    "bump_delivery_attempts": _noop_action,
    "bump_storm_count": _noop_action,
    "emit_delivery_failure_metric": _noop_action,
    "emit_suppression_metric": _noop_action,
    "persist_fired_row": _noop_action,
    "schedule_backoff_deadline": _noop_action,
    "stamp_storm_window": _noop_action,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "all_channels_ok": _deny_guard,
    "delivery_attempts_left": _deny_guard,
    "in_storm_window": _deny_guard,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "dispatch_to_channels": _idempotent_service,
}

register_binding_module("alert", __name__)

#: Permissive payload schemas (same shape as B16) so `strict=True` accepts
#: exactly the events this chart declares; owning epics tighten them.
_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    {
        "ACK": _ANY_PAYLOAD,
        "CONDITION_MET": _ANY_PAYLOAD,
        "DISABLE": _ANY_PAYLOAD,
        "ENABLE": _ANY_PAYLOAD,
        "KILL": _ANY_PAYLOAD,
        "RESOLVE": _ANY_PAYLOAD,
        "RETRY_DUE": _ANY_PAYLOAD,
        "SUPPRESSION_EXPIRED": _ANY_PAYLOAD,
    }
)
