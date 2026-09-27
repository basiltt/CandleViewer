"""ASGI middleware rejecting off-mesh requests before authentication.

Applies to both HTTP and the WS upgrade (ASGI `scope["type"]` in
`{"http", "websocket"}`). The source address is taken from the ASGI
`scope["client"]` socket peer tuple only; a client-controllable header
(`X-Forwarded-For` and friends) is never consulted unless an explicitly
configured trusted proxy sits in front — and even then only that proxy's
own immediate peer address is trusted to supply it, never an arbitrary
downstream hop.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .audit import AuditSink, NullAuditSink
from .cidr import CidrAllowList
from .read_only_gate import ReadOnlyGate

_GENERIC_403_BODY = b'{"detail":"Forbidden"}'


class MeshOnlyMiddleware:
    """Rejects any request whose real source address is off-mesh.

    `trusted_proxy_header` is `None` by default (no trusted proxy
    configured): headers are always ignored and only `scope["client"]` is
    used. When a trusted proxy is explicitly configured, pass its header
    name here — the middleware still requires the *immediate* peer to be
    the configured proxy address before it will read the header.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        allow_list: CidrAllowList,
        read_only_gate: ReadOnlyGate | None = None,
        audit_sink: AuditSink | None = None,
        trusted_proxy_header: str | None = None,
        trusted_proxy_address: str | None = None,
    ) -> None:
        self._app = app
        self._allow_list = allow_list
        self._gate = read_only_gate
        self._audit = audit_sink or NullAuditSink()
        self._trusted_proxy_header = trusted_proxy_header
        self._trusted_proxy_address = trusted_proxy_address

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        source = self._resolve_source_address(scope)
        if source is not None and self._allow_list.is_allowed(source):
            await self._app(scope, receive, send)
            return

        self._audit.emit(
            "net.off_mesh_request",
            severity="warning",
            source_address=source,
            path=scope.get("path"),
            scope_type=scope["type"],
        )
        await self._reject(scope, send)

    def _resolve_source_address(self, scope: Scope) -> str | None:
        client = scope.get("client")
        peer_address: str | None = client[0] if client else None

        if self._trusted_proxy_header is None or self._trusted_proxy_address is None:
            return peer_address
        if peer_address != self._trusted_proxy_address:
            # Off-mesh caller cannot forge an on-mesh address via the header
            # unless it is arriving directly from the configured proxy.
            return peer_address

        headers = dict(scope.get("headers") or [])
        raw = headers.get(self._trusted_proxy_header.lower().encode("latin-1"))
        if raw is None:
            return peer_address
        # Only the first, left-most hop is trusted (the proxy's own client).
        forwarded: str = raw.decode("latin-1").split(",")[0].strip()
        return forwarded

    async def _reject(self, scope: Scope, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4403})
            return
        message: Message = {
            "type": "http.response.start",
            "status": 403,
            "headers": [(b"content-type", b"application/json")],
        }
        await send(message)
        await send({"type": "http.response.body", "body": _GENERIC_403_BODY})
