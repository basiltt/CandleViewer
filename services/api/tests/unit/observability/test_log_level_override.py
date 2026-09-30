"""E04-T02 runtime log-level override: scoping, TTL revert, RBAC, audit."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.log_level import make_log_level_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.observability.log_level import LogLevelOverrides, LogLevelRequest


class _Clock:
    t = 1000.0

    def __call__(self) -> float:
        return self.t


class _Sink:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def record(self, *, component: str, kind: str, detail: dict[str, object]) -> None:
        self.rows.append({"component": component, "kind": kind, **detail})


async def test_override_scoped_and_expires() -> None:
    clock, sink = _Clock(), _Sink()
    ov = LogLevelOverrides(clock=clock, sink=sink)
    ing = logging.getLogger("candleviewer.ingestion.x")
    oms = logging.getLogger("candleviewer.oms.x")
    base_ing, base_oms = ing.getEffectiveLevel(), oms.getEffectiveLevel()
    await ov.apply(LogLevelRequest(subsystem="ingestion", level="debug", ttl_seconds=60))
    assert ing.getEffectiveLevel() == logging.DEBUG
    assert oms.getEffectiveLevel() == base_oms
    assert ov.active_count == 1
    clock.t += 59
    await ov.tick()
    assert ing.getEffectiveLevel() == logging.DEBUG
    clock.t += 2
    await ov.tick()
    assert ing.getEffectiveLevel() == base_ing
    assert ov.active_count == 0
    assert [r["phase"] for r in sink.rows] == ["set", "expired"]
    assert all(r["component"] == "api" and r["kind"] == "log_level_override" for r in sink.rows)


async def test_override_reapply_keeps_original_baseline() -> None:
    ov = LogLevelOverrides(clock=_Clock())
    lg = logging.getLogger("candleviewer.rules")
    base = lg.level
    await ov.apply(LogLevelRequest(subsystem="rules", level="debug"))
    await ov.apply(LogLevelRequest(subsystem="rules", level="warning"))
    await ov.revert("rules")
    assert lg.level == base


async def test_ticker_start_stop_idempotent() -> None:
    ov = LogLevelOverrides()
    ov.start()
    ov.start()
    await ov.stop()
    await ov.stop()


@pytest.mark.parametrize("bad", ["root", "", "ROOT", "cv"])
def test_closed_set_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        LogLevelRequest.model_validate({"subsystem": bad, "level": "debug"})


@pytest.mark.parametrize("ttl", [0, 3601, -1])
def test_ttl_bounds(ttl: int) -> None:
    with pytest.raises(ValueError):
        LogLevelRequest(subsystem="oms", level="debug", ttl_seconds=ttl)


def test_default_ttl_and_extra_forbidden() -> None:
    assert LogLevelRequest(subsystem="oms", level="info").ttl_seconds == 900
    with pytest.raises(ValueError):
        LogLevelRequest.model_validate({"subsystem": "oms", "level": "info", "x": 1})


class _Audit:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.calls.append((action, kw))


class _Resolver:
    def __init__(self, perms: set[str] | None) -> None:
        self.p = (
            None
            if perms is None
            else AuditPrincipal(uuid.uuid4(), "bob", frozenset(perms), request_id=uuid.uuid4())
        )

    def resolve(self, request: Any) -> AuditPrincipal | None:
        return self.p


def _client(
    resolver: _Resolver | None, audit: _Audit | None = None
) -> tuple[TestClient, LogLevelOverrides, _Audit]:
    a = audit or _Audit()
    ov = LogLevelOverrides()
    app = FastAPI()
    app.include_router(make_log_level_router(ov, a, resolver))
    return TestClient(app), ov, a


BODY = {"subsystem": "ingestion", "level": "debug", "ttl_seconds": 60}


def test_endpoint_viewer_denied_and_audited() -> None:
    c, ov, a = _client(_Resolver({"audit:read"}))
    assert c.put("/admin/log-level", json=BODY).status_code == 403
    assert ov.active_count == 0
    assert a.calls[0][0] == "settings.change"
    assert a.calls[0][1]["outcome"].value == "denied"


def test_endpoint_admin_applies_and_audits() -> None:
    c, ov, a = _client(_Resolver({"admin:write"}))
    r = c.put("/admin/log-level", json=BODY)
    assert r.status_code == 200
    assert r.json()["ttl_seconds"] == 60
    assert ov.active_count == 1
    assert a.calls[0][0] == "settings.change"
    logging.getLogger("candleviewer.ingestion").setLevel(logging.NOTSET)


def test_endpoint_invalid_body_rejected() -> None:
    c, ov, _ = _client(_Resolver({"*"}))
    r = c.put("/admin/log-level", json={"subsystem": "root", "level": "debug"})
    assert r.status_code == 400
    assert ov.active_count == 0


def test_endpoint_unwired_unauthenticated_and_no_audit() -> None:
    assert _client(None)[0].put("/admin/log-level", json=BODY).status_code == 501
    assert _client(_Resolver(None))[0].put("/admin/log-level", json=BODY).status_code == 401
    app = FastAPI()
    app.include_router(make_log_level_router(LogLevelOverrides(), None, _Resolver({"*"})))
    assert TestClient(app).put("/admin/log-level", json=BODY).status_code == 503
