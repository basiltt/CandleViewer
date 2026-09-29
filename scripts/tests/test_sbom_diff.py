"""Unit tests for tools/ci/sbom_diff.py (SR-135)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.sbom_diff import _component_keys, render_diff

SBOM_A = {
    "components": [
        {"name": "fastapi", "version": "0.115.0"},
        {"name": "pydantic", "version": "2.9.0"},
    ]
}
SBOM_B = {
    "components": [
        {"name": "fastapi", "version": "0.115.0"},
        {"name": "httpx", "version": "0.27.0"},
    ]
}


def test_component_keys_formats_name_at_version() -> None:
    assert _component_keys(SBOM_A) == {"fastapi@0.115.0", "pydantic@2.9.0"}


def test_render_diff_with_no_previous_lists_everything_as_new() -> None:
    out = render_diff(SBOM_A, None)
    assert "No previous" in out
    assert "fastapi@0.115.0" in out
    assert "pydantic@2.9.0" in out


def test_render_diff_reports_added_and_removed() -> None:
    out = render_diff(SBOM_B, SBOM_A)
    assert "Added" in out
    assert "httpx@0.27.0" in out
    assert "Removed" in out
    assert "pydantic@2.9.0" in out
    # unchanged component must not appear in either added/removed list
    assert "+ `fastapi@0.115.0`" not in out
    assert "- `fastapi@0.115.0`" not in out


def test_render_diff_no_changes_reports_no_component_changes() -> None:
    out = render_diff(SBOM_A, SBOM_A)
    assert "No component changes" in out
