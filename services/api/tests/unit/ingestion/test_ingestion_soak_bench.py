"""E08-T06 soak + burst harness (`bench/ingestion_soak.py`): deterministic,
no network, no sleeps (virtual time). The sampler is a fake, so memory
assertions are about the harness's verdict logic, not this host."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

BENCH_DIR = Path(__file__).resolve().parents[3] / "bench"
sys.path.insert(0, str(BENCH_DIR))

import ingestion_soak as soak  # noqa: E402 - path set up for the bench script above


class FakeSampler:
    """RSS grows by `slope` bytes per sample from a 100 MiB base."""

    def __init__(self, slope: int = 0) -> None:
        self.n = 0
        self.slope = slope

    def sample(self) -> soak.ProcSample:
        self.n += 1
        return soak.ProcSample(100 * 2**20 + self.n * self.slope, 12.5)


def _soak_cfg(duration_s: float = 60.0, realtime: bool = False) -> soak.RunConfig:
    return soak.RunConfig(
        mode="soak", duration_s=duration_s, sample_every_s=5.0, trades_per_s=20, realtime=realtime
    )


async def test_soak_flat_memory_three_symbols_passes_and_records_budgets() -> None:
    rep = await soak.run(_soak_cfg(), FakeSampler())
    assert rep.passed, rep.failures
    assert len(soak.SYMBOLS) >= 3 and rep.config["symbols"] == soak.SYMBOLS
    assert rep.trades_lost == 0 and rep.trades_published == rep.trades_delivered > 0
    assert set(rep.latency_ms) == {"ingest_to_bus", "book_apply"}
    assert rep.latency_ms["ingest_to_bus"]["p95"] <= soak.BUDGET_INGEST_BUS_P95_MS
    assert rep.latency_ms["book_apply"]["p95"] <= soak.BUDGET_BOOK_APPLY_P95_MS
    assert len(rep.curve) >= 12 and rep.memory_growth == 0.0
    soak.enforce(rep)  # no raise


async def test_soak_memory_growth_over_5pct_fails_explicitly_with_curve() -> None:
    rep = await soak.run(_soak_cfg(), FakeSampler(slope=1 * 2**20))
    assert not rep.passed
    assert rep.memory_growth > soak.MEMORY_TOLERANCE
    with pytest.raises(soak.SoakRegressionError) as err:
        soak.enforce(rep)
    assert len(err.value.curve) == len(rep.curve)
    assert "curve:" in str(err.value) and "MiB" in str(err.value)


def test_check_memory_within_tolerance_and_short_curves() -> None:
    pts = [soak.Point(float(i), 1000 + i, 0.0, 0.0, 0, 0) for i in range(10)]
    assert abs(soak.check_memory(pts)) < soak.MEMORY_TOLERANCE
    assert soak.memory_growth(pts[:1]) == 0.0


async def test_burst_5x_loses_nothing_backpressures_and_recovers() -> None:
    cfg = soak.RunConfig(mode="burst", burst_s=60.0, trades_per_s=20, sample_every_s=10.0)
    rep = await soak.run(cfg, FakeSampler())
    assert rep.passed, rep.failures
    assert rep.trades_lost == 0 and rep.out_of_order == 0
    assert rep.queue_full_events > 0  # ingest_queue_full_total{class="trade"} moved
    assert rep.recovery_s is not None and rep.recovery_s <= soak.RECOVERY_WINDOW_S


async def test_burst_without_headroom_fails_recovery_window() -> None:
    cfg = soak.RunConfig(
        mode="burst", burst_s=60.0, trades_per_s=20, capacity_factor=1, sample_every_s=10.0
    )
    rep = await soak.run(cfg, FakeSampler())
    assert rep.trades_lost == 0  # never-drop still holds: the final drain delivers all
    assert not rep.passed and any("steady state" in f for f in rep.failures)
    with pytest.raises(soak.BurstError):
        soak.enforce(rep)


async def test_realtime_mode_paces_with_injected_sleep() -> None:
    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    cfg = _soak_cfg(duration_s=1.0, realtime=True)
    rep = await soak.run(cfg, FakeSampler(), sleep=fake_sleep)
    assert rep.passed and slept == [cfg.tick_s] * 10


def test_percentile_and_reservoir_are_bounded() -> None:
    assert soak.percentile([], 0.95) == 0.0
    assert soak.percentile(list(range(1, 101)), 0.95) == 95
    r = soak.Reservoir(size=10)
    for i in range(1000):
        r.add(float(i))
    assert len(r.values) == 10 and r.summary()["count"] == 1000.0


@pytest.fixture
def _no_psutil(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(soak, "PsutilSampler", lambda pid=None: FakeSampler())
    yield None


@pytest.mark.usefixtures("_no_psutil")
def test_cli_writes_machine_readable_report(tmp_path: Path) -> None:
    out = tmp_path / "soak.json"
    code = soak.main(["soak", "--duration-s", "20", "--trades-per-s", "10", "--out", str(out)])
    data = json.loads(out.read_text(encoding="utf-8"))
    assert code == 0 and data["passed"] is True and data["mode"] == "soak"
    assert {"latency_ms", "curve", "memory_growth", "trades_lost"} <= set(data)


def test_psutil_sampler_reads_this_process() -> None:
    s = soak.PsutilSampler().sample()
    assert s.rss_bytes > 0 and s.cpu_percent >= 0.0
