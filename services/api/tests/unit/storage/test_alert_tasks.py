"""E40-T01: alert retention purge + gauge tasks."""

from __future__ import annotations

from candleviewer.storage.retention.alert_tasks import AlertDeliveriesPurgeTask, AlertGaugeTask
from candleviewer.storage.retention.schedule import RetentionSchedule


class _Purger:
    def __init__(self) -> None:
        self.days: list[int] = []

    async def purge_expired(self, days: int) -> int:
        self.days.append(days)
        return 1


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


async def test_purge_uses_180_day_hot_window() -> None:
    repo = _Purger()
    sched = RetentionSchedule.from_env({"CV_RETENTION_ENABLED": "true"})
    task = AlertDeliveriesPurgeTask(repo, sched)
    await task.run_once()
    assert repo.days == [180]


async def test_purge_disabled_never_starts() -> None:
    task = AlertDeliveriesPurgeTask(_Purger(), RetentionSchedule.from_env({}))
    task.start()
    assert not task.running


async def test_gauge_task_sets_metrics() -> None:
    total, pending = _Metric(), _Metric()
    await AlertGaugeTask(_Gauges(), total, pending).run_once()  # type: ignore[arg-type]  # test double
    assert total.kids["true"].value == 3
    assert total.kids["false"].value == 1
    assert pending.child().value == 4
