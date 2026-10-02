"""Tier router tests (E07-T05): boundary maths, straddle merge, overlap fixture."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.natural_keys import NATURAL_KEY, NATURAL_KEY_BY_TABLE
from candleviewer.storage.questdb.ddl import parse_ddl_dir
from candleviewer.storage.router import TierRouter, dedup_merge

DAY = 86_400_000_000
NOW = 100 * DAY
HOT_DAYS = 30
BOUNDARY = NOW - HOT_DAYS * DAY
FIXTURE = (
    Path(__file__).resolve().parents[5]
    / "packages/fixtures/golden/storage/router_overlap.golden.json"
)


def _router(hot_rows: list[Any], cold_rows: list[Any], calls: list[str]) -> TierRouter:
    async def hot(sym: str, rng: TimeRange) -> list[Any]:
        calls.append("hot")
        return list(hot_rows)

    async def cold(sym: str, rng: TimeRange) -> list[Any]:
        calls.append("cold")
        return list(cold_rows)

    return TierRouter(
        {StreamKind.TRADES: hot},
        {StreamKind.TRADES: cold},
        lambda s: HOT_DAYS,
        clock_us=lambda: NOW,
    )


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (BOUNDARY, BOUNDARY + 10, "hot"),  # start == boundary: inclusive hot
        (BOUNDARY - 1, BOUNDARY + 10, "both"),  # boundary-1us straddles
        (BOUNDARY - 10, BOUNDARY, "cold"),  # end exclusive == boundary: cold
        (BOUNDARY - 10, BOUNDARY + 1, "both"),
        (0, 5, "cold"),
        (NOW - 5, NOW, "hot"),
    ],
)
def test_resolve_boundary_cases(start: int, end: int, expected: str) -> None:
    r = _router([], [], [])
    assert r.resolve(StreamKind.TRADES, TimeRange(start_us=start, end_us=end)) == expected


def test_explicit_hint_overrides_auto() -> None:
    r = _router([], [], [])
    rng = TimeRange(start_us=0, end_us=5)
    assert r.resolve(StreamKind.TRADES, rng, "hot") == "hot"
    assert r.resolve(StreamKind.TRADES, TimeRange(start_us=NOW - 1, end_us=NOW), "cold") == "cold"


async def test_hot_only_queries_questdb_only() -> None:
    calls: list[str] = []
    out = await _router([{"ts": 1}], [], calls).read(
        StreamKind.TRADES, "X", TimeRange(start_us=NOW - 5, end_us=NOW)
    )
    assert calls == ["hot"] and out.tier == "hot"


async def test_cold_only_queries_duckdb_only() -> None:
    calls: list[str] = []
    out = await _router([], [{"ts": 1}], calls).read(
        StreamKind.TRADES, "X", TimeRange(start_us=0, end_us=5)
    )
    assert calls == ["cold"] and out.tier == "cold"


async def test_straddle_merges_overlap_fixture_without_dupes_or_gaps() -> None:
    fx = json.loads(FIXTURE.read_text("utf-8"))
    calls: list[str] = []
    out = await _router(fx["hot"], fx["cold"], calls).read(
        StreamKind.TRADES, "BTCUSDT", TimeRange(start_us=BOUNDARY - 5, end_us=NOW)
    )
    assert out.tier == "both" and sorted(calls) == ["cold", "hot"]
    assert [r["trade_id"] for r in out.rows] == fx["expected_ids"]
    assert [r["ts"] for r in out.rows] == sorted(r["ts"] for r in out.rows)
    t4 = next(r for r in out.rows if r["trade_id"] == "t4")
    assert t4["size"] == fx["expected_t4_size"]  # hot wins ties


def test_dedup_merge_supports_attribute_rows() -> None:
    class Row:
        def __init__(self, ts: int, v: int) -> None:
            self.ts, self.v = ts, v

    rows = dedup_merge([Row(1, 1)], [Row(1, 2)], ("ts",))
    assert len(rows) == 1 and rows[0].v == 2


def test_natural_key_equals_questdb_dedup_clause() -> None:
    ddl_dir = Path(__file__).resolve().parents[5] / "backend/db/questdb"
    tables = {t.name: t.dedup_keys for t in parse_ddl_dir(ddl_dir)}
    for table, key in NATURAL_KEY_BY_TABLE.items():
        assert tables[table] == key, table
    assert set(NATURAL_KEY) <= set(StreamKind)


def test_accelerated_window_halves_hot_boundary() -> None:
    # BUG #1696-A: reaper accelerated (30d -> 15d) dropped 20d-old hot data.
    state = {"acc": False}
    r = TierRouter(
        {}, {}, lambda s: HOT_DAYS, clock_us=lambda: NOW, accelerated=lambda: state["acc"]
    )
    rng = TimeRange(start_us=NOW - 21 * DAY, end_us=NOW - 20 * DAY)
    assert r.resolve(StreamKind.TRADES, rng) == "hot"
    state["acc"] = True
    assert r.resolve(StreamKind.TRADES, rng) == "cold"


def test_boundary_is_monotonic_under_clock_step_back() -> None:
    clock = {"t": NOW}
    r = TierRouter({}, {}, lambda s: HOT_DAYS, clock_us=lambda: clock["t"])
    rng = TimeRange(start_us=NOW - 31 * DAY, end_us=NOW - 29 * DAY)
    assert r.resolve(StreamKind.TRADES, rng) == "both"
    clock["t"] = NOW - 3 * DAY
    assert r.resolve(StreamKind.TRADES, rng) == "both"
    rng2 = TimeRange(start_us=NOW - 40 * DAY, end_us=NOW - 31 * DAY)
    assert r.resolve(StreamKind.TRADES, rng2) == "cold"
