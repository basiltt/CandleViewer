"""Unit tests for `benchmarks.questdb_hot_tier.compare`.

No network, no sleeps, no live QuestDB — pure JSON-diff logic.
"""

from __future__ import annotations

from typing import Any

from benchmarks.questdb_hot_tier.compare import compare_shapes, format_table


def _baseline() -> dict[str, Any]:
    return {
        "shapes": {
            "A": {"questdb": {"p95_ms": 4.147}},
            "F": {"questdb": {"p95_ms": 4.306}},
        }
    }


def test_compare_shapes_within_tolerance_marks_ok() -> None:
    candidate = {"shapes": {"A": {"p95_ms": 4.2}, "F": {"p95_ms": 4.31}}}

    report = compare_shapes(_baseline(), candidate, tolerance_pct=25.0)

    assert report["all_ok"] is True
    assert report["regressed"] == []
    assert report["missing"] == []
    assert report["rows"]["A"]["verdict"] == "ok"


def test_compare_shapes_regression_detected_beyond_tolerance() -> None:
    candidate = {"shapes": {"A": {"p95_ms": 10.0}, "F": {"p95_ms": 4.31}}}

    report = compare_shapes(_baseline(), candidate, tolerance_pct=25.0)

    assert report["all_ok"] is False
    assert "A" in report["regressed"]
    assert "F" not in report["regressed"]
    assert report["rows"]["A"]["verdict"] == "regressed"
    assert report["rows"]["A"]["delta_pct"] > 25.0


def test_compare_shapes_missing_shape_reported_not_raised() -> None:
    candidate = {"shapes": {"A": {"p95_ms": 4.2}}}  # "F" absent

    report = compare_shapes(_baseline(), candidate, tolerance_pct=25.0)

    assert report["all_ok"] is False
    assert report["missing"] == ["F"]
    assert report["rows"]["F"]["verdict"] == "missing"
    assert report["rows"]["F"]["candidate_p95_ms"] is None


def test_compare_shapes_faster_candidate_is_ok_not_regressed() -> None:
    candidate = {"shapes": {"A": {"p95_ms": 1.0}, "F": {"p95_ms": 1.0}}}

    report = compare_shapes(_baseline(), candidate, tolerance_pct=25.0)

    assert report["all_ok"] is True
    assert report["regressed"] == []


def test_format_table_includes_every_shape_row() -> None:
    candidate = {"shapes": {"A": {"p95_ms": 4.2}, "F": {"p95_ms": 4.31}}}
    report = compare_shapes(_baseline(), candidate, tolerance_pct=25.0)

    table = format_table(report)

    assert "A" in table
    assert "F" in table
    assert "verdict" in table
