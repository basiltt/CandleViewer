"""E08-Q02 group 1 (instrument catalogue over the read surface): E08-TC-A02, E08-TC-A03,
E08-TC-A04, E08-TC-A08, E08-TC-A09.

Recorded `instruments-info` pages -> real `parse_instruments` -> real `InstrumentsRefreshScheduler`
-> real `/instruments` router (generated-model validated). Fake clock/sleep, in-memory repository,
no network. A01/A10 live in `test_contract_instruments.py` / `test_contract_errors.py`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.instruments import (
    InstrumentsPrincipal,
    make_instruments_router,
    serialize_instrument,
)
from candleviewer.domain.events import InstrumentUpdatedEvent
from candleviewer.exchange.base.instruments import InstrumentsFetchResult
from candleviewer.exchange.bybit.instruments import parse_instruments
from candleviewer.exchange.policy import InstrumentPolicy
from candleviewer.ingestion.instruments_refresh import InstrumentsRefreshScheduler
from candleviewer.ingestion.metrics import instruments_refresh_total
from tests._corpus import rest
from tests.contract.bybit._support import counter_value

BEFORE, AFTER = "rest/instruments_before.json", "rest/instruments_after.json"
T0 = 1_700_000_000_000_000
TTL_S = 43_200.0


def _rows(rel: str) -> list[dict[str, Any]]:
    return list(rest(rel)["result"]["list"])


class _Repo:
    def __init__(self) -> None:
        self.versions: list[tuple[Mapping[str, Any], tuple[str, ...]]] = []

    async def upsert_snapshot(self, rows: Sequence[Mapping[str, Any]]) -> None:
        return None

    async def record_version(
        self, row: Mapping[str, Any], *, changed_fields: Sequence[str]
    ) -> None:
        self.versions.append((row, tuple(changed_fields)))

    async def mark_stale(self, *, stale_since_us: int) -> None:
        return None

    async def load_all(self) -> Sequence[Mapping[str, Any]]:
        return []


class _Resolver:
    def resolve(self, request: Request) -> InstrumentsPrincipal:
        return InstrumentsPrincipal(user_id="u", permissions=frozenset({"instruments:read"}))


async def _no_wait(_delay: float) -> None:
    return None


def _scheduler(
    pages: list[list[dict[str, Any]]],
    *,
    sleep: Callable[[float], Any] = _no_wait,
) -> tuple[InstrumentsRefreshScheduler, _Repo, list[Any]]:
    repo, published, queue = _Repo(), [], list(pages)

    async def fetch(now_us: Callable[[], int]) -> InstrumentsFetchResult:
        page = queue.pop(0) if len(queue) > 1 else queue[0]
        return parse_instruments(page, fetched_at_us=now_us())

    async def publish(event: Any) -> None:
        published.append(event)

    sched = InstrumentsRefreshScheduler(
        fetch_instruments_info=fetch,
        repository=repo,
        publish=publish,
        now_us=lambda: T0,
        sleep=sleep,
        random_fn=lambda: 0.0,
        on_demand_cooldown_s=0.0,
    )
    return sched, repo, published


def _client(sched: InstrumentsRefreshScheduler) -> TestClient:
    app = FastAPI()
    app.include_router(make_instruments_router(lambda: sched, principal_resolver=_Resolver()))
    return TestClient(app, client=("127.0.0.1", 50000))


async def test_a02_instrument_detail_equals_the_recorded_row_with_internal_names_only() -> None:
    """E08-TC-A02."""
    sched, _, _ = _scheduler([_rows(BEFORE)])
    await sched.refresh_now()
    body = _client(sched).get("/instruments/BTCUSDT").json()
    snap = sched.snapshot()
    assert snap is not None
    inst = snap.get("BTCUSDT")
    assert inst is not None
    assert {k: body[k] for k in serialize_instrument(inst)} == serialize_instrument(inst)
    wire = next(r for r in _rows(BEFORE) if r["symbol"] == "BTCUSDT")
    assert Decimal(body["tick_size"]) == Decimal(wire["priceFilter"]["tickSize"])
    assert Decimal(body["qty_step"]) == Decimal(wire["lotSizeFilter"]["qtyStep"])
    assert not {"tickSize", "priceFilter", "lotSizeFilter", "retCode", "result"} & set(body)


async def test_a03_unknown_symbol_is_a_404_problem_without_upstream_text() -> None:
    """E08-TC-A03."""
    sched, _, _ = _scheduler([_rows(BEFORE)])
    await sched.refresh_now()
    r = _client(sched).get("/instruments/NOPEUSDT")
    assert r.status_code == 404 and "NOPEUSDT" in r.text
    assert "bybit" not in r.text.lower() and "retCode" not in r.text


async def test_a04_new_listing_appears_without_restart_and_counts_one_refresh() -> None:
    """E08-TC-A04: SOLUSDT is absent from the first catalogue, present in the next refresh."""
    first = [r for r in _rows(BEFORE) if r["symbol"] != "SOLUSDT"]
    sched, _, _ = _scheduler([first, _rows(BEFORE)])
    await sched.refresh_now()
    client = _client(sched)
    before = counter_value(instruments_refresh_total, result="ok")
    assert client.get("/instruments/SOLUSDT").status_code == 200  # on-demand refresh
    assert counter_value(instruments_refresh_total, result="ok") == before + 1


async def test_a08_tick_size_change_bumps_the_version_publishes_and_moves_the_grid() -> None:
    """E08-TC-A08 (server half; client re-validation is E08-Q05): SOLUSDT 0.010 -> 0.005."""
    sched, repo, published = _scheduler([_rows(BEFORE), _rows(AFTER)])
    await sched.refresh_now()
    snap = sched.snapshot()
    assert snap is not None
    v1 = snap.get("SOLUSDT")
    assert v1 is not None
    await sched.refresh_now()
    snap = sched.snapshot()
    assert snap is not None
    v2 = snap.get("SOLUSDT")
    assert v2 is not None
    assert v2.metadata_version > v1.metadata_version and v2.tick_size == Decimal("0.005")
    assert [fields for _row, fields in repo.versions if "tick_size" in fields]  # version row
    (event,) = [
        e for e in published if isinstance(e, InstrumentUpdatedEvent) and e.symbol == "SOLUSDT"
    ]
    assert "tick_size" in event.changed_fields
    assert InstrumentPolicy(v2).round_price(Decimal("150.003")) == Decimal("150.005")
    assert InstrumentPolicy(v1).round_price(Decimal("150.003")) == Decimal("150.000")


async def test_a09_scheduled_refresh_fires_after_the_ttl_on_a_frozen_clock() -> None:
    """E08-TC-A09 (frozen-clock automation of the manual case): the periodic task sleeps one TTL
    (12 h + <=5 % jitter) and then refreshes exactly once more (`instruments_refresh_total` +1)."""
    delays: list[float] = []
    second_sleep = asyncio.Event()

    async def sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) > 1:  # the periodic loop's second wait: park until cancelled
            second_sleep.set()
            await asyncio.Event().wait()

    sched, _, _ = _scheduler([_rows(BEFORE)], sleep=sleep)
    await sched.start()
    try:
        after_start = counter_value(instruments_refresh_total, result="ok")
        await asyncio.wait_for(second_sleep.wait(), timeout=5)
        assert delays[0] >= TTL_S and delays[0] <= TTL_S * 1.05
        assert counter_value(instruments_refresh_total, result="ok") == after_start + 1
    finally:
        await sched.stop()
