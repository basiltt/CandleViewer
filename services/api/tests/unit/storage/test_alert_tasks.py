"""E40-T01: alert retention purge + gauge tasks."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq

from candleviewer.storage.repositories.alert_deliveries_sqlalchemy import DeliveryRow
from candleviewer.storage.retention.alert_tasks import AlertDeliveriesPurgeTask, AlertGaugeTask
from candleviewer.storage.retention.schedule import RetentionSchedule


class _Purger:
    def __init__(self, rows: list[DeliveryRow] | None = None) -> None:
        self.rows = rows or []
        self.days: list[int] = []
        self.deleted: list[int] = []
        self.fail_delete = False

    async def fetch_expired(self, days: int, limit: int = 5000) -> list[DeliveryRow]:
        self.days.append(days)
        return [r for r in self.rows if r.id not in self.deleted][:limit]

    async def delete_ids(self, ids: list[int]) -> int:
        if self.fail_delete:
            raise RuntimeError("append-only")
        self.deleted += ids
        return len(ids)


def _row(i: int, day: int) -> DeliveryRow:
    return DeliveryRow(
        id=i,
        alert_id="a",
        user_id=None,
        channel="in_app",
        status="sent",
        title="t",
        body="",
        context={"k": i},
        attempt=1,
        http_status=None,
        error_message=None,
        queued_at=datetime(2026, 1, day, tzinfo=UTC),
        sent_at=None,
        acked_at=None,
        acked_by=None,
    )


_ON = RetentionSchedule.from_env({"CV_RETENTION_ENABLED": "true"})


class _Child:
    def __init__(self) -> None:
        self.value = -1.0

    def set(self, v: float) -> None:
        self.value = v


class _Metric:
    def __init__(self) -> None:
        self.kids: dict[str, _Child] = {}

    def labels(self, *v: str) -> _Child:
        return self.kids.setdefault(v[0], _Child())

    def child(self) -> _Child:
        return self.labels("")


class _Gauges:
    async def gauges(self) -> dict[str, int]:
        return {
            "cv_alerts_total{enabled=true}": 3,
            "cv_alerts_total{enabled=false}": 1,
            "cv_alert_deliveries_pending": 4,
        }


async def test_purge_archives_to_parquet_then_deletes(tmp_path: Path) -> None:
    repo = _Purger([_row(1, 1), _row(2, 1), _row(3, 2)])
    await AlertDeliveriesPurgeTask(repo, _ON, archive_root=tmp_path).run_once()
    assert repo.days[0] == 180
    assert sorted(repo.deleted) == [1, 2, 3]
    files = sorted((tmp_path / "alert_deliveries").glob("dt=*/*.parquet"))
    assert [f.parent.name for f in files] == ["dt=2026-01-01", "dt=2026-01-02"]
    assert sum(pq.read_table(f).num_rows for f in files) == 3


async def test_purge_keeps_rows_when_archive_fails(tmp_path: Path) -> None:
    repo = _Purger([_row(1, 1)])
    blocker = tmp_path / "alert_deliveries"
    blocker.write_text("not a dir")  # archive mkdir fails -> nothing may be deleted
    await AlertDeliveriesPurgeTask(repo, _ON, archive_root=tmp_path).run_once()
    assert repo.deleted == []


async def test_purge_failure_is_swallowed_and_logged(tmp_path: Path) -> None:
    repo = _Purger([_row(1, 1)])
    repo.fail_delete = True
    await AlertDeliveriesPurgeTask(repo, _ON, archive_root=tmp_path).run_once()


async def test_purge_disabled_never_starts(tmp_path: Path) -> None:
    off = RetentionSchedule.from_env({})
    task = AlertDeliveriesPurgeTask(_Purger(), off, archive_root=tmp_path)
    task.start()
    assert not task.running


async def test_purge_off_without_owner_dsn(tmp_path: Path) -> None:
    task = AlertDeliveriesPurgeTask(_Purger(), _ON, archive_root=tmp_path, has_owner_dsn=False)
    task.start()
    assert not task.running


async def test_gauge_task_sets_metrics() -> None:
    total, pending = _Metric(), _Metric()
    await AlertGaugeTask(_Gauges(), total, pending).run_once()  # type: ignore[arg-type]  # test double
    assert total.kids["true"].value == 3
    assert total.kids["false"].value == 1
    assert pending.child().value == 4
