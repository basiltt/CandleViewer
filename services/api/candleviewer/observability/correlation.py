"""ASGI correlation middleware + WS binding hooks (E04-T02).

Inbound `X-Correlation-Id` is untrusted input destined for a log field
(SR-120/123): only a canonical lowercase/uppercase UUIDv4 of exactly 36
characters is accepted; anything else is discarded and replaced, and the
rejected value is never logged.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from typing import Any, Final

from candleviewer.observability.context import bind_context

CORRELATION_HEADER: Final[str] = "X-Correlation-Id"
_HEADER_LC: Final[bytes] = b"x-correlation-id"
_UUID4_RE: Final[re.Pattern[str]] = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.IGNORECASE
)


def sanitize_correlation_id(raw: str | None) -> str:
    """Return `raw` (normalised) if a valid UUIDv4, else a freshly minted one."""
    if raw is not None and len(raw) == 36 and _UUID4_RE.fullmatch(raw):
        return raw.lower()
    return str(uuid.uuid4())


class CorrelationMiddleware:
    """Pure-ASGI middleware: bind `request_id`, echo it on the response."""

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: MutableMapping[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return
        inbound: str | None = None
        for key, value in scope.get("headers", []):
            if key.lower() == _HEADER_LC and len(value) <= 64:
                inbound = value.decode("latin-1")
                break
        request_id = sanitize_correlation_id(inbound)
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_wrapper(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != _HEADER_LC]
                headers.append((_HEADER_LC, request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        with bind_context(request_id=request_id):
            await self._app(scope, receive, send_wrapper)


@contextmanager
def ws_connection_context(*, user_id: object = None) -> Iterator[str]:
    """Bind a fresh `conn_id` at `auth_ok` (23-ws-protocol.md §6); yields it.

    The gateway wraps the whole connection handler in this so every frame
    logged for the connection carries `conn_id` (and `user_id`).
    """
    conn_id = str(uuid.uuid4())
    with bind_context(conn_id=conn_id, user_id=user_id):
        yield conn_id


@contextmanager
def ws_frame_context(frame_request_id: str | None = None) -> Iterator[str]:
    """Bind a per-inbound-frame `request_id` (validated like the HTTP header)."""
    request_id = sanitize_correlation_id(frame_request_id)
    with bind_context(request_id=request_id):
        yield request_id
