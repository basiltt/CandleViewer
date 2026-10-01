"""candleviewer.statechart.bindings.b12_replay — MachineLogic stubs for B12 `replay`
(E50-S02). Chart: `machines/B12.replay.machine.json`.

Stubs only: business logic is owned by E36 replay (ticket "Out of scope").
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
    "record_coverage": _noop_action,
    "record_error": _noop_action,
    "reset_cursor_to_start": _noop_action,
    "set_cursor": _noop_action,
    "set_speed": _noop_action,
    "slow_clock": _noop_action,
    "start_clock": _noop_action,
    "stop_clock": _noop_action,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "loop_enabled": _deny_guard,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "emit_one_step": _idempotent_service,
    "seek_and_prime": _idempotent_service,
}

register_binding_module("replay", __name__)

#: Permissive payload schemas (same shape as B16) so `strict=True` accepts
#: exactly the events this chart declares; owning epics tighten them.
_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    {
        "CANCEL": _ANY_PAYLOAD,
        "CONSUMER_SLOW": _ANY_PAYLOAD,
        "DESTROY": _ANY_PAYLOAD,
        "KILL": _ANY_PAYLOAD,
        "PAUSE": _ANY_PAYLOAD,
        "PLAY": _ANY_PAYLOAD,
        "PREPARE": _ANY_PAYLOAD,
        "RANGE_END": _ANY_PAYLOAD,
        "SEEK": _ANY_PAYLOAD,
        "SET_SPEED": _ANY_PAYLOAD,
        "SOURCE_ERROR": _ANY_PAYLOAD,
        "STEP": _ANY_PAYLOAD,
    }
)
