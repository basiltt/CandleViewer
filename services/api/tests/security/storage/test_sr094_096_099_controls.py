"""SR-094 / SR-096 / SR-099 verification (E07-X02), reusing the E07-T04/T05 fakes."""

from __future__ import annotations

from pathlib import Path

import pytest

from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.parquet_repository import ParquetColdTierRepository
from candleviewer.storage.errors import StorageExportVerifyFailed
from candleviewer.storage.models import StreamKind
from tests.unit.storage.cold._helpers import FakeHotSource, RecordingSink, day_range, trades_table
from tests.unit.storage.retention.test_reaper import DAY, NOW_US, Env, part


async def test_sr094_corrupt_file_is_quarantined_and_alerted_critical(tmp_path: Path) -> None:
    sink = RecordingSink()
    repo = ParquetColdTierRepository(
        DatasetRegistry(tmp_path), FakeHotSource(trades_table(5)), events=sink
    )
    await repo.export_partition("BTCUSDT", StreamKind.TRADES, day_range())
    f = tmp_path / "trades" / "symbol=BTCUSDT" / "dt=2026-10-17" / "part-0000.parquet"
    data = bytearray(f.read_bytes())
    data[len(data) // 2] ^= 0x01
    f.write_bytes(bytes(data))
    with pytest.raises(StorageExportVerifyFailed):
        await repo.query("BTCUSDT", StreamKind.TRADES, day_range())
    assert sink.events[-1][:2] == ("CRITICAL", "STORAGE_COLD_FILE_QUARANTINED")
    assert not f.exists()


async def test_sr096_alert_precedes_deletion_and_recorder_pauses_at_critical() -> None:
    env = Env([part("A", 20)], free=10.0)
    await env.reaper().run()
    order = [e for e in env.log if e.startswith(("event:", "drop"))]
    first_drop = next(i for i, e in enumerate(order) if e.startswith("drop"))
    assert any(e.startswith("event:") for e in order[:first_drop])
    crit = Env([], free=3.0)
    crit.auto = {"A"}
    assert await crit.reaper().guard() is True
    assert crit.paused == ["A"]


async def test_sr096_trading_path_does_not_depend_on_recording_volume_guard() -> None:
    # Guard only touches the recorder control port; it exposes no relational/OMS port.
    env = Env([], free=1.0)
    env.auto = {"A"}
    await env.reaper().guard()
    assert set(vars(env.reaper()).keys()).isdisjoint({"_oms", "_postgres", "_orders"})


async def test_sr099_pinned_symbol_survives_full_cycle_and_deletions_audited_once() -> None:
    env = Env([part("PIN", 800, "cold"), part("PIN", 40), part("A", 40), part("B", 45)])
    env.pinned.add("PIN")
    report = await env.reaper().run()
    drops = [e for e in env.log if e.startswith("drop")]
    assert not any("PIN" in d for d in drops)
    purges = [d for a, d in env.audits if a == "retention.purge"]
    assert len(purges) == len(drops) == 2
    for d in purges:
        assert {"symbol", "stream", "range_start_us", "range_end_us", "freed_bytes"} <= set(d)
    assert report.skipped


async def test_sr099_dry_run_deletes_nothing() -> None:
    env = Env([part("A", 40)])
    await env.reaper().dry_run()
    assert not any(e.startswith("drop") for e in env.log)
    assert NOW_US > DAY
