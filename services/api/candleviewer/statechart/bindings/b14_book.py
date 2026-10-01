"""candleviewer.statechart.bindings.b14_book — MachineLogic stubs for B14 `book`
(E50-S02). Chart: `machines/B14.book.machine.json`.

Stubs only: business logic is owned by E06 order book (ticket "Out of scope").
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
    "apply_delta": _noop_action,
    "buffer_delta": _noop_action,
    "bump_resync_count": _noop_action,
    "clear_buffer": _noop_action,
    "emit_book_desynced": _noop_action,
    "emit_book_live": _noop_action,
    "emit_resync_metric": _noop_action,
    "install_snapshot": _noop_action,
    "replay_buffered_deltas_after_seq": _noop_action,
    "request_snapshot": _noop_action,
    "stamp_desync": _noop_action,
}

GUARDS: dict[str, Callable[..., bool]] = {}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {}

register_binding_module("book", __name__)

#: Permissive payload schemas (same shape as B16) so `strict=True` accepts
#: exactly the events this chart declares; owning epics tighten them.
_ANY_PAYLOAD: dict[str, Any] = {"type": "object", "additionalProperties": True}
register_event_schemas(
    {
        "DELTA": _ANY_PAYLOAD,
        "SEQUENCE_GAP": _ANY_PAYLOAD,
        "SNAPSHOT": _ANY_PAYLOAD,
        "SNAPSHOT_TIMEOUT": _ANY_PAYLOAD,
        "SUBSCRIBE": _ANY_PAYLOAD,
        "UNSUBSCRIBE": _ANY_PAYLOAD,
    }
)
