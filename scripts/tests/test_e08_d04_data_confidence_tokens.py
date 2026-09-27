"""pytest for E08-D04 (data-confidence tokens, states and badges).

Verifies the Gherkin acceptance criteria that are testable from the token JSON
and catalogue docs alone (contribution scope — no React components exist yet):

  1. Every one of the 8 data-confidence states has a text + indicator token
     defined identically across all 3 themes (dark/light/high-contrast),
     resolving through the same verifier used by E05-D01 (contrast proof).
  2. `stale` is the only state with a dedicated `.surface` token (per the
     design decision that the surface tint is the exception, not the rule).
  3. The component catalogue documents CMP-239 FreshnessMarker and its
     composition rule with CMP-227 EstimatedBadge (never merged into one
     chip) — a structural doc check, since no component exists to unit test.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_SCRIPT = REPO_ROOT / "packages" / "ui" / "tokens" / "tests" / "verify_tokens.py"
CATALOGUE = REPO_ROOT / "docs" / "plan" / "15-component-catalogue.md"
BRIEF = REPO_ROOT / "docs" / "plan" / "16-design-system-brief.md"

STATES = (
    "live", "stale", "reconnecting", "disconnected",
    "resyncing", "gapped", "backfilling", "delisted",
)


def test_verify_tokens_passes_including_data_confidence_checks() -> None:
    result = subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "OK:" in result.stdout


def test_all_eight_states_have_text_and_indicator_tokens_in_dark_theme() -> None:
    import json

    tokens = json.loads(
        (REPO_ROOT / "packages" / "ui" / "tokens" / "semantic-dark.tokens.json").read_text(
            encoding="utf-8"
        )
    )
    for state in STATES:
        assert f"color.data-confidence.{state}.text" in tokens, state
        assert f"color.data-confidence.{state}.indicator" in tokens, state


def test_only_stale_defines_a_surface_token() -> None:
    import json

    tokens = json.loads(
        (REPO_ROOT / "packages" / "ui" / "tokens" / "semantic-dark.tokens.json").read_text(
            encoding="utf-8"
        )
    )
    surface_states = [
        s for s in STATES if f"color.data-confidence.{s}.surface" in tokens
    ]
    assert surface_states == ["stale"], surface_states


def test_catalogue_documents_freshness_marker_and_composition_rule() -> None:
    text = CATALOGUE.read_text(encoding="utf-8")
    assert "CMP-239 FreshnessMarker" in text
    assert "never overlapping" not in text  # guard against a stale draft phrase
    assert "never overlap" in text or "never touching or overlapping" in text
    assert "CMP-227" in text and "CMP-239" in text


def test_brief_documents_data_confidence_token_group() -> None:
    text = BRIEF.read_text(encoding="utf-8")
    assert "color.data-confidence" in text
    assert "2.1a" in text
