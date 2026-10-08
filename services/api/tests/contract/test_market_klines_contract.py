"""E12-T05 (#398) PR-A: `/market/klines` responses and every documented error validate against the
committed OpenAPI (`KlineResponse` / `Problem`, generated from `22-api-openapi.yaml`).

Bars come from the recorded corpus (`packages/fixtures/bybit/2026-10-05`, BTCUSDT 1m, 450 bars
spanning 2023-11-14 22:13 .. 2023-11-15 05:42 UTC). No network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api._generated.openapi_models import KlineResponse, Problem
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.market import MarketDataPrincipal, make_market_router
from candleviewer.ingestion.kline_read import KlineReadService
from tests._corpus import rest

_SPEC = load_openapi_spec()
_CODES = {e["code"]: e["status"] for e in _SPEC["x-error-codes"]}
_DECLARED = set(_SPEC["paths"]["/market/klines"]["get"]["responses"])


@dataclass(frozen=True, slots=True)
class _Kline:
    ts_us: int
    open: str
    high: str
    low: str
    close: str
    volume: str
    turnover: str
    confirmed: bool = True
    source: str = "ws"  # hot-tier kline (not an exchange_rest backfill row)


@dataclass(frozen=True, slots=True)
class _Tape:
    ts_us: int
    open: str = "1"
    high: str = "2"
    low: str = "0.5"
    close: str = "1.5"
    volume: str = "3.0"
    turnover: str = "4.5"
    confirmed: bool = True
    trades: int = 7
    delta: str | None = "1.25"
    min_delta: str | None = "-0.5"
    max_delta: str | None = "2.0"
    source: str = "tape"


def _corpus() -> list[_Kline]:
    pages = (rest(f"rest/kline_BTCUSDT_1_page{i}.json")["result"]["list"] for i in range(3))
    wire = [r for page in pages for r in page]
    return sorted(
        (_Kline(int(r[0]) * 1000, r[1], r[2], r[3], r[4], r[5], r[6]) for r in wire),
        key=lambda k: k.ts_us,
    )


class _Hot:
    def __init__(self, rows: list[_Kline]) -> None:
        self.rows = rows

    async def read_klines(
        self, sym: str, interval: str, rng: Any, tier: str = "auto", limit: int | None = None
    ) -> list[_Kline]:
        got = [r for r in self.rows if rng.start_us <= r.ts_us < rng.end_us]
        return got[-limit:] if limit else got


class _Resolver:
    def __init__(self, perms: frozenset[str] | None) -> None:
        self._perms = perms

    def resolve(self, request: Request) -> MarketDataPrincipal | None:
        return None if self._perms is None else MarketDataPrincipal("u1", self._perms)


_READ = frozenset({"marketdata:read"})
_START_US = 1_699_999_980_000_000  # 2023-11-14T22:13:00Z, first corpus bar


def _client(
    *, perms: frozenset[str] | None = _READ, tape: list[_Tape] | None = None,
    recording_us: int | None = None,
) -> TestClient:  # fmt: skip
    async def tape_reader(symbol: str, interval: str, rng: Any, limit: int | None) -> list[_Tape]:
        return [t for t in (tape or []) if rng.start_us <= t.ts_us < rng.end_us]

    async def started(symbol: str) -> int | None:
        return recording_us

    service = KlineReadService(
        _Hot(_corpus()), tape=tape_reader if tape is not None else None,
        recording_started_at_us=started,
    )  # fmt: skip
    app = FastAPI()
    app.include_router(
        make_market_router(
            lambda: _Hot([]), principal_resolver=_Resolver(perms),
            read_service_provider=lambda: service, symbol_listed=lambda s: s == "BTCUSDT",
            now_us=lambda: 1_700_100_000_000_000,
        )
    )  # fmt: skip
    return TestClient(app, client=("127.0.0.1", 50000))


_P: dict[str, Any] = {
    "symbol": "BTCUSDT", "interval": "1",
    "from": "2023-11-14T22:00:00Z", "to": "2023-11-15T06:00:00Z", "limit": 1000,
}  # fmt: skip


def _problem(resp: Any, status: int, code: str) -> None:
    assert resp.status_code == status, resp.text
    assert str(status) in _DECLARED, f"{status} not declared on /market/klines"
    # `validation_failed` is also served at 422 app-wide (api/error_redaction.py, FastAPI request
    # validation) for semantically invalid input; every other code must match its catalogue status.
    allowed = {_CODES[code]} | ({422} if code == "validation_failed" else set())
    assert status in allowed, f"{code} is catalogued as {_CODES.get(code)}"
    body = resp.json()
    Problem.model_validate(body)
    assert body["code"] == code
    assert resp.headers["content-type"].startswith("application/problem+json")


class TestKlinesResponses:
    def test_corpus_window_validates_against_kline_response(self) -> None:
        body = _client().get("/market/klines", params=_P).json()
        KlineResponse.model_validate(body)
        ts = [b["t"] for b in body["bars"]]
        assert len(ts) == 450 and ts == sorted(ts)
        assert body["meta"]["sources"] == ["questdb"] and body["meta"]["has_more"] is False

    def test_kline_rows_have_null_not_zero_delta_with_include_delta(self) -> None:
        """Gherkin "Klines degrade honestly": pre-recording kline bars carry null order flow."""
        recording = _START_US + 1_000 * 60_000_000  # after the whole corpus window
        body = (
            _client(recording_us=recording)
            .get("/market/klines", params={**_P, "include_delta": "true"})
            .json()
        )
        KlineResponse.model_validate(body)
        for bar in body["bars"]:
            for name in ("delta", "min_delta", "max_delta", "cvd"):
                assert name in bar and bar[name] is None, (name, bar)
        assert body["meta"]["recording_started_at"].startswith("2023-11-15T")

    def test_without_include_delta_no_order_flow_fields(self) -> None:
        bar = _client().get("/market/klines", params=_P).json()["bars"][0]
        assert not {"delta", "cvd", "min_delta", "max_delta"} & set(bar)

    def test_tape_wins_over_klines_on_overlap(self) -> None:
        tape = [_Tape(ts_us=_START_US), _Tape(ts_us=_START_US + 60_000_000)]
        body = (
            _client(tape=tape).get("/market/klines", params={**_P, "include_delta": "true"}).json()
        )
        KlineResponse.model_validate(body)
        bars = body["bars"]
        assert len(bars) == 450  # replaced, not duplicated
        assert bars[0]["o"] == "1" and bars[0]["delta"] == "1.25" and bars[0]["trades"] == 7
        assert bars[2]["delta"] is None  # kline bar after the overlap stays null
        assert body["meta"]["sources"] == ["questdb", "tape"]

    def test_tape_reader_with_no_rows_never_claims_tape(self) -> None:
        body = _client(tape=[]).get("/market/klines", params=_P).json()
        assert "tape" not in body["meta"]["sources"]

    def test_include_open_governs_the_forming_bar(self) -> None:
        forming = _Tape(ts_us=_START_US, confirmed=False)
        params = {**_P, "from": "2023-11-14T22:13:00Z", "to": "2023-11-14T22:14:00Z"}
        closed_only = _client(tape=[forming]).get("/market/klines", params=params).json()
        assert closed_only["bars"] == []
        with_open = (
            _client(tape=[forming])
            .get("/market/klines", params={**params, "include_open": "true"})
            .json()
        )
        assert [b["confirm"] for b in with_open["bars"]] == [False]


class TestKlinesPagination:
    _WIDE: ClassVar[dict[str, Any]] = {**_P, "limit": 100}

    def test_uncursored_window_wider_than_limit_is_bar_window_too_large(self) -> None:
        _problem(_client().get("/market/klines", params=self._WIDE), 422, "bar_window_too_large")

    def test_cursor_round_trip_returns_every_bar_once_oldest_first(self) -> None:
        client = _client()
        from candleviewer.api.market_response import encode_cursor

        cursor: str | None = encode_cursor(0)  # first page: start at `from`
        seen: list[str] = []
        pages = 0
        while cursor is not None:
            body = client.get("/market/klines", params={**self._WIDE, "cursor": cursor}).json()
            KlineResponse.model_validate(body)
            assert body["meta"]["count"] <= 100
            seen.extend(b["t"] for b in body["bars"])
            cursor = body["meta"]["next_cursor"]
            assert body["meta"]["has_more"] is (cursor is not None)
            pages += 1
            assert pages < 20
        assert len(seen) == len(set(seen)) == 450 and seen == sorted(seen)

    @pytest.mark.parametrize("bad", ["x", "djE6YWJj", "Zm9v", "v1:12"])
    def test_malformed_cursor_is_invalid_cursor(self, bad: str) -> None:
        _problem(
            _client().get("/market/klines", params={**self._WIDE, "cursor": bad}),
            400, "invalid_cursor",
        )  # fmt: skip


class TestKlinesErrors:
    def test_no_session_is_401(self) -> None:
        _problem(_client(perms=None).get("/market/klines", params=_P), 401, "unauthenticated")

    def test_missing_permission_is_403_and_discloses_nothing(self) -> None:
        resp = _client(perms=frozenset({"orders:read"})).get("/market/klines", params=_P)
        _problem(resp, 403, "forbidden")
        assert "bars" not in resp.json()

    def test_bad_interval_is_400_validation_failed(self) -> None:
        resp = _client().get("/market/klines", params={**_P, "interval": "7"})
        _problem(resp, 400, "validation_failed")

    def test_unknown_price_type_is_400(self) -> None:
        resp = _client().get("/market/klines", params={**_P, "price_type": "last"})
        _problem(resp, 400, "validation_failed")

    @pytest.mark.parametrize("price_type", ["mark", "index", "premium_index"])
    def test_unrecorded_price_type_is_422_naming_the_alternative(self, price_type: str) -> None:
        resp = _client().get("/market/klines", params={**_P, "price_type": price_type})
        _problem(resp, 422, "validation_failed")
        assert "price_type=trade" in resp.json()["detail"]

    def test_unknown_symbol_is_422(self) -> None:
        resp = _client().get("/market/klines", params={**_P, "symbol": "NOPEUSDT"})
        _problem(resp, 422, "validation_failed")

    def test_storage_not_ready_is_503(self) -> None:
        app = FastAPI()
        app.include_router(make_market_router(lambda: None, principal_resolver=_Resolver(_READ)))
        resp = TestClient(app).get("/market/klines", params=_P)
        _problem(resp, 503, "store_unavailable")
