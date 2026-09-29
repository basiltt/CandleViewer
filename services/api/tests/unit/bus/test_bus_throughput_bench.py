"""Smoke test for the `bench/bus_throughput.py` harness (E08-T03 DoD:
"Benchmark recorded in the PR with before/after numbers"). This does not
assert an absolute latency budget — the CI regression gate compares against
the `main` baseline separately — it only asserts the harness runs, delivers
every published event, and returns well-formed percentile results at a
small event count so the suite stays fast."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BENCH_DIR = Path(__file__).resolve().parents[3] / "bench"
sys.path.insert(0, str(BENCH_DIR))

from bus_throughput import BenchResult, _run_once  # noqa: E402


@pytest.mark.asyncio
async def test_bus_throughput_bench_runs_and_delivers_every_event() -> None:
    result = await _run_once(events_per_s=200, n_subscribers=2, duration_s=0.05)

    assert isinstance(result, BenchResult)
    assert result.delivered == 10
    assert result.p50_ms <= result.p95_ms <= result.p99_ms
