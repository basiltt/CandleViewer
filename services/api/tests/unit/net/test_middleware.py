"""Unit tests for MeshOnlyMiddleware (E09-T04).

Uses raw ASGI scope/receive/send fakes (no real sockets, no network) so the
"rejection happens before authentication" and "header cannot forge an
on-mesh source" scenarios can be asserted precisely.
"""

from __future__ import annotations

import pytest

from candleviewer.net.audit import InMemoryAuditSink
from candleviewer.net.cidr import CidrAllowList
from candleviewer.net.middleware import MeshOnlyMiddleware

MESH_CIDR = "100.64.0.0/10"


async def _downstream_app(scope: dict, receive: object, send: object) -> None:
    """An app that would only be reached if auth/handling were allowed to run."""
    if scope["type"] == "websocket":
        await send({"type": "websocket.accept"})
        return
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def _http_scope(client_host: str, headers: list[tuple[bytes, bytes]] | None = None) -> dict:
    return {
        "type": "http",
        "path": "/v1/orders",
        "client": (client_host, 12345),
        "headers": headers or [],
    }


class _Sent:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def __call__(self, message: dict) -> None:
        self.messages.append(message)


async def _noop_receive() -> dict:
    return {"type": "http.request"}


@pytest.mark.asyncio
async def test_on_mesh_request_reaches_downstream_app() -> None:
    allow_list = CidrAllowList([MESH_CIDR])
    mw = MeshOnlyMiddleware(_downstream_app, allow_list=allow_list)
    sent = _Sent()

    await mw(_http_scope("100.70.1.2"), _noop_receive, sent)

    assert sent.messages[0]["status"] == 200


@pytest.mark.asyncio
async def test_off_mesh_request_is_rejected_with_generic_403() -> None:
    allow_list = CidrAllowList([MESH_CIDR])
    mw = MeshOnlyMiddleware(_downstream_app, allow_list=allow_list)
    sent = _Sent()

    await mw(_http_scope("8.8.8.8"), _noop_receive, sent)

    assert sent.messages[0]["status"] == 403
    assert b"Forbidden" in sent.messages[1]["body"]
    # Generic body: no hint about the allowed CIDR.
    assert MESH_CIDR.encode() not in sent.messages[1]["body"]


@pytest.mark.asyncio
async def test_off_mesh_request_never_reaches_downstream_app() -> None:
    calls: list[str] = []

    async def _tracking_app(scope: dict, receive: object, send: object) -> None:
        calls.append("reached")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    allow_list = CidrAllowList([MESH_CIDR])
    mw = MeshOnlyMiddleware(_tracking_app, allow_list=allow_list)
    sent = _Sent()

    await mw(_http_scope("8.8.8.8"), _noop_receive, sent)

    assert calls == []


@pytest.mark.asyncio
async def test_off_mesh_request_is_audited_with_source_address() -> None:
    allow_list = CidrAllowList([MESH_CIDR])
    audit = InMemoryAuditSink()
    mw = MeshOnlyMiddleware(_downstream_app, allow_list=allow_list, audit_sink=audit)
    sent = _Sent()

    await mw(_http_scope("8.8.8.8"), _noop_receive, sent)

    assert len(audit.events) == 1
    event = audit.events[0]
    assert event["event"] == "net.off_mesh_request"
    assert event["severity"] == "warning"
    assert event["source_address"] == "8.8.8.8"


@pytest.mark.asyncio
async def test_websocket_upgrade_from_off_mesh_is_closed() -> None:
    allow_list = CidrAllowList([MESH_CIDR])
    mw = MeshOnlyMiddleware(_downstream_app, allow_list=allow_list)
    sent = _Sent()
    scope = {"type": "websocket", "path": "/ws", "client": ("8.8.8.8", 1), "headers": []}

    await mw(scope, _noop_receive, sent)

    assert sent.messages[0] == {"type": "websocket.close", "code": 4403}


@pytest.mark.asyncio
async def test_header_cannot_forge_on_mesh_source_without_trusted_proxy() -> None:
    allow_list = CidrAllowList([MESH_CIDR])
    mw = MeshOnlyMiddleware(_downstream_app, allow_list=allow_list)
    sent = _Sent()
    scope = _http_scope("8.8.8.8", headers=[(b"x-forwarded-for", b"100.70.1.2")])

    await mw(scope, _noop_receive, sent)

    assert sent.messages[0]["status"] == 403


@pytest.mark.asyncio
async def test_header_is_honoured_only_from_the_configured_trusted_proxy() -> None:
    allow_list = CidrAllowList([MESH_CIDR])
    mw = MeshOnlyMiddleware(
        _downstream_app,
        allow_list=allow_list,
        trusted_proxy_header="x-forwarded-for",
        trusted_proxy_address="127.0.0.1",
    )
    sent = _Sent()
    scope = _http_scope("127.0.0.1", headers=[(b"x-forwarded-for", b"100.70.1.2")])

    await mw(scope, _noop_receive, sent)

    assert sent.messages[0]["status"] == 200
