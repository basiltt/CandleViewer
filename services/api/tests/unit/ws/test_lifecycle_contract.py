"""E17-S01 contract: every lifecycle control frame the gateway emits validates
against the `23-ws-protocol.md` §13 schemas (bundled in `docs/plan/ws-schema.json`)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from candleviewer.ws.lifecycle import CLOSE_REASONS, bye_frame
from tests.unit.ws.test_lifecycle_socket import (
    JSON,
    TOKEN_TTL_S,
    _auth,
    _bye_then_close,
    _hello,
    _recv,
    _World,
)

_BUNDLE = Path(__file__).resolve().parents[5] / "docs" / "plan" / "ws-schema.json"
_SCHEMAS: dict[str, Any] = json.loads(_BUNDLE.read_text(encoding="utf-8"))["schemas"]
_REGISTRY: Registry[Any] = Registry().with_resources(
    (sid, Resource.from_contents(body)) for sid, body in _SCHEMAS.items()
)
_PAYLOAD_SCHEMA = {
    "hello": "hello",
    "welcome": "welcome",
    "auth": "auth",
    "auth_ok": "auth_ok",
    "ping": "heartbeat",
    "pong": "heartbeat",
    "bye": "bye",
}


def _validate(frame: dict[str, Any]) -> None:
    def check(schema_id: str, doc: Any) -> None:
        validator = Draft202012Validator(_SCHEMAS[schema_id], registry=_REGISTRY)
        errors = sorted(validator.iter_errors(doc), key=str)
        assert not errors, f"{frame['t']}: {[e.message for e in errors]}"

    check("cv://ws/v1/envelope.schema.json", frame)
    name = _PAYLOAD_SCHEMA.get(frame["t"])
    if name is not None:
        check(f"cv://ws/v1/{name}.schema.json", frame.get("p", {}))


def test_handshake_heartbeat_and_bye_frames_validate_against_section_13() -> None:
    w = _World()
    hello = {
        "t": "hello",
        "id": "c-1",
        "p": {
            "client": "candleviewer-web",
            "client_version": "1.0.0",
            "protocol": "cv.v1",
            "clock_ms": 1_789_132_261_980,
        },
    }
    auth = {"t": "auth", "id": "c-2", "p": {"access_token": "good-" + "x" * 20}}
    ping = {"t": "ping", "id": "c-hb-1", "p": {"client_ms": 1_789_132_261_990}}
    for client_frame in (hello, auth, ping):
        _validate(client_frame)
    with w.client, w.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        ws.send_json(hello)
        frames = [_recv(ws)]
        ws.send_json(auth)
        frames.append(_recv(ws))
        ws.send_json(ping)
        frames.append(_recv(ws))
        w.clock.now = 20.0
        frames.append(_recv(ws))  # unsolicited server ping
        w.clock.now = float(TOKEN_TTL_S)
        bye, _ = _bye_then_close(ws)
        frames.append(bye)
    assert [f["t"] for f in frames] == ["welcome", "auth_ok", "pong", "ping", "bye"]
    for frame in frames:
        _validate(frame)
    assert uuid.UUID(frames[1]["p"]["session_id"])


@pytest.mark.parametrize("reason", sorted(CLOSE_REASONS))
def test_every_bye_reason_validates(reason: str) -> None:
    _validate(bye_frame(reason, now_ms=1_789_132_262_000, retry_after_ms=0))


def test_err_frames_on_the_lifecycle_paths_validate_against_the_envelope() -> None:
    w = _World()
    with w.client, w.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        ws.send_json({"t": "sub", "id": "s", "p": {"topics": ["book.BTCUSDT.50"]}})
        _validate(_recv(ws))
        _validate(_auth(ws, "bad"))
