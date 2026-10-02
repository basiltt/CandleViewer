"""Reaper tests (E07-T05): AC coverage with call-order spies."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.retention.policy import RetentionPolicy, load_defaults
from candleviewer.storage.retention.ports import Partition, Tier
from candleviewer.storage.retention.reaper import Reaper

DAY = 86_400_000_000
NOW = datetime(2026, 6, 1, tzinfo=UTC)
NOW_US = int(NOW.timestamp() * 1_000_000)


def part(
    sym: str, age_days: int, tier: Tier = "hot", stream: StreamKind = StreamKind.TRADES
) -> Partition:
    end = NOW_US - age_days * DAY
    return Partition(sym, stream, tier, TimeRange(start_us=end - DAY, end_us=end), 100, 1000)


class Env:
    def __init__(self, parts: list[Partition], free: float = 50.0) -> None:
        self.parts, self.free = parts, free
        self.log: list[str] = []
        self.pinned: set[str] = set()
        self.unverified: set[Partition] = set()
        self.replay: dict[Partition, str] = {}
        self.audits: list[tuple[str, dict[str, Any]]] = []
        self.events: list[tuple[str, str, dict[str, Any]]] = []
        self.paused: list[str] = []
        self.prio: dict[str, int] = {}
        self.auto: set[str] = set()

    # StorageOps
    async def list_partitions(self, symbol: str, stream: StreamKind, tier: Tier) -> list[Partition]:
        return [
            p for p in self.parts if p.symbol == symbol and p.stream == stream and p.tier == tier
        ]

    async def is_exported_and_verified(self, p: Partition) -> bool:
        return p not in self.unverified

    async def drop(self, p: Partition) -> None:
        self.log.append(f"drop:{p.symbol}:{p.range.end_us}")
        if p in self.parts:
            self.parts.remove(p)

    # facts
    async def symbols(self) -> list[str]:
        return sorted({p.symbol for p in self.parts})

    async def pinned_symbols(self) -> set[str]:
        return self.pinned

    async def priority(self, s: str) -> int:
        return self.prio.get(s, 0)

    async def auto_recorded_symbols(self) -> set[str]:
        return self.auto

    async def replay_session_for(self, p: Partition) -> str | None:
        return self.replay.get(p)

    async def has_unexported_journal_trade(self, p: Partition) -> bool:
        return False

    def free_pct(self) -> float:
        return self.free

    async def write(self, action: str, detail: dict[str, Any]) -> None:
        self.audits.append((action, detail))
        self.log.append(f"audit:{action}")

    async def emit(self, severity: str, code: str, detail: dict[str, Any]) -> None:
        self.events.append((severity, code, detail))
        self.log.append(f"event:{severity}")

    async def pause(self, symbol: str) -> None:
        self.paused.append(symbol)

    def reaper(self) -> Reaper:
        return Reaper(
            RetentionPolicy([], load_defaults()),
            self,
            self,
            self,
            self,
            self,
            self,
            clock=lambda: NOW,
        )


async def test_dry_run_reports_only_old_partitions_and_deletes_nothing() -> None:
    env = Env([part("A", 40), part("A", 10)])
    report = await env.reaper().dry_run()
    assert [i.partition.range.end_us for i in report.to_drop] == [NOW_US - 40 * DAY]
    assert report.to_drop[0].partition.rows == 100 and report.to_drop[0].partition.bytes == 1000
    assert not any(e.startswith("drop") for e in env.log)


async def test_pinned_never_dropped_and_reported() -> None:
    env = Env([part("A", 40, "hot"), part("A", 800, "cold")])
    env.pinned.add("A")
    report = await env.reaper().run()
    assert not any(e.startswith("drop") for e in env.log)
    assert {i.reason for i in report.skipped} == {"pinned"}
    assert {i.error_code for i in report.skipped} == {"STORAGE_RETENTION_BLOCKED_BY_PIN"}


async def test_unverified_blocked_and_run_continues() -> None:
    bad, good = part("A", 40), part("B", 41)
    env = Env([bad, good])
    env.unverified.add(bad)
    report = await env.reaper().run()
    assert env.log.count(f"drop:B:{good.range.end_us}") == 1
    assert not any("drop:A" in e for e in env.log)
    assert report.skipped[0].error_code == "STORAGE_RETENTION_BLOCKED_UNVERIFIED"
    assert any(s == "CRITICAL" for s, _, _ in env.events)


async def test_replay_referenced_cold_partition_skipped_with_session_id() -> None:
    p = part("A", 800, "cold")
    env = Env([p])
    env.replay[p] = "sess-1"
    report = await env.reaper().run()
    assert not any(e.startswith("drop") for e in env.log)
    assert report.skipped[0].detail == "session_id=sess-1"
    skip = next(d for a, d in env.audits if a == "retention.skip")
    assert skip["info"] == "session_id=sess-1"


async def test_one_audit_entry_per_deletion_with_required_fields() -> None:
    env = Env([part("A", 40), part("B", 45)])
    await env.reaper().run()
    purges = [d for a, d in env.audits if a == "retention.purge"]
    assert len(purges) == 2
    for d in purges:
        assert {"symbol", "stream", "range_start_us", "range_end_us", "freed_bytes"} <= set(d)


async def test_pin_added_after_dry_run_still_blocks() -> None:
    env = Env([part("A", 40)])
    r = env.reaper()
    report = await r.dry_run()
    env.pinned.add("A")
    out = await r.apply(report)
    assert not any(e.startswith("drop") for e in env.log)
    assert out.skipped[0].reason == "pinned"


async def test_accelerated_mode_priority_halved_and_alert_before_delete() -> None:
    # 20 days old: kept at normal retention (30d) but expired at halved (15d)
    env = Env([part("LOW", 20), part("HIGH", 20), part("PIN", 20)], free=10.0)
    env.prio = {"LOW": 1, "HIGH": 9, "PIN": 0}
    env.pinned.add("PIN")
    report = await env.reaper().run()
    assert report.accelerated
    order = [e for e in env.log if e.startswith(("event:", "drop"))]
    assert order[:2] == ["event:WARNING", "event:WARNING"]  # alerts first
    assert order.index("event:WARNING") < order.index(
        next(e for e in order if e.startswith("drop"))
    )
    drops = [e for e in env.log if e.startswith("drop")]
    assert [d.split(":")[1] for d in drops] == ["LOW", "HIGH"]
    assert [d["symbol"] for s, c, d in env.events] == ["LOW", "HIGH"]
    # BUG-D: detail carries the effective halved hot window (hours), not just the symbol
    detail = env.events[0][2]
    assert detail["retention_factor_pct"] == 50
    hot = {k: v for k, v in detail.items() if k.startswith("effective_hot_hours_")}
    assert hot and all(isinstance(v, int) and v > 0 for v in hot.values())


async def test_not_accelerated_above_threshold_keeps_normal_retention() -> None:
    env = Env([part("A", 20)], free=30.0)
    assert (await env.reaper().dry_run()).to_drop == []


async def test_critical_disk_pauses_non_pinned_auto_symbols_after_event() -> None:
    env = Env([], free=3.0)
    env.auto, env.pinned = {"A", "B", "P"}, {"P"}
    assert await env.reaper().guard() is True
    assert env.paused == ["A", "B"]
    assert env.events[0][0] == "CRITICAL" and env.events[0][1] == "STORAGE_DISK_CRITICAL"
    assert await Env([], free=50.0).reaper().guard() is False


async def test_recovery_hysteresis_leaves_accelerated_only_above_25() -> None:
    env = Env([], free=10.0)
    r = env.reaper()
    await r.dry_run()
    env.free = 20.0
    assert (await r.dry_run()).accelerated
    env.free = 26.0
    assert not (await r.dry_run()).accelerated


async def test_drop_failure_does_not_abort_run() -> None:
    a, b = part("A", 40), part("B", 41)
    env = Env([a, b])
    real = env.drop

    async def flaky(p: Partition) -> None:
        if p.symbol == "A":
            raise OSError("boom")
        await real(p)

    env.drop = flaky  # type: ignore[method-assign]  # justified: failure injection
    await env.reaper().run()
    assert any("drop:B" in e for e in env.log)


async def test_apply_twice_same_report_writes_single_purge_audit() -> None:
    env = Env([part("A", 40)])
    r = env.reaper()
    report = await r.dry_run()
    await r.apply(report)
    await r.apply(report)
    assert [a for a, _ in env.audits].count("retention.purge") == 1
    assert [e for e in env.log if e.startswith("drop")] == [f"drop:A:{NOW_US - 40 * DAY}"]


async def test_two_reapers_same_report_single_purge_audit() -> None:
    env = Env([part("A", 40)])
    report = await env.reaper().dry_run()
    await env.reaper().apply(report)
    await env.reaper().apply(report)
    assert [a for a, _ in env.audits].count("retention.purge") == 1
