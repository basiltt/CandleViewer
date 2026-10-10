"""`GET /market/data-coverage` (E16-T04): RBAC, validation, and the `DataCoverage` shape."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api._generated.openapi_models import DataCoverage, Problem
from candleviewer.api.market import MarketDataPrincipal
from candleviewer.api.market_coverage import make_data_coverage_router
from candleviewer.recorder.coverage import CoverageService
from candleviewer.recorder.sessions import to_dt, to_us
from tests.unit.recorder._session_fakes import MemRecorderStore, UsClock

NOW = to_us(datetime(2026, 9, 14, 10, 31, tzinfo=UTC))


class _Resolver:
    def __init__(self, perms: frozenset[str] | None) -> None:
        self._perms = perms

    def resolve(self, request: Request) -> MarketDataPrincipal | None:
        return None if self._perms is None else MarketDataPrincipal("u1", self._perms)


class _Boom(CoverageService):
    async def coverage(self, *a: Any, **k: Any) -> Any:
        raise TimeoutError


async def _seed(store: MemRecorderStore) -> None:
    sid = await store.open_session_at(
        recorded_symbol_id="r", symbol="BTCUSDT", streams=["trades"], orderbook_depth=1,
        ws_endpoint="x", started_at=datetime(2026, 9, 1, tzinfo=UTC),
    )  # fmt: skip
    await store.record_gap(
        session_id=sid, symbol="BTCUSDT", stream="trades",
        gap_start=datetime(2026, 9, 4, 2, 11, tzinfo=UTC),
        gap_end=datetime(2026, 9, 4, 2, 14, 20, tzinfo=UTC), cause="process_restart",
    )  # fmt: skip


def _client(
    service: CoverageService | None, perms: frozenset[str] | None = frozenset({"marketdata:read"}),
    *, wired: bool = True,
) -> TestClient:  # fmt: skip
    app = FastAPI()
    app.include_router(
        make_data_coverage_router(
            lambda: service,
            principal_resolver=_Resolver(perms) if wired else None,
            now_us=lambda: NOW,
        )
    )
    return TestClient(app, client=("127.0.0.1", 50000))


async def test_coverage_report_matches_contract_schema() -> None:
    store = MemRecorderStore()
    await _seed(store)
    svc = CoverageService(store, now_us=UsClock(NOW))
    resp = _client(svc).get(
        "/market/data-coverage", params=[("symbol", "BTCUSDT"), ("stream", "trades")]
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    DataCoverage.model_validate(body)
    (trades,) = body["streams"]
    assert [i["tier"] for i in trades["intervals"]] == ["questdb", "questdb"]
    assert trades["intervals"][0] == {
        "from": "2026-09-01T00:00:00Z", "to": "2026-09-04T02:11:00Z", "tier": "questdb"
    }  # fmt: skip
    assert trades["gaps"] == [
        {"from": "2026-09-04T02:11:00Z", "to": "2026-09-04T02:14:20Z", "reason": "backend_restart"}
    ]
    assert body["generated_at"] == "2026-09-14T10:31:00Z"
    assert to_us(datetime.fromisoformat(trades["intervals"][-1]["to"])) == NOW


async def test_default_streams_when_none_requested() -> None:
    svc = CoverageService(MemRecorderStore(), now_us=UsClock(NOW))
    body = _client(svc).get("/market/data-coverage", params={"symbol": "BTCUSDT"}).json()
    assert [s["stream"] for s in body["streams"]] == [
        "trades", "orderbook_delta", "orderbook_snapshot", "tickers", "liquidations"
    ]  # fmt: skip
    assert all(s["intervals"] == [] and s["gaps"] == [] for s in body["streams"])


def _problem(resp: Any, status: int, code: str) -> None:
    assert resp.status_code == status, resp.text
    Problem.model_validate(resp.json())
    assert resp.json()["code"] == code


def test_rbac_and_validation_fail_closed() -> None:
    svc = CoverageService(MemRecorderStore(), now_us=UsClock(NOW))
    q = {"symbol": "BTCUSDT"}
    _problem(
        _client(svc, wired=False).get("/market/data-coverage", params=q), 501, "internal_error"
    )
    _problem(_client(svc, None).get("/market/data-coverage", params=q), 401, "unauthenticated")
    _problem(_client(svc, frozenset({"orders:read"})).get("/market/data-coverage", params=q),
             403, "forbidden")  # fmt: skip
    _problem(_client(svc).get("/market/data-coverage", params={"symbol": "../x"}),
             400, "validation_failed")  # fmt: skip
    _problem(_client(svc).get("/market/data-coverage", params={**q, "stream": "bogus"}),
             400, "validation_failed")  # fmt: skip
    _problem(_client(None).get("/market/data-coverage", params=q), 503, "store_unavailable")
    boom = _Boom(MemRecorderStore(), now_us=UsClock(NOW))
    _problem(_client(boom).get("/market/data-coverage", params=q), 503, "store_unavailable")


def test_to_dt_round_trips() -> None:
    assert to_us(to_dt(NOW)) == NOW


async def test_create_app_wires_sessions_provider_and_mounts_route() -> None:
    """E16-T04 wiring through the real factory: `recording_started_at` resolves from the
    sessions-backed `CoverageService` once attached (real backend), and the route is mounted
    (fake backend: no session resolver -> 501, fail closed)."""
    from candleviewer.app import create_app, recording_started_at_us
    from candleviewer.settings import Settings

    app = create_app(Settings(git_sha="test", version="0.0.0-test"))
    ctx = app.state.app_context
    assert app.state.coverage_service is None and ctx.recorder.coverage is None
    store = MemRecorderStore()
    sid = await store.open_session_at(
        recorded_symbol_id="r", symbol="SOLUSDT", streams=["trades"], orderbook_depth=1,
        ws_endpoint="x", started_at=datetime(2026, 9, 13, tzinfo=UTC),
    )  # fmt: skip
    first = datetime(2026, 9, 13, 0, 0, 1, tzinfo=UTC)
    await store.touch_session_events(sid, first=first, last=first)
    ctx.recorder.attach_coverage(CoverageService(store, now_us=UsClock(NOW)))
    assert await recording_started_at_us(ctx)("SOLUSDT") == to_us(first)
    resp = TestClient(app, client=("127.0.0.1", 50000)).get(
        "/market/data-coverage", params={"symbol": "SOLUSDT"}
    )
    assert resp.status_code == 501
