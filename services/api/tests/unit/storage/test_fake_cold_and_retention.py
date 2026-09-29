"""Unit tests for `FakeColdTierRepository`, `FakeRetentionRepository`,
`FakeRelationalRepository`/`FakeUnitOfWork` (E07-T01)."""

from __future__ import annotations

import pytest

from candleviewer.storage.errors import StorageExportVerifyFailed, StorageRetentionBlockedByPin
from candleviewer.storage.models import RetentionDecision, StreamKind, TimeRange
from candleviewer.storage.testing import (
    FakeColdTierRepository,
    FakeRelationalRepository,
    FakeRetentionRepository,
)


async def test_export_partition_returns_unverified_run() -> None:
    repo = FakeColdTierRepository()
    run = await repo.export_partition(
        "BTCUSDT", StreamKind.TRADES, TimeRange(start_us=0, end_us=1_000)
    )
    assert run.verified is False


async def test_verify_checksums_marks_run_verified_and_updates_manifest() -> None:
    repo = FakeColdTierRepository()
    run = await repo.export_partition(
        "BTCUSDT", StreamKind.TRADES, TimeRange(start_us=0, end_us=1_000)
    )
    assert await repo.verify_checksums(run) is True
    manifest = await repo.list_manifest("BTCUSDT", StreamKind.TRADES)
    assert manifest[0].verified is True


async def test_verify_checksums_raises_on_poisoned_run() -> None:
    repo = FakeColdTierRepository()
    run = await repo.export_partition(
        "BTCUSDT", StreamKind.TRADES, TimeRange(start_us=0, end_us=1_000)
    )
    repo.poison(run.run_id)
    with pytest.raises(StorageExportVerifyFailed):
        await repo.verify_checksums(run)


async def test_list_manifest_scoped_and_sorted() -> None:
    repo = FakeColdTierRepository()
    await repo.export_partition(
        "BTCUSDT", StreamKind.TRADES, TimeRange(start_us=1_000, end_us=2_000)
    )
    await repo.export_partition("BTCUSDT", StreamKind.TRADES, TimeRange(start_us=0, end_us=1_000))
    await repo.export_partition("ETHUSDT", StreamKind.TRADES, TimeRange(start_us=0, end_us=1_000))
    manifest = await repo.list_manifest("BTCUSDT", StreamKind.TRADES)
    assert [r.partition_range.start_us for r in manifest] == [0, 1_000]


async def test_query_filters_seeded_rows_by_range() -> None:
    repo = FakeColdTierRepository()
    repo.seed(
        "BTCUSDT",
        StreamKind.TRADES,
        [{"ts_us": 100}, {"ts_us": 200}, {"ts_us": 300}],
    )
    result = await repo.query("BTCUSDT", StreamKind.TRADES, TimeRange(start_us=150, end_us=250))
    assert result == [{"ts_us": 200}]


async def test_retention_apply_records_non_pinned_decisions() -> None:
    repo = FakeRetentionRepository()
    decision = RetentionDecision(
        symbol="BTCUSDT",
        stream=StreamKind.BARS,
        action="roll_off_to_cold",
        range=TimeRange(start_us=0, end_us=1),
    )
    await repo.apply([decision])
    assert repo.applied == [decision]


async def test_retention_apply_blocks_pinned_stream() -> None:
    repo = FakeRetentionRepository()
    repo.pin("BTCUSDT", StreamKind.BARS)
    decision = RetentionDecision(
        symbol="BTCUSDT",
        stream=StreamKind.BARS,
        action="delete",
        range=TimeRange(start_us=0, end_us=1),
    )
    with pytest.raises(StorageRetentionBlockedByPin):
        await repo.apply([decision])
    assert repo.applied == []


async def test_retention_apply_allows_skip_on_pinned_stream() -> None:
    repo = FakeRetentionRepository()
    repo.pin("BTCUSDT", StreamKind.BARS)
    decision = RetentionDecision(
        symbol="BTCUSDT",
        stream=StreamKind.BARS,
        action="skip",
        range=TimeRange(start_us=0, end_us=1),
        reason="pinned",
    )
    await repo.apply([decision])
    assert repo.applied == [decision]


async def test_retention_plan_defaults_to_empty() -> None:
    repo = FakeRetentionRepository()
    assert await repo.plan() == []
    assert repo.policies() == []


async def test_unit_of_work_commits_once() -> None:
    factory = FakeRelationalRepository()
    async with factory.unit_of_work() as uow:
        await uow.commit()
    assert uow.committed is True

    with pytest.raises(RuntimeError):
        await uow.commit()


async def test_unit_of_work_rolls_back_on_exception() -> None:
    factory = FakeRelationalRepository()
    uow = factory.unit_of_work()
    with pytest.raises(ValueError):
        async with uow:
            raise ValueError("boom")
    assert uow.rolled_back is True


async def test_unit_of_work_explicit_rollback() -> None:
    factory = FakeRelationalRepository()
    uow = factory.unit_of_work()
    await uow.rollback()
    assert uow.rolled_back is True
    assert uow.committed is False
