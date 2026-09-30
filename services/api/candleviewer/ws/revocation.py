"""Session-revocation -> WebSocket `4401` close (23-ws-protocol.md §9.5, US-ONB-009).

Transport-agnostic: the (E17) gateway registers one `Closer` per live socket
keyed by session id; the session router's `publish_revocation` calls
`RevocationHub.revoke`, which sends the `bye` frame and closes with 4401.
Latency is observed on `auth_revocation_latency_seconds` (alert > 5 s).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from candleviewer.observability.metrics import Counter, Histogram

_log = logging.getLogger(__name__)
CLOSE_TOKEN_EXPIRED = 4401

auth_revocation_latency_seconds = Histogram(
    "ws_session_revocation_close_seconds",
    "Seconds from session revocation to its WebSocket being closed.",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

ws_revocation_close_failures_total = Counter(
    "ws_session_revocation_close_failures_total",
    "WebSocket closes that failed during session revocation (socket may remain open).",
)

Closer = Callable[[dict[str, Any], int], Awaitable[None]]  # (bye frame, close code)


def bye_frame(reason: str) -> dict[str, Any]:
    return {
        "t": "bye",
        "p": {
            "code": CLOSE_TOKEN_EXPIRED,
            "reason": reason,
            "message": "session revoked",
            "reconnect": False,
        },
    }


class RevocationHub:
    def __init__(self) -> None:
        self._sockets: dict[str, list[Closer]] = defaultdict(list)

    def register(self, session_id: str, closer: Closer) -> None:
        self._sockets[session_id].append(closer)

    def unregister(self, session_id: str, closer: Closer) -> None:
        if closer in self._sockets.get(session_id, []):
            self._sockets[session_id].remove(closer)
        if not self._sockets.get(session_id):
            self._sockets.pop(session_id, None)

    async def revoke(self, session_id: str, reason: str = "session_revoked") -> int:
        """Close every socket of `session_id`; returns how many were closed."""
        closers = self._sockets.pop(session_id, [])
        started = time.monotonic()
        for closer in closers:
            try:
                await closer(bye_frame(reason), CLOSE_TOKEN_EXPIRED)
            except Exception:
                ws_revocation_close_failures_total.inc()
                _log.error(
                    "ws revocation close failed; revoked socket may remain open",
                    extra={"session_id": session_id},
                    exc_info=True,
                )
        if closers:
            auth_revocation_latency_seconds.observe(time.monotonic() - started)
        return len(closers)
