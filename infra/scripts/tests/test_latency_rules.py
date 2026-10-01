"""E04-T06: latency-budget recording/alert rule contract (names are stable)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

RULES = Path(__file__).resolve().parents[2] / "prometheus" / "alerts" / "latency_budget.yml"

#: Dashboards (E04-S01) and alerts (E04-T05) depend on these names.
STABLE_RECORDS = {
    "cv:ingest_stage_seconds:p50_5m",
    "cv:ingest_stage_seconds:p95_5m",
    "cv:ingest_stage_seconds:p99_5m",
    "cv:ingest_stage_seconds:mean_5m",
    "cv:fe_ws_decode_ms:p95_5m",
    "cv:fe_frame_time_ms:p95_5m",
    "cv:e2e_tick_to_paint_seconds:p50_5m",
    "cv:e2e_tick_to_paint_seconds:p95_1m",
    "cv:e2e_tick_to_paint_seconds:p95_5m",
    "cv:e2e_tick_to_paint_seconds:p99_5m",
    "cv:latency_stage_share:ratio_5m",
    "cv:slo_tick_to_paint:burn_rate_1h",
    "cv:slo_tick_to_paint:burn_rate_6h",
    "cv:slo_backend_fanout:burn_rate_1h",
    "cv:slo_backend_fanout:burn_rate_6h",
    "cv:slo_fe_decode:burn_rate_1h",
}


def _rules() -> list[dict[str, Any]]:
    doc = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    return [r for g in doc["groups"] for r in g["rules"]]


def test_recording_rule_names_are_stable() -> None:
    assert {r["record"] for r in _rules() if "record" in r} == STABLE_RECORDS


def test_breach_alert_fires_on_p95_over_250ms_for_60s_and_names_stage() -> None:
    alert = next(r for r in _rules() if r.get("alert") == "LatencyBudgetBreach")
    assert alert["expr"].strip() == "cv:e2e_tick_to_paint_seconds:p95_1m > 0.25"
    assert alert["for"] == "60s"
    assert alert["labels"]["severity"] == "ticket"
    summary = alert["annotations"]["summary"]
    assert "cv:latency_stage_share:ratio_5m" in summary and ".Labels.stage" in summary


def test_e2e_is_measured_directly_not_summed_from_stage_percentiles() -> None:
    for r in _rules():
        if r.get("record", "").startswith("cv:e2e_tick_to_paint_seconds:"):
            assert "ingest_stage_seconds" not in r["expr"]


def test_burn_rates_use_documented_budget_edges() -> None:
    by = {r["record"]: r["expr"] for r in _rules() if "record" in r}
    assert 'le="0.1"' in by["cv:slo_tick_to_paint:burn_rate_1h"]
    assert 'le="0.02"' in by["cv:slo_backend_fanout:burn_rate_1h"]
    assert 'le="4"' in by["cv:slo_fe_decode:burn_rate_1h"]
