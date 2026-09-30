"""Correlation context (E04-T02, US-OBS-003).

The seven correlation fields live in structlog's own contextvars store so the
`merge_contextvars` processor (E04-T01) stamps them on every log line with no
extra wiring. `spawn()` and `run_in_thread()` are the two sanctioned ways to
hop off the current task: both carry the context across, which bare
`asyncio.create_task` (copies, but is banned by Semgrep for app code so the
intent is explicit) and `run_in_executor` / `to_thread` (copies only
via `to_thread`; raw executors do not) cannot guarantee.
"""

from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from typing import Any, Final

import structlog

CORRELATION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "request_id",
        "conn_id",
        "user_id",
        "account_id",
        "symbol",
        "order_link_id",
        "trade_group_id",
    }
)


@contextmanager
def bind_context(**fields: Any) -> Iterator[None]:
    """Bind correlation fields for the duration of the `with` block.

    Unknown field names are rejected (closed set). `None` values are skipped.
    Previous values are restored on exit, so nested binds compose.
    """
    unknown = set(fields) - CORRELATION_FIELDS
    if unknown:
        raise ValueError(f"unknown correlation field(s): {sorted(unknown)}")
    values = {k: str(v) for k, v in fields.items() if v is not None}
    token = structlog.contextvars.bind_contextvars(**values)
    try:
        yield
    finally:
        structlog.contextvars.reset_contextvars(**token)


def get_context() -> dict[str, Any]:
    """Current correlation fields (for tests / outbound-request tagging)."""
    ctx = structlog.contextvars.get_contextvars()
    return {k: v for k, v in ctx.items() if k in CORRELATION_FIELDS}


def current_request_id() -> str | None:
    value = get_context().get("request_id")
    return str(value) if value is not None else None


def spawn[T](coro: Coroutine[Any, Any, T], *, name: str) -> asyncio.Task[T]:
    """`create_task` that explicitly runs under a copy of the current context."""
    ctx = contextvars.copy_context()
    return asyncio.get_running_loop().create_task(coro, name=name, context=ctx)


async def run_in_thread[T](func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Thread offload that carries the correlation context (unlike a raw executor)."""
    ctx = contextvars.copy_context()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: ctx.run(func, *args, **kwargs))
