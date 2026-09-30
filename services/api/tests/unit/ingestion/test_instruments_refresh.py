"""Unit tests for `InstrumentsRefreshScheduler` (E08-S01-2 Gherkin AC):
startup load, refresh without restart, tick-size change -> version row +
bus publish, refresh failure -> stale_since + error metric + previous
snapshot kept, on-demand throttle. No network, no DB, fake clock/sleep."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from candleviewer.domain.events import InstrumentUpdatedEvent
from candleviewer.ingestion.instruments_refresh import (
    InstrumentRefreshError,
    InstrumentsRefreshScheduler,
)
from candleviewer.ingestion.metrics import instruments_refresh_total

_BASE: dict[str, Any] = {
    "symbol": "BTCUSDT",
    "baseCoin": "BTC",
    "quoteCoin": "USDT",
    "settleCoin": "USDT",
    "status": "Trading",
    "launchTime": "1585699200000",
    "priceScale": "2",
    "priceFilter": {"tickSize": "0.10", "minPrice": "0.10", "maxPrice": "999999.00"},
    "lotSizeFilter": {
        "qtyStep": "0.001",
        "minOrderQty": "0.001",
        "maxOrderQty": "100.000",
        "maxMktOrderQty": "50.000",
        "minNotionalValue": "5",
    },
    "leverageFilter": {"minLeverage": "1", "maxLeverage": "100.00", "leverageStep": "0.01"},
    "fundingInterval": 480,
    "upperFundingRate": "0.00375",
    "lowerFundingRate": "-0.00375",
    "copyTrading": "both",
}


def raw(symbol: str = "BTCUSDT", **overrides: Any) -> dict[str, Any]:
    r = copy.deepcopy(_BASE)
    r["symbol"] = symbol
    r["baseCoin"] = symbol.removesuffix("USDT")
    r.update(overrides)
    return r


class FakeRepo:
    def __init__(self, persisted: Sequence[Mapping[str, Any]] = ()) -> None:
        self.persisted = list(persisted)
        self.snapshots: list[list[Mapping[str, Any]]] = []
        self.versions: list[tuple[Mapping[str, Any], tuple[str, ...]]] = []
        self.stale: list[int] = []

    async def upsert_snapshot(self, rows: Sequence[Mapping[str, Any]]) -> None:
        self.snapshots.append(list(rows))
        self.persisted = list(rows)

    async def record_version(
        self, row: Mapping[str, Any], *, changed_fields: Sequence[str]
    ) -> None:
        self.versions.append((row, tuple(changed_fields)))

    async def mark_stale(self, *, stale_since_us: int) -> None:
        self.stale.append(stale_since_us)

    async def load_all(self) -> Sequence[Mapping[str, Any]]:
        return self.persisted


class Clock:
    def __init__(self) -> None:
        self.us = 1_700_000_000_000_000

    def __call__(self) -> int:
        return self.us


async def _no_sleep(delay: float) -> None:
    """Retry backoffs return immediately; the 12 h TTL wait blocks until the
    task is cancelled by `stop()` (never a real sleep — C-13.7)."""
    if delay > 1_000:
        await asyncio.Event().wait()


def make(
    pages: list[Any], repo: FakeRepo | None = None, clock: Clock | None = None
) -> tuple[InstrumentsRefreshScheduler, FakeRepo, list[InstrumentUpdatedEvent], Clock]:
    """`pages`: each fetch pops the next entry; an Exception entry is raised."""
    repo = repo or FakeRepo()
    clock = clock or Clock()
    published: list[InstrumentUpdatedEvent] = []

    async def fetch() -> Sequence[Mapping[str, Any]]:
        item = pages.pop(0) if len(pages) > 1 else pages[0]
        if isinstance(item, Exception):
            raise item
        return list(item)

    async def publish(event: Any) -> None:
        published.append(event)

    sched = InstrumentsRefreshScheduler(
        fetch_instruments_info=fetch,
        repository=repo,
        publish=publish,
        now_us=clock,
        sleep=_no_sleep,
        random_fn=lambda: 0.0,
    )
    return sched, repo, published, clock


def _count(result: str) -> float:
    value: float = instruments_refresh_total.labels(result=result)._value.get()
    return value


async def test_refresh_now_populates_snapshot_and_persists() -> None:
    sched, repo, published, _ = make([[raw("BTCUSDT"), raw("ETHUSDT")]])
    await sched.refresh_now()
    snap = sched.snapshot()
    assert snap is not None and set(snap.by_symbol) == {"BTCUSDT", "ETHUSDT"}
    assert len(repo.snapshots) == 1 and len(repo.snapshots[0]) == 2
    assert published == []  # new symbols are not "updates"


async def test_new_listing_appears_on_refresh_without_restart() -> None:
    sched, _, _, _ = make([[raw("BTCUSDT")], [raw("BTCUSDT"), raw("SOLUSDT")]])
    await sched.refresh_now()
    assert sched.snapshot().get("SOLUSDT") is None  # type: ignore[union-attr]  # set above
    await sched.refresh_now()
    assert sched.snapshot().get("SOLUSDT") is not None  # type: ignore[union-attr]  # set above


async def test_tick_size_change_records_version_and_publishes_event() -> None:
    changed = raw(priceFilter={"tickSize": "0.50", "minPrice": "0.10", "maxPrice": "999999.00"})
    sched, repo, published, _ = make([[raw()], [changed]])
    await sched.refresh_now()
    await sched.refresh_now()
    inst = sched.snapshot().get("BTCUSDT")  # type: ignore[union-attr]  # set above
    assert inst is not None and inst.metadata_version == 2
    assert len(repo.versions) == 1 and "tick_size" in repo.versions[0][1]
    assert len(published) == 1
    assert published[0].symbol == "BTCUSDT" and published[0].metadata_version == 2


async def test_unchanged_refresh_is_noop_for_versions() -> None:
    sched, repo, published, _ = make([[raw()], [raw()]])
    await sched.refresh_now()
    await sched.refresh_now()
    assert repo.versions == [] and published == []


async def test_refresh_failure_keeps_previous_snapshot_and_marks_stale() -> None:
    sched, repo, _, clock = make([[raw()], RuntimeError("boom")])
    await sched.refresh_now()
    before = _count("error")
    clock.us += 5_000_000
    with pytest.raises(InstrumentRefreshError):
        await sched.refresh_now()
    snap = sched.snapshot()
    assert snap is not None and snap.get("BTCUSDT") is not None  # never empty
    assert snap.stale_since_us == clock.us
    assert repo.stale == [clock.us]
    assert _count("error") == before + 1
    first = clock.us
    clock.us += 5_000_000
    with pytest.raises(InstrumentRefreshError):
        await sched.refresh_now()
    assert sched.snapshot().stale_since_us == first  # type: ignore[union-attr]  # set above


async def test_successful_refresh_clears_stale() -> None:
    sched, _, _, _ = make(
        [[raw()], RuntimeError("x"), RuntimeError("x"), RuntimeError("x"), [raw()]]
    )
    await sched.refresh_now()
    with pytest.raises(InstrumentRefreshError):
        await sched.refresh_now()
    await sched.refresh_now()
    assert sched.snapshot().stale_since_us is None  # type: ignore[union-attr]  # set above


async def test_start_loads_persisted_when_fetch_fails() -> None:
    seed, _, _, _ = make([[raw()]])
    await seed.refresh_now()
    persisted = seed.snapshot().get("BTCUSDT").model_dump(mode="json")  # type: ignore[union-attr]  # set above
    sched, _, _, _ = make([RuntimeError("down")], repo=FakeRepo([persisted]))
    await sched.start()
    try:
        snap = sched.snapshot()
        assert snap is not None and snap.get("BTCUSDT") is not None
    finally:
        await sched.stop(grace_s=1.0)


async def test_ensure_symbol_triggers_one_refresh_then_throttles() -> None:
    sched, _, _, clock = make([[raw()], [raw(), raw("NEWUSDT")]])
    await sched.refresh_now()
    found = await sched.ensure_symbol("NEWUSDT")
    assert found is not None and found.symbol == "NEWUSDT"
    before = _count("throttled")
    assert await sched.ensure_symbol("NOPEUSDT") is None
    assert _count("throttled") == before + 1
    clock.us += 61_000_000
    assert await sched.ensure_symbol("BTCUSDT") is not None  # cached path, no fetch


async def test_zero_parseable_rows_is_an_error_not_an_empty_catalogue() -> None:
    sched, _, _, _ = make([[raw()], [{"symbol": "BAD"}]])
    await sched.refresh_now()
    with pytest.raises(InstrumentRefreshError):
        await sched.refresh_now()
    assert sched.snapshot().get("BTCUSDT") is not None  # type: ignore[union-attr]  # set above
