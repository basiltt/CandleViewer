"""Unit tests for scripts/check_branch_protection_drift.py (GOV-005)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from apply_branch_protection import Diff
from check_branch_protection_drift import render_findings


# Regression: encodes E01-Q01 case 1.10 (originating case id) -- drift between
# live and desired branch-protection state must be detected and reported.
def test_render_findings_text_reports_all_kinds() -> None:
    diff = Diff(added={"a": 1}, removed={"b": 2}, changed={"c": (3, 4)})
    text = render_findings(diff, as_json=False)
    assert "GOV-005" in text
    assert "+ a" in text
    assert "- b" in text
    assert "~ c" in text


def test_render_findings_json_shapes_each_kind() -> None:
    diff = Diff(added={"a": 1}, removed={"b": 2}, changed={"c": (3, 4)})
    payload = json.loads(render_findings(diff, as_json=True))
    kinds = {item["kind"] for item in payload}
    assert kinds == {"missing_on_live", "unexpected_on_live", "changed"}
    for item in payload:
        assert item["code"] == "GOV-005"


def test_render_findings_json_empty_diff_is_empty_list() -> None:
    diff = Diff(added={}, removed={}, changed={})
    payload = json.loads(render_findings(diff, as_json=True))
    assert payload == []
