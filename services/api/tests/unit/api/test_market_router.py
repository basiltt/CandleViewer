"""Unit tests for `candleviewer.api.market.make_market_router` (QA defect
#1622 blocker: "GET /market/klines REST endpoint (core ticket deliverable)
not implemented" — `grep -rln "market/klines" services/api/candleviewer/
**/*.py` outside `ingestion/` returned nothing before this fix, and no
`APIRouter` served the route)."""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.market import make_market_router
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.models import TimeRange


@dataclass(slots=True)
class _FakeRow:
    ts_us: int
    open: str = "100"
    high: str = "101"
    low: str = "99"
    close: str = "100.5"
    volume: str = "10"
    turnover: str = "1000"
    confirmed: bool = True


@dataclass(slots=True)
class _FakeCache:
    rows: list[_FakeRow] = field(default_factory=list)
    calls: list[tuple[str, str, TimeRange]] = field(default_factory=list)

    async def read_klines(
        self, sym: str, interval: str, rng: TimeRange, tier: str = "auto"
    ) -> list[_FakeRow]:
        self.calls.append((sym, interval, rng))
        return [r for r in self.rows if rng.start_us <= r.ts_us < rng.end_us]


def _app(cache: _FakeCache | None) -> FastAPI:
    app = FastAPI()
    app.include_router(make_market_router(lambda: cache))
    return app


def _client(cache: _FakeCache | None) -> TestClient:
    return TestClient(_app(cache), client=("127.0.0.1", 50000))


class TestGetKlinesHappyPath:
    def test_returns_ascending_confirmed_bars_from_the_cache(self) -> None:
        cache = _FakeCache(rows=[_FakeRow(ts_us=0), _FakeRow(ts_us=60_000_000)])
        client = _client(cache)

        resp = client.get(
            "/market/klines",
            params={
                "symbol": "BTCUSDT",
                "interval": "1",
                "from": "1970-01-01T00:00:00Z",
                "to": "1970-01-01T00:01:00Z",
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["symbol"] == "BTCUSDT"
        assert body["interval"] == "1"
        assert len(body["bars"]) == 1
        assert body["bars"][0]["confirm"] is True
        assert body["meta"]["count"] == 1

    def test_unconfirmed_bar_excluded_unless_include_open(self) -> None:
        cache = _FakeCache(rows=[_FakeRow(ts_us=0, confirmed=False)])
        client = _client(cache)
        params = {
            "symbol": "BTCUSDT",
            "interval": "1",
            "from": "1970-01-01T00:00:00Z",
            "to": "1970-01-01T00:01:00Z",
        }

        resp_default = client.get("/market/klines", params=params)
        resp_open = client.get("/market/klines", params={**params, "include_open": "true"})

        assert resp_default.json()["bars"] == []
        assert len(resp_open.json()["bars"]) == 1
        assert resp_open.json()["bars"][0]["confirm"] is False


class TestGetKlinesValidation:
    def test_missing_from_is_400(self) -> None:
        client = _client(_FakeCache())
        resp = client.get("/market/klines", params={"symbol": "BTCUSDT", "interval": "1"})
        assert resp.status_code == 400
        assert resp.json()["title"] == "Bad request"

    def test_unsupported_interval_is_400(self) -> None:
        client = _client(_FakeCache())
        resp = client.get(
            "/market/klines",
            params={
                "symbol": "BTCUSDT",
                "interval": "not-an-interval",
                "from": "1970-01-01T00:00:00Z",
            },
        )
        assert resp.status_code == 400

    def test_from_after_to_is_400(self) -> None:
        client = _client(_FakeCache())
        resp = client.get(
            "/market/klines",
            params={
                "symbol": "BTCUSDT",
                "interval": "1",
                "from": "1970-01-02T00:00:00Z",
                "to": "1970-01-01T00:00:00Z",
            },
        )
        assert resp.status_code == 400


class TestGetKlinesUnavailable:
    def test_no_cache_wired_is_503(self) -> None:
        client = _client(None)
        resp = client.get(
            "/market/klines",
            params={"symbol": "BTCUSDT", "interval": "1", "from": "1970-01-01T00:00:00Z"},
        )
        assert resp.status_code == 503

    def test_storage_not_started_yet_is_503_not_a_500(self) -> None:
        def _raise() -> None:
            raise StorageTierUnavailable("storage.start() has not been called")

        app = FastAPI()
        app.include_router(make_market_router(_raise))  # type: ignore[arg-type]
        client = TestClient(app, client=("127.0.0.1", 50000))

        resp = client.get(
            "/market/klines",
            params={"symbol": "BTCUSDT", "interval": "1", "from": "1970-01-01T00:00:00Z"},
        )
        assert resp.status_code == 503
