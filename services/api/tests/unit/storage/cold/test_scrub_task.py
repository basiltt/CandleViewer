"""E07-X02 / SR-094: the weekly scrub is wired as a supervised periodic task."""

from __future__ import annotations

import asyncio
from pathlib import Path

from candleviewer.app import create_app
from candleviewer.settings import Settings
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.scrub import ScrubTask


class _Sink:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str]] = []

    async def emit(self, severity: str, code: str, detail: dict[str, str | int]) -> None:
        self.rows.append((severity, code))


def test_app_registers_scrub_task_only_when_enabled(tmp_path: Path) -> None:
    off = create_app(Settings(parquet_root=str(tmp_path)))
    on = create_app(Settings(parquet_root=str(tmp_path), scrub_enabled=True))
    assert off.state.scrub_task is None
    assert isinstance(on.state.scrub_task, ScrubTask)


async def test_scrub_task_runs_on_schedule_and_audits_each_run(tmp_path: Path) -> None:
    sink = _Sink()
    sleeps: list[float] = []
    gate = asyncio.Event()

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)
        if len(sleeps) >= 2:
            gate.set()
            await asyncio.Event().wait()

    task = ScrubTask(DatasetRegistry(tmp_path), sink, interval_s=60.0, sleep=fake_sleep)
    task.start()
    await asyncio.wait_for(gate.wait(), 5)
    assert task.running
    assert sleeps[:2] == [60.0, 60.0]
    assert sink.rows.count(("INFO", "STORAGE_COLD_SCRUB_RUN")) == 2
    await task.stop()
    assert not task.running
