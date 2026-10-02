"""Live WS gateway endpoint (`23-ws-protocol.md` §4-§5, §9.5; QA #1648 d1).

Wires the authorisation building blocks onto a real socket:

- `hello` -> `welcome`; `auth` -> the opaque access token is verified by the
  injected `authenticate` (ADR-0020 session lookup), the principal snapshot
  is resolved, the socket is registered with the `ConnectionRegistry` (for
  `permission_change` pushes) and the `RevocationHub` (4401 on revoke), and
  `auth_ok` carries roles/permissions/account scope.
- `sub` -> every topic checked against permission AND account scope.
- Anything else before `auth_ok` -> `err not_authenticated`; a failed `auth`
  -> `bye auth_failed` + close 4401 (fail closed).

Resource bounds (C-2.18) live in `candleviewer.ws.limits` together with the
overflow policy: inbound size checked before `json.loads` (1009), auth
deadline (`bye auth_timeout` + 4401), subscription caps, bounded fan-out.

Transport only: no business logic, no data fan-out (owned by E17).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from candleviewer.ws.errors import build_ws_error
from candleviewer.ws.limits import (
    AUTH_TIMEOUT_S,
    CLOSE_SLOW_CONSUMER,
    CLOSE_TOO_BIG,
    MAX_INBOUND_FRAME_BYTES,
)
from candleviewer.ws.permissions import (
    ConnectionAuthz,
    ConnectionRegistry,
    close_connection,
    handle_sub,
    open_connection,
)
from candleviewer.ws.revocation import CLOSE_TOKEN_EXPIRED, RevocationHub, bye_frame

WS_PATH = "/ws"

#: (raw access token) -> (session_id, user_id); raises on any invalid token.
Authenticate = Callable[[str], Awaitable[tuple[str, uuid.UUID]]]


def make_ws_router(
    *,
    authenticate: Authenticate,
    registry: ConnectionRegistry,
    revocation_hub: RevocationHub,
    auth_timeout_s: float = AUTH_TIMEOUT_S,
    max_frame_bytes: int = MAX_INBOUND_FRAME_BYTES,
) -> APIRouter:
    router = APIRouter()

    @router.websocket(WS_PATH)
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        lock = asyncio.Lock()

        async def send(frame: dict[str, Any]) -> None:
            async with lock:
                await ws.send_json(frame)

        async def closer(frame: dict[str, Any], code: int) -> None:
            await send(frame)
            await ws.close(code=code)

        async def evict() -> None:
            await closer(bye_frame("slow_consumer"), CLOSE_SLOW_CONSUMER)

        async def receive() -> Any:
            """One inbound frame; `None` after closing 1009 when oversized.
            Size is checked on the raw payload BEFORE any JSON decoding."""
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect(int(msg.get("code") or 1000))
            raw: str | bytes = msg.get("text") or msg.get("bytes") or ""
            size = len(raw.encode()) if isinstance(raw, str) else len(raw)
            if size > max_frame_bytes:
                await ws.close(code=CLOSE_TOO_BIG)
                return None
            try:
                return json.loads(raw)
            except ValueError:
                return []  # malformed -> ignored like any non-object frame

        authz: ConnectionAuthz | None = None
        session_id: str | None = None
        loop = asyncio.get_running_loop()
        auth_deadline = loop.time() + auth_timeout_s
        try:
            while True:
                if authz is None:
                    try:
                        async with asyncio.timeout_at(auth_deadline):
                            frame = await receive()
                    except TimeoutError:
                        await closer(bye_frame("auth_timeout"), CLOSE_TOKEN_EXPIRED)
                        return
                else:
                    frame = await receive()
                if frame is None:
                    return
                if not isinstance(frame, dict):
                    continue
                kind = frame.get("t")
                if kind == "ping":
                    await send({"t": "pong", "id": frame.get("id")})
                elif kind == "hello":
                    await send(
                        {"t": "welcome", "id": frame.get("id"), "p": {"auth_required": True}}
                    )
                elif kind == "auth" and authz is None:
                    body = frame.get("p")
                    token = body.get("access_token") if isinstance(body, dict) else None
                    try:
                        if not isinstance(token, str):
                            raise ValueError("missing access_token")
                        session_id, user_id = await authenticate(token)
                    except Exception:
                        await closer(bye_frame("auth_failed"), CLOSE_TOKEN_EXPIRED)
                        return
                    principal = await registry.resolve(user_id)
                    revocation_hub.register(session_id, closer)
                    authz = await open_connection(
                        registry, principal, send, close=evict, session_id=session_id
                    )
                elif authz is None:
                    await send(build_ws_error("not_authenticated", id=frame.get("id")))
                elif kind == "sub":
                    await handle_sub(authz, frame, send)
                elif kind == "unsub":
                    for ch in (frame.get("p") or {}).get("topics") or []:
                        if isinstance(ch, str):
                            authz.unsubscribe(ch)
                    await send({"t": "unsub_ok", "id": frame.get("id")})
        except WebSocketDisconnect:
            pass
        finally:
            if authz is not None:
                close_connection(registry, authz)
            if session_id is not None:
                revocation_hub.unregister(session_id, closer)

    return router
