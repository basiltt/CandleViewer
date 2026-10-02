"""Unit tests for the E42-K01 CI spike helpers (no database)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench.audit_index import ci_spike as cs

_PLAN = [
    {
        "Execution Time": 1.25,
        "Plan": {
            "Node Type": "Limit",
            "Shared Hit Blocks": 7,
            "Plans": [{"Node Type": "Index Scan", "Index Name": "ix_audit_time"}],
        },
    }
]


def test_percentile_nearest_rank_small_sample_p99_is_max() -> None:
    assert cs.percentile([3.0, 1.0, 2.0], 50) == 2.0
    assert cs.percentile([float(i) for i in range(1, 21)], 99) == 20.0
    assert cs.percentile([float(i) for i in range(1, 101)], 95) == 95.0


def test_percentile_empty_raises() -> None:
    with pytest.raises(ValueError):
        cs.percentile([], 50)


def test_parse_plan_collects_nodes_and_indexes() -> None:
    for doc in (_PLAN, json.dumps(_PLAN)):
        p = cs.parse_plan(doc)
        assert p["exec_ms"] == 1.25
        assert p["node_types"] == ["Index Scan", "Limit"]
        assert p["indexes"] == ["ix_audit_time"]
        assert p["shared_hit"] == 7 and p["shared_read"] == 0


def test_build_query_keyset_and_materialized_forms() -> None:
    q = cs.build_query("action = 'x'", "2026-02-01T00:00:00+00:00")
    assert q.startswith("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT id FROM audit_log")
    assert "event_ts < '2026-02-01T00:00:00+00:00'" in q
    assert q.endswith("ORDER BY event_ts DESC, id DESC LIMIT 50")
    m = cs.build_query("action = 'x'", materialized=True)
    assert "WITH m AS MATERIALIZED" in m and "event_ts <" not in m


def test_cursor_literal_is_90_percent_deep_in_desc_order() -> None:
    assert cs.cursor_literal(0.9).startswith("2026-02-06")


def test_generate_rows_sql_chained_vs_bulk() -> None:
    bulk = cs.generate_rows_sql(0, 9, 10, chained=False)
    chained = cs.generate_rows_sql(0, 9, 10, chained=True)
    assert "entry_hash" in bulk and "entry_hash" not in chained
    assert "generate_series(0::bigint, 9::bigint)" in chained
    assert "192.0.2." in bulk  # RFC 5737 documentation range only


def test_seed_users_sql_is_synthetic() -> None:
    sql = cs.seed_users_sql(3)
    assert "generate_series(0, 2)" in sql and "example.invalid" in sql


def test_summarise_verdict_and_report_writer(tmp_path: Path) -> None:
    s = cs.summarise([1.0, 2.0, 500.0])
    assert s["p50_ms"] == 2.0 and s["p99_ms"] == 500.0 and s["n"] == 3.0
    assert cs.verdict(s["p95_ms"], cs.COMMON_P95_BUDGET_MS) == "MISS"
    assert cs.verdict(399.0, cs.COMMON_P95_BUDGET_MS) == "meets"
    out = cs.write_report(tmp_path / "r" / "x.json", {"b": 1, "a": 2})
    assert json.loads(out.read_text(encoding="utf-8")) == {"a": 2, "b": 1}


def test_candidates_cover_existing_and_recommended_sets() -> None:
    assert cs.CANDIDATES["a_existing"] == ()
    assert len(cs.CANDIDATES["f_recommended"]) == 2
    assert cs.GIN_DDL.startswith("CREATE INDEX CONCURRENTLY")
    assert len(cs.FILTERS) == 11
