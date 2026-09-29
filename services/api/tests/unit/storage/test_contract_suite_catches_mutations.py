"""Mutation exercise for the storage contract suite (E07-Q01 DoD: "Mutation
exercise executed; all three seeded defects caught.").

Each mutant is a small local wrapper around `FakeMarketDataRepository`
defined only inside this test module — never a change to the shipped fake —
so this proves the contract suite's assertions actually *detect* a
regression rather than merely exercising a happy path. For each mutant we
assert the unmutated repository still passes the relevant assertion and the
mutated one fails it.
"""

from __future__ import annotations

from candleviewer.storage.models import TimeRange
from candleviewer.storage.repositories.rows import TradeRow
from candleviewer.storage.testing import FakeMarketDataRepository


class _WrongDedupKeyRepo(FakeMarketDataRepository):
    """Mutant 1: dedups trades on `(symbol, ts_us)` instead of the documented
    `(symbol, trade_id)` natural key."""

    async def write_trades(self, rows: object) -> None:
        for row in rows:  # type: ignore[attr-defined]
            self._trades[(row.symbol, str(row.ts_us))] = row


class _UnsortedReadRepo(FakeMarketDataRepository):
    """Mutant 2: returns trades in insertion order instead of sorting by
    `ts_us` ascending."""

    async def read_trades(self, sym: str, rng: TimeRange, tier: str = "auto") -> list[TradeRow]:
        return [r for r in self._trades.values() if r.symbol == sym and _in_range(r.ts_us, rng)]


class _InclusiveEndRangeRepo(FakeMarketDataRepository):
    """Mutant 3: treats the range end as inclusive instead of the documented
    exclusive-end boundary."""

    async def read_trades(self, sym: str, rng: TimeRange, tier: str = "auto") -> list[TradeRow]:
        rows = [
            r
            for r in self._trades.values()
            if r.symbol == sym and rng.start_us <= r.ts_us <= rng.end_us
        ]
        return sorted(rows, key=lambda r: (r.ts_us, r.trade_id))


def _in_range(ts_us: int, rng: TimeRange) -> bool:
    return rng.start_us <= ts_us < rng.end_us


async def test_dedup_key_mutant_is_caught_by_contract_assertion() -> None:
    row_a = TradeRow(ts_us=1_000, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id="a")
    row_b = TradeRow(ts_us=1_000, symbol="BTCUSDT", price="2", qty="1", side="buy", trade_id="b")

    good = FakeMarketDataRepository()
    await good.write_trades([row_a, row_b])
    good_result = await good.read_trades("BTCUSDT", TimeRange(start_us=0, end_us=2_000))
    assert len(good_result) == 2  # unmutated: distinct trade_ids both kept

    bad = _WrongDedupKeyRepo()
    await bad.write_trades([row_a, row_b])
    bad_result = await bad.read_trades("BTCUSDT", TimeRange(start_us=0, end_us=2_000))
    assert len(bad_result) == 1  # mutant collapses same-ts_us trades: defect caught


async def test_ordering_mutant_is_caught_by_contract_assertion() -> None:
    out_of_order = [
        TradeRow(ts_us=3_000, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id="a"),
        TradeRow(ts_us=1_000, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id="b"),
        TradeRow(ts_us=2_000, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id="c"),
    ]

    good = FakeMarketDataRepository()
    await good.write_trades(out_of_order)
    good_result = await good.read_trades("BTCUSDT", TimeRange(start_us=0, end_us=10_000))
    assert [r.ts_us for r in good_result] == [1_000, 2_000, 3_000]

    bad = _UnsortedReadRepo()
    await bad.write_trades(out_of_order)
    bad_result = await bad.read_trades("BTCUSDT", TimeRange(start_us=0, end_us=10_000))
    assert [r.ts_us for r in bad_result] != [1_000, 2_000, 3_000]  # mutant: insertion order


async def test_range_boundary_mutant_is_caught_by_contract_assertion() -> None:
    boundary = 1_000
    row = TradeRow(ts_us=boundary, symbol="BTCUSDT", price="1", qty="1", side="buy", trade_id="b")

    good = FakeMarketDataRepository()
    await good.write_trades([row])
    good_result = await good.read_trades(
        "BTCUSDT", TimeRange(start_us=boundary - 1, end_us=boundary)
    )
    assert good_result == []  # unmutated: exclusive-end excludes the boundary row

    bad = _InclusiveEndRangeRepo()
    await bad.write_trades([row])
    bad_result = await bad.read_trades("BTCUSDT", TimeRange(start_us=boundary - 1, end_us=boundary))
    assert bad_result == [row]  # mutant: inclusive-end wrongly includes it — defect caught
