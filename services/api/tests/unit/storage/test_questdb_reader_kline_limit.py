"""#2045 security review (medium): `limit` is pushed into the kline hot-tier query and keeps
the newest rows; the fake repository mirrors it."""

from __future__ import annotations

from candleviewer.storage.models import TimeRange
from candleviewer.storage.questdb.reader import build_read_klines
from candleviewer.storage.repositories.rows import KlineRow
from candleviewer.storage.testing import FakeMarketDataRepository


def test_build_read_klines_without_limit_is_unchanged() -> None:
    q = build_read_klines("BTCUSDT", "1", TimeRange(start_us=0, end_us=10))
    assert q.sql.endswith("ORDER BY ts") and "LIMIT" not in q.sql
    assert q.params == ("BTCUSDT", "1", 0, 10)


def test_build_read_klines_limit_is_bound_and_keeps_newest() -> None:
    q = build_read_klines("BTCUSDT", "1", TimeRange(start_us=0, end_us=10), 5)
    assert q.sql.endswith("ORDER BY ts DESC LIMIT $5")
    assert q.params == ("BTCUSDT", "1", 0, 10, 5)


async def test_fake_repository_limit_keeps_newest_ascending() -> None:
    repo = FakeMarketDataRepository()
    await repo.write_klines([
        KlineRow(ts_us=t, symbol="BTCUSDT", interval="1", open="1", high="1", low="1",
                 close="1", volume="1", turnover="1", confirmed=True)
        for t in range(5)
    ])  # fmt: skip
    rng = TimeRange(start_us=0, end_us=10)
    assert [r.ts_us for r in await repo.read_klines("BTCUSDT", "1", rng, limit=2)] == [3, 4]
    assert await repo.read_klines("BTCUSDT", "1", rng, limit=0) == []
    assert len(await repo.read_klines("BTCUSDT", "1", rng)) == 5
