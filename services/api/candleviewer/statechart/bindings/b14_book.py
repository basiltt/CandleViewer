"""candleviewer.statechart.bindings.b14_book - MachineLogic for B14 `book`
(E08-S05). Chart: `machines/B14.book.machine.json`.

Supervision only (INV-B14-a): the per-delta path never reaches these
bindings. `apply_delta` / `buffer_delta` stay no-ops because the book engine
applies/buffers deltas directly as plain code; the chart is told only about
lifecycle edges. Entry actions call the per-book runtime registered under
`context["input"]["book_key"]` (the statechart package never imports `book`).
With no runtime registered actions are no-ops (A6). Names are fixed by the
chart contract.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from candleviewer.statechart.bindings import register_binding_module
from candleviewer.statechart.config import register_event_schemas


class BookRuntime(Protocol):
    """Implemented by `candleviewer.book.resync.BookEngine`."""

    async def request_snapshot(self) -> None: ...
    async def go_live(self) -> None: ...
    async def go_desynced(self) -> None: ...


_RUNTIMES: dict[str, BookRuntime] = {}


def register_runtime(book_key: str, runtime: BookRuntime) -> None:
    _RUNTIMES[book_key] = runtime


def unregister_runtime(book_key: str) -> None:
    _RUNTIMES.pop(book_key, None)


def _rt(context: dict[str, Any]) -> BookRuntime | None:
    inp = context.get("input")
    key = inp.get("book_key") if isinstance(inp, dict) else context.get("book_key")
    return _RUNTIMES.get(str(key or ""))


async def _noop_action(*_args: object, **_kwargs: object) -> None:
    return None


async def request_snapshot(interp: Any, context: dict[str, Any], *_a: object) -> None:
    if (rt := _rt(context)) is not None:
        await rt.request_snapshot()


async def install_snapshot(interp: Any, context: dict[str, Any], *_a: object) -> None:
    if (rt := _rt(context)) is not None:
        await rt.go_live()


async def emit_book_desynced(interp: Any, context: dict[str, Any], *_a: object) -> None:
    if (rt := _rt(context)) is not None:
        await rt.go_desynced()


async def bump_resync_count(interp: Any, context: dict[str, Any], *_a: object) -> None:
    context["resync_count"] = int(context.get("resync_count", 0)) + 1


async def clear_buffer(interp: Any, context: dict[str, Any], *_a: object) -> None:
    context["buffered_deltas"] = []


ACTIONS: dict[str, Callable[..., Awaitable[None]]] = {
    "apply_delta": _noop_action,  # hot path: BookState.apply, never here
    "buffer_delta": _noop_action,  # hot path: BookEngine buffer, never here
    "bump_resync_count": bump_resync_count,
    "clear_buffer": clear_buffer,
    "emit_book_desynced": emit_book_desynced,
    "emit_book_live": _noop_action,  # LIVE status published by install_snapshot
    "emit_resync_metric": _noop_action,
    "install_snapshot": install_snapshot,
    "replay_buffered_deltas_after_seq": _noop_action,  # done inside go_live
    "request_snapshot": request_snapshot,
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
