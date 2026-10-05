"""Unit tests for the storage perf harness (E07-Q03)."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import harness
import measure
from shapes import SHAPES
from stats import (
    PerfRegressionError,
    assert_within_baseline,
    compare_to_baseline,
    percentile_nearest_rank,
    summarize,
    write_report_section,
)

ROOT = Path(__file__).resolve().parents[3]


def test_percentile_nearest_rank_known_distribution() -> None:
    xs = list(range(1, 101))
    assert percentile_nearest_rank(xs, 50) == 50
    assert percentile_nearest_rank(xs, 95) == 95
    assert percentile_nearest_rank(xs, 99) == 99
    assert percentile_nearest_rank(xs, 100) == 100


def test_summarize_fewer_than_30_samples_reports_raw_not_percentiles() -> None:
    s = summarize([1.0] * 29)
    assert "p95" not in s and s["raw"] == [1.0] * 29
    assert "p95" in summarize([1.0] * 30)


def test_baseline_boundary_exactly_20_percent_is_not_a_regression() -> None:
    assert compare_to_baseline({"1": 100.0}, {"1": 120.0}) == []
    regs = compare_to_baseline({"1": 100.0}, {"1": 120.1})
    assert regs[0]["shape"] == "1" and regs[0]["delta_pct"] == 20.1


def test_baseline_missing_shape_is_reported() -> None:
    assert compare_to_baseline({"1": 1.0}, {})[0]["reason"] == "missing"


def test_timer_correctness_on_known_duration() -> None:
    t = time.perf_counter()
    time.sleep(0.05)
    assert 40 <= (time.perf_counter() - t) * 1000 < 500


def test_refuses_without_cv_env_test(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CV_ENV", raising=False)
    with pytest.raises(SystemExit):
        harness.require_test_env()
    monkeypatch.setenv("CV_ENV", "test")
    harness.require_test_env()


def test_shape_ids_cover_1_to_11_and_k01_ids() -> None:
    assert [s.id for s in SHAPES] == list(range(1, 12))
    sys.path.insert(0, str(ROOT / "spikes" / "storage"))
    import bench  # type: ignore[import-not-found]

    assert {s.k01_id for s in SHAPES if s.k01_id} == {s.id for s in bench.SHAPES}


def test_query_shapes_report_warm_and_cold_separately_with_conditions() -> None:
    out = harness.run_query_shapes(1, 500, samples=30, cold_samples=3)
    assert len(out) == 22
    warm, cold = out["1:warm"], out["1:cold"]
    assert "p99" in warm and "p99" not in cold  # cold has <30 samples -> raw
    for k in ("engine", "cache", "cpu_limit", "mem_limit", "dataset_id", "commit_sha"):
        assert k in warm["conditions"]
    assert warm["conditions"]["cache"] == "warm" and cold["conditions"]["cache"] == "cold"


def test_stress_ingest_never_drops_trades_and_records_backpressure() -> None:
    async def bounded() -> dict[str, object]:
        try:
            return await asyncio.wait_for(
                measure.run_ingest(
                    seconds=0.3,
                    batch=500,
                    drain_delay_s=0.02,
                    max_queue_rows=1000,
                    require_backpressure=True,
                ),
                timeout=30.0,
            )
        except TimeoutError:
            raise AssertionError(
                "run_ingest hung >30 s under backpressure (writer deadlock?)"
            ) from None

    r = asyncio.run(bounded())
    assert r["trade_rows_dropped"] == 0
    assert r["backpressure_onset_rows_s"] is not None
    assert r["max_queue_depth"] > 0


def test_stress_scenario_fails_when_queue_never_fills() -> None:
    with pytest.raises(AssertionError, match="never backed up"):
        asyncio.run(
            measure.run_ingest(
                seconds=0.2, batch=5000, max_queue_rows=200_000, require_backpressure=True
            )
        )


def test_compaction_reports_before_after() -> None:
    r = measure.run_cold(1, rows=2000, small_files=20)
    assert r["compaction"]["scan_ms_before"] > 0 and r["export"]["mb_per_s"] > 0


def test_loop_lag_drives_real_reaper_and_drops_every_partition() -> None:
    r = asyncio.run(measure.measure_loop_lag(symbols=3, days=5))
    assert r["samples"] > 0 and r["partitions_dropped"] == 15


def test_stress_ingest_reaches_sink_over_real_socket() -> None:
    r = asyncio.run(measure.run_ingest(seconds=0.3, batch=500))
    assert r["sink_lines_received"] == r["written_rows"] == r["submitted_rows"]


def test_baseline_gate_fires_on_deliberate_slowdown() -> None:
    clean = harness.run_query_shapes(1, 500, samples=30, cold_samples=0)
    base = {k.split(":")[0]: float(v["p95"]) for k, v in clean.items() if "p95" in v}
    slow = harness.run_query_shapes(1, 500, samples=30, cold_samples=0, slowdown_ms=50)
    cur = {k.split(":")[0]: float(v["p95"]) for k, v in slow.items() if "p95" in v}
    regs = compare_to_baseline(base, cur)
    # a 50 ms/query slowdown must trip the gate (shapes already >250 ms may absorb it)
    assert len(regs) >= 6
    assert all(r["delta_pct"] > 20 for r in regs if "delta_pct" in r)


def test_measured_growth_has_all_replayed_streams() -> None:
    r = measure.measure_storage_growth(sample_rows=500)
    assert set(r["streams"]) == {"trades", "tickers", "orderbook_deltas"}
    assert r["measured_streams_parquet_gb_day"] > 0


def test_baseline_json_is_committed_and_covers_all_shapes() -> None:
    b = json.loads((Path(__file__).parent / "baseline.json").read_text("utf-8"))
    assert set(b["p95_ms"]) == {str(i) for i in range(1, 12)}


def test_comparator_raises_on_synthetic_2x_regression() -> None:
    base = json.loads((Path(__file__).parent / "baseline_integration.json").read_text("utf-8"))
    metrics = {k: float(v) for k, v in base["metrics_ms"].items()}
    doubled = {k: v * 2 for k, v in metrics.items()}
    with pytest.raises(PerfRegressionError, match="reaper_lag_max_ms"):
        assert_within_baseline(metrics, doubled, abs_slack_ms=25.0)
    assert_within_baseline(metrics, metrics, abs_slack_ms=25.0)  # equal -> passes


def test_comparator_absolute_slack_absorbs_sub_ms_jitter() -> None:
    assert_within_baseline({"q": 1.0}, {"q": 3.0}, abs_slack_ms=25.0)
    with pytest.raises(PerfRegressionError):
        assert_within_baseline({"q": 1.0}, {}, abs_slack_ms=25.0)


def test_report_writer_merges_sections(tmp_path: Path) -> None:
    p = tmp_path / "build" / "reports" / "storage-perf.json"
    write_report_section(p, "a", {"x": 1})
    write_report_section(p, "b", {"y": 2})
    assert json.loads(p.read_text("utf-8")) == {"a": {"x": 1}, "b": {"y": 2}}


def test_adr_addendum_compaction_numbers_match_committed_results() -> None:
    root = Path(__file__).resolve().parents[3]
    c = json.loads((Path(__file__).parent / "results.json").read_text("utf-8"))["cold"][
        "compaction"
    ]
    adr = next((root / "docs/plan/27-adrs").glob("ADR-0022-*.md")).read_text("utf-8")
    expected = f"{c['scan_ms_before']} ms -> {c['scan_ms_after']} ms ({c['speedup_x']}x)"
    assert expected in adr


def test_harness_entry_point_exits_1_naming_shape_and_delta_on_slowed_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CV_ENV", "test")
    here = Path(__file__).parent
    res = json.loads((here / "baseline.json").read_text("utf-8"))["p95_ms"]
    shapes = {f"{k}:warm": {"p95": v * 1.3 + 5} for k, v in res.items()}
    slowed = tmp_path / "results.json"
    slowed.write_text(json.dumps({"shapes": shapes}), encoding="utf-8")
    rc = harness.main(["--compare-only", str(slowed), "--baseline", str(here / "baseline.json")])
    out = capsys.readouterr().out
    assert rc == 1
    first = next(iter(res))
    assert first in out and "%" in out
    clean = tmp_path / "clean.json"
    clean.write_text(
        json.dumps({"shapes": {f"{k}:warm": {"p95": v} for k, v in res.items()}}), encoding="utf-8"
    )
    assert (
        harness.main(["--compare-only", str(clean), "--baseline", str(here / "baseline.json")]) == 0
    )
