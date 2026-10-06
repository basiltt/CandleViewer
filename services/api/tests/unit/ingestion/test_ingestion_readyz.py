"""#1919: `/readyz` and the health registry surface ingestion DEGRADED (C-13.6 #1, SCR-152)."""

from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.health import make_health_router
from candleviewer.health_wiring import ingestion_state
from candleviewer.ingestion.connection import PHASE_CONNECTING, PHASE_OPEN
from candleviewer.ingestion.service import WS_GRACE_S, HealthReason, IngestionService
from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.observability.health_probes import ComponentState
from candleviewer.settings import Settings


class _Ws:
    def __init__(self, t: list[float]) -> None:
        self.t, self.phase, self.since = t, PHASE_OPEN, t[0]

    def set(self, phase: str) -> None:
        self.phase, self.since = phase, self.t[0]

    def state(self) -> str:
        return self.phase

    def phase_since(self) -> float:
        return self.since


def test_readyz_degraded_with_reasons_then_ok() -> None:
    t = [10.0]
    svc = IngestionService(clock=lambda: t[0])
    svc._started = True
    ws = _Ws(t)
    svc.ws = cast(Any, ws)
    app = FastAPI()
    app.include_router(make_health_router(Settings(), ingestion_health=svc.health))
    client = TestClient(app)
    assert client.get("/readyz").json()["status"] == "ok"
    ws.set(PHASE_CONNECTING)  # total feed outage
    t[0] += WS_GRACE_S + 15  # the 20 s outage of #1919
    resp = client.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"] == [
        {"name": "ingestion", "ok": False, "detail": HealthReason.WS_NOT_OPEN.value}
    ]
    ws.set(PHASE_OPEN)
    body = client.get("/readyz").json()
    assert body["status"] == "ok" and body["checks"][0]["ok"] is True


def test_probe_maps_status_to_component_state() -> None:
    def rep(st: HealthStatus, d: str = "") -> HealthReport:
        return HealthReport(module="ingestion", status=st, detail=d)

    assert ingestion_state(rep(HealthStatus.OK)).state is ComponentState.HEALTHY
    degraded = ingestion_state(rep(HealthStatus.DEGRADED, "ws_not_open"))
    assert (degraded.state, degraded.detail) == (ComponentState.DEGRADED, "ws_not_open")
    assert ingestion_state(rep(HealthStatus.STOPPED)).state is ComponentState.NOT_DEPLOYED
