"""Shared `ColdTierRepository` contract suite (E07-Q01 CT-01..CT-04).

Parametrised the same way as `test_market_data_contract.py` — `fake` today,
a real Parquet/DuckDB engine added by E07-T04 (issue #170) once it lands.
Covers the export -> verify -> query lifecycle, the "verify raises rather
than returns False" safety invariant, manifest ordering, and retention pin
enforcement.
"""

from __future__ import annotations

import pytest

from candleviewer.storage.errors import StorageExportVerifyFailed, StorageRetentionBlockedByPin
from candleviewer.storage.models import RetentionDecision, StreamKind, TimeRange
from candleviewer.storage.repositories.cold import ColdTierRepository
from candleviewer.storage.testing import FakeColdTierRepository, FakeRetentionRepository


@pytest.fixture(params=["fake"])
def cold_repo(request: pytest.FixtureRequest) -> ColdTierRepository:
    if request.param == "fake":
        return FakeColdTierRepository()
    raise AssertionError(f"unknown param {request.param!r}")  # pragma: no cover


async def test_export_then_verify_then_query_lifecycle_round_trips(
    cold_repo: ColdTierRepository,
) -> None:
    # FakeColdTierRepository is the concrete type under test here (the
    # Protocol has no `seed`/`poison` test helpers by design); real-engine
    # parametrisations add their own seeding fixture when E07-T04 lands.
    assert isinstance(cold_repo, FakeColdTierRepository)
    rng = TimeRange(start_us=0, end_us=1_000)
    cold_repo.seed("BTCUSDT", StreamKind.TRADES, [{"ts_us": 100}, {"ts_us": 200}])

    run = await cold_repo.export_partition("BTCUSDT", StreamKind.TRADES, rng)
    assert run.verified is False

    verified = await cold_repo.verify_checksums(run)
    assert verified is True

    manifest = await cold_repo.list_manifest("BTCUSDT", StreamKind.TRADES)
    assert manifest[0].verified is True

    rows = await cold_repo.query("BTCUSDT", StreamKind.TRADES, rng)
    assert rows == [{"ts_us": 100}, {"ts_us": 200}]


async def test_verify_checksums_raises_rather_than_returns_false_on_mismatch(
    cold_repo: ColdTierRepository,
) -> None:
    assert isinstance(cold_repo, FakeColdTierRepository)
    rng = TimeRange(start_us=0, end_us=1_000)
    run = await cold_repo.export_partition("BTCUSDT", StreamKind.TRADES, rng)
    cold_repo.poison(run.run_id)
    with pytest.raises(StorageExportVerifyFailed):
        await cold_repo.verify_checksums(run)


async def test_list_manifest_scoped_by_symbol_and_stream_ordered_by_range_start(
    cold_repo: ColdTierRepository,
) -> None:
    assert isinstance(cold_repo, FakeColdTierRepository)
    await cold_repo.export_partition(
        "BTCUSDT", StreamKind.TRADES, TimeRange(start_us=1_000, end_us=2_000)
    )
    await cold_repo.export_partition(
        "BTCUSDT", StreamKind.TRADES, TimeRange(start_us=0, end_us=1_000)
    )
    await cold_repo.export_partition(
        "ETHUSDT", StreamKind.TRADES, TimeRange(start_us=0, end_us=1_000)
    )
    manifest = await cold_repo.list_manifest("BTCUSDT", StreamKind.TRADES)
    assert [r.partition_range.start_us for r in manifest] == [0, 1_000]
    assert all(r.symbol == "BTCUSDT" for r in manifest)


async def test_retention_apply_blocks_pinned_range_but_allows_skip() -> None:
    repo = FakeRetentionRepository()
    repo.pin("BTCUSDT", StreamKind.BARS)

    blocked = RetentionDecision(
        symbol="BTCUSDT",
        stream=StreamKind.BARS,
        action="delete",
        range=TimeRange(start_us=0, end_us=1),
    )
    with pytest.raises(StorageRetentionBlockedByPin):
        await repo.apply([blocked])
    assert repo.applied == []

    allowed_skip = RetentionDecision(
        symbol="BTCUSDT",
        stream=StreamKind.BARS,
        action="skip",
        range=TimeRange(start_us=0, end_us=1),
        reason="pinned",
    )
    await repo.apply([allowed_skip])
    assert repo.applied == [allowed_skip]
