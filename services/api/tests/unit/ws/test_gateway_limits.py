"""Gateway deny branches and C-2.18 bounds (PR #1654 security review)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.ws import limits
from candleviewer.ws.gateway import make_ws_router
from candleviewer.ws.permissions import ConnectionAuthz, ConnectionRegistry, handle_sub
from candleviewer.ws.revocation import RevocationHub

USER = uuid.uuid4()


async def _resolve(uid: uuid.UUID) -> PrincipalSnapshot:
    return PrincipalSnapshot(uid, frozenset({"viewer"}), frozenset({Permission.MARKETDATA_READ}))


async def _authenticate(presented: str) -> tuple[str, uuid.UUID]:
    if presented != "ok":
        raise PermissionError("bad token")
    return "sess", USER


def _client(**kw: Any) -> TestClient:
    app = FastAPI()
    reg = ConnectionRegistry(_resolve, lambda: 1)
    app.include_router(
        make_ws_router(
            authenticate=_authenticate, registry=reg, revocation_hub=RevocationHub(), **kw
        )
    )
    return TestClient(app)


@pytest.mark.parametrize("payload", [{}, {"access_token": 7}, None, "x"])
def test_gateway_auth_without_string_token_closes_4401(payload: Any) -> None:
    with _client().websocket_connect("/ws") as ws:
        ws.send_json({"t": "auth", "id": "a", "p": payload})
        bye = ws.receive_json()
        assert (bye["t"], bye["p"]["reason"]) == ("bye", "auth_failed")
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4401


def test_gateway_non_object_and_non_json_frames_are_ignored() -> None:
    with _client().websocket_connect("/ws") as ws:
        ws.send_json([1, 2])
        ws.send_text("not json")
        ws.send_json({"t": "ping", "id": "p"})
        assert ws.receive_json() == {"t": "pong", "id": "p"}


def test_gateway_unauthenticated_socket_hits_deadline_4401() -> None:
    with _client(auth_timeout_s=0.05).websocket_connect("/ws") as ws:
        ws.send_json({"t": "hello", "id": "h"})
        assert ws.receive_json()["t"] == "welcome"
        bye = ws.receive_json()  # blocks until the server-side deadline fires
        assert bye["p"]["reason"] == "auth_timeout"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4401


def test_gateway_authenticated_socket_has_no_auth_deadline() -> None:
    with _client(auth_timeout_s=0.05).websocket_connect("/ws") as ws:
        ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "ok"}})
        assert ws.receive_json()["t"] == "auth_ok"
        ws.send_json({"t": "unsub", "id": "u", "p": {"topics": ["book.X", 3]}})
        assert ws.receive_json()["t"] == "unsub_ok"


@pytest.mark.parametrize("binary", [False, True])
def test_gateway_oversized_frame_closes_1009_before_parse(binary: bool) -> None:
    with _client(max_frame_bytes=64).websocket_connect("/ws") as ws:
        blob = '{"t":"ping","id":"' + "x" * 100 + '"}'
        if binary:
            ws.send_bytes(blob.encode())
        else:
            ws.send_text(blob)
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == limits.CLOSE_TOO_BIG


def _viewer() -> ConnectionAuthz:
    return ConnectionAuthz(
        PrincipalSnapshot(USER, frozenset({"viewer"}), frozenset({Permission.MARKETDATA_READ}))
    )


async def _collect_sub(authz: ConnectionAuthz, topics: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        out.append(frame)

    await handle_sub(authz, {"t": "sub", "id": "s", "p": {"topics": topics}}, send)
    results: list[dict[str, Any]] = out[0]["p"]["results"]
    return results


def test_sub_over_subscription_cap_is_rejected_and_set_does_not_grow() -> None:
    authz = _viewer()
    for start in range(0, limits.MAX_SUBSCRIPTIONS, limits.MAX_TOPICS_PER_SUB):
        topics = [f"book.S{i}" for i in range(start, start + limits.MAX_TOPICS_PER_SUB)]
        assert all(r["ok"] for r in asyncio.run(_collect_sub(authz, topics)))
    assert len(authz.subs) == limits.MAX_SUBSCRIPTIONS
    res = asyncio.run(_collect_sub(authz, ["book.extra", "book.S0"]))
    assert res[0]["error"]["code"] == "subscription_limit"
    assert res[1]["ok"] is True  # re-subscribing an existing topic needs no new slot
    assert len(authz.subs) == limits.MAX_SUBSCRIPTIONS
    assert authz.subscribe("book.extra2") is not None
    assert ("book.extra2", None) not in authz.subs


def test_sub_frame_with_too_many_topics_rejects_the_excess() -> None:
    authz = _viewer()
    topics = [f"book.T{i}" for i in range(limits.MAX_TOPICS_PER_SUB + 3)]
    res = asyncio.run(_collect_sub(authz, topics))
    assert [r["error"]["code"] for r in res if not r["ok"]] == ["too_many_topics"] * 3
    assert len(authz.subs) == limits.MAX_TOPICS_PER_SUB
    assert asyncio.run(_collect_sub(authz, "notalist")) == []  # type: ignore[arg-type]  # malformed frame


def test_roles_changed_stalled_socket_is_evicted_and_does_not_block_others() -> None:
    async def scenario() -> tuple[list[str], list[dict[str, Any]], int]:
        reg = ConnectionRegistry(_resolve, lambda: 1)
        reg.send_timeout_s = 0.05
        never = asyncio.Event()
        closed: list[str] = []
        good: list[dict[str, Any]] = []

        async def stalled(frame: dict[str, Any]) -> None:
            await never.wait()

        async def close_stalled() -> None:
            closed.append("stalled")

        async def ok(frame: dict[str, Any]) -> None:
            good.append(frame)

        async def broken(frame: dict[str, Any]) -> None:
            raise RuntimeError("socket gone")

        reg.register(_viewer(), stalled, close_stalled)
        reg.register(_viewer(), broken)  # no close hook: still evicted
        reg.register(_viewer(), ok)
        await reg.roles_changed(USER)
        await reg.roles_changed(USER)  # evicted sockets receive nothing more
        return closed, good, len(reg._conns[USER])

    closed, good, remaining = asyncio.run(scenario())
    assert closed == ["stalled"]
    assert [f["t"] for f in good] == ["permission_change", "permission_change"]
    assert remaining == 1


def test_gateway_client_disconnect_before_auth_cleans_up() -> None:
    with _client().websocket_connect("/ws") as ws:
        ws.send_json({"t": "hello", "id": "h"})
        assert ws.receive_json()["t"] == "welcome"
    # context exit = client close frame -> server leaves the loop without error


def test_gateway_evict_hook_sends_slow_consumer_and_closes_4429() -> None:
    app = FastAPI()
    reg = ConnectionRegistry(_resolve, lambda: 1)
    app.include_router(
        make_ws_router(authenticate=_authenticate, registry=reg, revocation_hub=RevocationHub())
    )
    client = TestClient(app)
    with client, client.websocket_connect("/ws") as ws:
        ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "ok"}})
        assert ws.receive_json()["t"] == "auth_ok"
        (_, _, evict) = reg._conns[USER][0]
        assert client.portal is not None
        client.portal.call(evict)
        assert ws.receive_json()["p"]["reason"] == "slow_consumer"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == limits.CLOSE_SLOW_CONSUMER
