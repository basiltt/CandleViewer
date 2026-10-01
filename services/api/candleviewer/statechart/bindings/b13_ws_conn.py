"""candleviewer.statechart.bindings.b13_ws_conn — MachineLogic stubs for B13 `ws_conn`
(E50-S02). Chart: `machines/B13.ws_conn.machine.json`.

Stubs only: business logic is owned by E05 ingestion (ticket "Out of scope").
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
    "arm_pong_deadline": _noop_action,
    "audit_kill": _noop_action,
    "bump_attempt": _noop_action,
    "compute_jittered_backoff": _noop_action,
    "emit_feed_degraded": _noop_action,
    "emit_feed_healthy": _noop_action,
    "notify_dependents_degraded": _noop_action,
    "raise_conn_budget_alert": _noop_action,
    "rearm_pong_deadline": _noop_action,
    "record_auth_error": _noop_action,
    "record_conn_error": _noop_action,
    "record_pong_timeout": _noop_action,
    "record_staleness": _noop_action,
    "record_sub_error": _noop_action,
    "record_subscribed": _noop_action,
    "reset_backoff": _noop_action,
    "schedule_backoff_deadline": _noop_action,
    "schedule_budget_recheck": _noop_action,
    "set_pending_topics": _noop_action,
    "stamp_pong": _noop_action,
}

GUARDS: dict[str, Callable[..., bool]] = {
    "connection_budget_exhausted": _deny_guard,
    "is_private": _deny_guard,
}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {
    "close_socket": _idempotent_service,
    "open_socket": _idempotent_service,
    "subscribe_in_batches": _idempotent_service,
    "ws_auth": _idempotent_service,
}

register_binding_module("ws_conn", __name__)

#: Permissive payload schemas (same shape as B16) so `strict=True` accepts
#: exactly the events this chart declares; owning epics tighten them.
_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    {
        "BACKOFF_DUE": _ANY_PAYLOAD,
        "BUDGET_RECHECK": _ANY_PAYLOAD,
        "CONNECT": _ANY_PAYLOAD,
        "KILL": _ANY_PAYLOAD,
        "PONG": _ANY_PAYLOAD,
        "PONG_DEADLINE": _ANY_PAYLOAD,
        "SHUTDOWN": _ANY_PAYLOAD,
        "SOCKET_CLOSED": _ANY_PAYLOAD,
        "TOPICS_CHANGED": _ANY_PAYLOAD,
        "TOPIC_STALE": _ANY_PAYLOAD,
    }
)
