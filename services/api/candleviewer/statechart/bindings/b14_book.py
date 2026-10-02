"""candleviewer.statechart.bindings.b14_book - MachineLogic for B14 `book`
(E08-S05). Chart: `machines/B14.book.machine.json`.

Record-only (C-2.20, C-2.21, INV-B14-a): the book engine enforces and
executes the whole lifecycle as plain code and forwards lifecycle edges
fire-and-forget through `candleviewer.ingestion.book_supervisor`. These
actions only maintain chart context; they never call back into the book and
never send events. Names are fixed by the chart contract.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from candleviewer.statechart.bindings import register_binding_module
from candleviewer.statechart.config import register_event_schemas


async def _noop_action(*_args: object, **_kwargs: object) -> None:
    return None


async def bump_resync_count(interp: Any, context: dict[str, Any], *_a: object) -> None:
    context["resync_count"] = int(context.get("resync_count", 0)) + 1


async def clear_buffer(interp: Any, context: dict[str, Any], *_a: object) -> None:
    context["buffered_deltas"] = []


ACTIONS: dict[str, Callable[..., Awaitable[None]]] = {
    "apply_delta": _noop_action,  # hot path: BookState.apply, never here
    "buffer_delta": _noop_action,  # hot path: BookEngine buffer, never here
    "bump_resync_count": bump_resync_count,
    "clear_buffer": clear_buffer,
    "emit_book_desynced": _noop_action,  # executed by BookEngine
    "emit_book_live": _noop_action,  # LIVE status published by BookEngine.go_live
    "emit_resync_metric": _noop_action,
    "install_snapshot": _noop_action,  # executed by BookEngine
    "replay_buffered_deltas_after_seq": _noop_action,  # done inside go_live
    "request_snapshot": _noop_action,  # executed by BookEngine
    "stamp_desync": _noop_action,
}

GUARDS: dict[str, Callable[..., bool]] = {}

SERVICES: dict[str, Callable[..., Awaitable[Any]]] = {}

register_binding_module("book", __name__)

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
