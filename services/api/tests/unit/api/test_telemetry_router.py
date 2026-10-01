"""E04-T06: `POST /telemetry/frontend` — bounded, safe, counted rejections."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from candleviewer.api.telemetry import SessionKeyResolver, make_telemetry_router
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.telemetry import SessionRateLimiter, TelemetrySink

PATH = "/telemetry/frontend"


class _Resolver:
    def __init__(self, key: str | None = "sess-1") -> None:
        self.key = key

    async def resolve_session_key(self, request: Request) -> str | None:
        return self.key


def _payload(**over: Any) -> dict[str, Any]:
    p: dict[str, Any] = {
        "screen": "R-100",
        "engine_version": "0.1.0",
        "fe_frame_time_ms": {"counts": [10, 20, 5, 3, 1, 0, 0, 0, 1]},
        "fe_ws_decode_ms": {"counts": [50, 10, 0, 0, 0, 0, 0, 0, 0]},
        "fe_dropped_frames_total": 2,
        "fe_gpu_memory_mb": 128.5,
    }
    p.update(over)
    return p


def _client(
    resolver: Any = None, *, enabled: bool = True
) -> tuple[TestClient, Metrics, list[float]]:
    t = [0.0]
    m = Metrics("demo")
    app = FastAPI()
    app.include_router(
        make_telemetry_router(
            TelemetrySink(m),
            SessionRateLimiter(lambda: t[0]),
            _Resolver() if resolver is None else resolver,
            enabled=enabled,
        )
    )
    return TestClient(app), m, t


def _sample(m: Metrics, name: str, **labels: str) -> float:
    v = m.registry.get_sample_value(name, {"env": "demo", **labels})
    return 0.0 if v is None else v


def test_valid_payload_is_folded_into_server_histograms() -> None:
    c, m, _ = _client()
    assert c.post(PATH, json=_payload()).status_code == 204
    assert _sample(m, "fe_frame_time_ms_count", screen="R-100") == 40
    assert _sample(m, "fe_frame_time_ms_bucket", screen="R-100", le="4.0") == 10
    assert _sample(m, "fe_frame_time_ms_bucket", screen="R-100", le="16.0") == 38
    assert _sample(m, "fe_frame_time_ms_bucket", screen="R-100", le="100.0") == 39
    assert _sample(m, "fe_ws_decode_ms_count", screen="R-100") == 60
    assert _sample(m, "fe_dropped_frames_total", screen="R-100") == 2
    assert _sample(m, "fe_gpu_memory_mb", screen="R-100") == 128.5


def test_oversize_5mb_payload_rejected_400_and_counted() -> None:
    c, m, _ = _client()
    body = b"{" + b" " * (5 * 1024 * 1024) + b"}"
    r = c.post(PATH, content=body, headers={"content-type": "application/json"})
    assert r.status_code == 400
    assert _sample(m, "telemetry_rejected_total", reason="too_large") == 1


def test_oversize_streamed_body_without_length_rejected() -> None:
    c, m, _ = _client()

    def gen() -> Iterator[bytes]:
        for _ in range(10):
            yield b" " * 1024

    r = c.post(PATH, content=gen(), headers={"content-type": "application/json"})
    assert r.status_code == 400
    assert _sample(m, "telemetry_rejected_total", reason="too_large") == 1


def test_100_posts_per_second_rate_limited_429() -> None:
    c, m, _ = _client()
    codes = [c.post(PATH, json=_payload()).status_code for _ in range(100)]
    assert codes[:2] == [204, 204]
    assert set(codes[2:]) == {429}
    assert _sample(m, "telemetry_rejected_total", reason="rate_limited") == 98


def test_rate_limit_refills_after_interval() -> None:
    c, _, t = _client()
    for _ in range(3):
        c.post(PATH, json=_payload())
    t[0] += 10.0
    assert c.post(PATH, json=_payload()).status_code == 204


def test_unknown_field_rejected_400_and_not_logged_verbatim() -> None:
    c, m, _ = _client()
    marker = "MARKER-" + uuid.uuid4().hex
    with structlog.testing.capture_logs() as logs:
        r = c.post(PATH, json=_payload(symbol=marker))
    assert r.status_code == 400
    assert marker not in json.dumps(logs, default=str)
    assert marker not in r.text
    assert _sample(m, "telemetry_rejected_total", reason="invalid") == 1


def test_hostile_screen_value_rejected_and_creates_no_series() -> None:
    c, m, t = _client()
    for screen in ["/terminal/abc", "R-1000", 'R-10"0', "x" * 300]:
        t[0] += 20
        assert c.post(PATH, json=_payload(screen=screen)).status_code == 400
    text = generate_latest(m.registry).decode()
    assert "terminal" not in text and 'screen="' not in text


def test_wrong_types_and_bucket_lengths_rejected() -> None:
    c, m, t = _client()
    bad = [
        _payload(fe_dropped_frames_total="2"),
        _payload(fe_dropped_frames_total=-1),
        _payload(fe_frame_time_ms={"counts": [1, 2]}),
        _payload(fe_ws_decode_ms={"counts": [1.5] * 9}),
        _payload(fe_frame_time_ms={"counts": [10**9] * 9}),
    ]
    for body in bad:
        t[0] += 20
        assert c.post(PATH, json=body).status_code == 400
    assert _sample(m, "telemetry_rejected_total", reason="invalid") == len(bad)


def test_screen_series_bounded_by_max_series() -> None:
    c, m, t = _client()
    for i in range(100):
        t[0] += 20
        c.post(PATH, json=_payload(screen=f"R-{i:03d}"))
    assert m.get("fe_frame_time_ms").series_count <= 8


def test_unauthenticated_is_401_and_counted() -> None:
    c, m, _ = _client(_Resolver(None))
    assert c.post(PATH, json=_payload()).status_code == 401
    assert _sample(m, "telemetry_rejected_total", reason="unauthenticated") == 1


def test_no_resolver_wired_fails_closed_501() -> None:
    m = Metrics("demo")
    app = FastAPI()
    app.include_router(make_telemetry_router(TelemetrySink(m), SessionRateLimiter(lambda: 0.0)))
    assert TestClient(app).post(PATH, json=_payload()).status_code == 501


def test_disabled_accepts_and_discards() -> None:
    c, m, _ = _client(enabled=False)
    assert c.post(PATH, json=_payload()).status_code == 204
    assert _sample(m, "fe_frame_time_ms_count", screen="R-100") == 0


def test_limiter_memory_bounded() -> None:
    lim = SessionRateLimiter(lambda: 0.0, max_sessions=8)
    for i in range(100):
        lim.allow(f"s{i}")
    assert len(lim) == 8


@dataclass
class _P:
    user_id: uuid.UUID
    session_id: uuid.UUID | None


class _PR:
    def __init__(self, p: _P | None) -> None:
        self.p = p

    async def resolve(self, request: Request) -> _P | None:
        return self.p


def test_session_key_resolver_adapts_principal() -> None:
    u, s = uuid.uuid4(), uuid.uuid4()
    req: Any = None
    assert asyncio.run(SessionKeyResolver(_PR(_P(u, s))).resolve_session_key(req)) == str(s)
    assert asyncio.run(SessionKeyResolver(_PR(_P(u, None))).resolve_session_key(req)) == str(u)
    assert asyncio.run(SessionKeyResolver(_PR(None)).resolve_session_key(req)) is None
