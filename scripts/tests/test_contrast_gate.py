"""Tests for tools/contrast/generate.mjs (E05-T05).

Exercises the pure Node modules (color-math.mjs, pairs.mjs, generate.mjs's
exported check functions) through `node --input-type=module`, mirroring the
shell-to-node pattern used for tools/ci/turbo-affected-packages.mjs
(test_turbo_affected_packages.py). No network; deterministic fixed colours.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COLOR_MATH = ROOT / "tools" / "contrast" / "color-math.mjs"
GENERATE = ROOT / "tools" / "contrast" / "generate.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _run_node(js: str) -> str:
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", js],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    )
    return proc.stdout.strip()


def test_known_good_pair_matches_expected_ratio_to_two_decimals() -> None:
    js = textwrap.dedent(
        f"""
        import {{ contrastRatio }} from '{COLOR_MATH.resolve().as_uri()}';
        console.log(contrastRatio('#E8EAED', '#0B0E11').toFixed(2));
        """
    )
    assert _run_node(js) == "16.06"


def test_known_bad_pair_is_below_text_threshold() -> None:
    js = textwrap.dedent(
        f"""
        import {{ contrastRatio }} from '{COLOR_MATH.resolve().as_uri()}';
        console.log(contrastRatio('#777777', '#666666') < 4.5);
        """
    )
    assert _run_node(js) == "true"


def test_deuteranopia_confusable_red_green_pair_collapses_under_jnd_floor() -> None:
    js = textwrap.dedent(
        f"""
        import {{ simulateCvd, deltaE76, CVD_JND_FLOOR }} from '{COLOR_MATH.resolve().as_uri()}';
        const red = simulateCvd('#D35400', 'deuteranopia');
        const green = simulateCvd('#7F8C00', 'deuteranopia');
        console.log(JSON.stringify({{ de: deltaE76(red, green), floor: CVD_JND_FLOOR }}));
        """
    )
    result = json.loads(_run_node(js))
    assert result["de"] < result["floor"]


def test_check_pairs_flags_below_threshold_pair_as_a11y_c001() -> None:
    js = textwrap.dedent(
        f"""
        import {{ checkPairs }} from '{GENERATE.resolve().as_uri()}';
        const theme = {{
          'color.text.secondary': {{ $value: '#4A4E55' }},
          'color.surface.app': {{ $value: '#0B0E11' }},
        }};
        const {{ findings }} = checkPairs('dark', theme, new Set());
        console.log(JSON.stringify(findings.map((f) => f.code)));
        """
    )
    codes = json.loads(_run_node(js))
    assert "A11Y-C001" in codes


def test_check_pairs_below_threshold_pair_marked_exempt_produces_no_finding() -> None:
    js = textwrap.dedent(
        f"""
        import {{ checkPairs }} from '{GENERATE.resolve().as_uri()}';
        const theme = {{
          'color.text.secondary': {{ $value: '#4A4E55' }},
          'color.surface.app': {{ $value: '#0B0E11' }},
        }};
        const exempt = new Set(['dark:color.text.secondary on color.surface.app']);
        const {{ findings, rows }} = checkPairs('dark', theme, exempt);
        console.log(JSON.stringify({{ findings, exemptRow: rows.find((r) => r.exempt) !== undefined }}));
        """
    )
    result = json.loads(_run_node(js))
    assert result["findings"] == []
    assert result["exemptRow"] is True


def test_exemption_entry_without_reason_or_owner_is_rejected() -> None:
    js = textwrap.dedent(
        """
        const entries = [{ token: 'color.foo' }, { pair: 'x on y', reason: 'r', owner: 'o' }];
        const invalid = entries.filter(
          (e) => !e.reason || !e.owner || (!e.token && !e.pair),
        );
        console.log(invalid.length);
        """
    )
    assert _run_node(js) == "1"


def test_undeclared_token_without_pair_or_exemption_fails_loudly() -> None:
    js = textwrap.dedent(
        f"""
        import {{ checkUndeclaredTokens }} from '{GENERATE.resolve().as_uri()}';
        const theme = {{ 'color.brand.new-mystery-token': {{ $value: '#FF00FF' }} }};
        const findings = checkUndeclaredTokens('dark', theme, new Set(), new Set());
        console.log(JSON.stringify(findings.map((f) => f.code)));
        """
    )
    assert json.loads(_run_node(js)) == ["A11Y-C002"]


def test_undeclared_token_covered_by_exemption_does_not_fail() -> None:
    js = textwrap.dedent(
        f"""
        import {{ checkUndeclaredTokens }} from '{GENERATE.resolve().as_uri()}';
        const theme = {{ 'color.brand.new-mystery-token': {{ $value: '#FF00FF' }} }};
        const exempt = new Set(['color.brand.new-mystery-token']);
        const findings = checkUndeclaredTokens('dark', theme, new Set(), exempt);
        console.log(JSON.stringify(findings));
        """
    )
    assert json.loads(_run_node(js)) == []


def test_cvd_check_flags_collapsing_adjacent_heatmap_stops_with_both_names() -> None:
    js = textwrap.dedent(
        f"""
        import {{ checkCvd }} from '{GENERATE.resolve().as_uri()}';
        // Two near-identical bid ramp stops: real registry pair names so
        // HEATMAP_ADJACENT_PAIRS resolves them, but values collapse under CVD.
        const theme = {{
          'color.heatmap.bid.1': {{ $value: '#B23A3A' }},
          'color.heatmap.bid.2': {{ $value: '#B33B3B' }},
        }};
        const {{ findings }} = checkCvd('dark', theme, new Set());
        console.log(JSON.stringify(findings.map((f) => ({{ code: f.code, pair: f.pair }}))));
        """
    )
    findings = json.loads(_run_node(js))
    assert any(f["code"] == "A11Y-C003" for f in findings)
    assert any("color.heatmap.bid.1" in f["pair"] and "color.heatmap.bid.2" in f["pair"] for f in findings)


def test_real_repo_token_set_generator_run_exits_nonzero_only_on_unexempted_findings() -> None:
    """Integration smoke test: running the real generator against this repo's
    actual, committed exemptions.json must produce zero *unexempted* findings
    (the gate as configured today is green)."""
    proc = subprocess.run(
        ["node", str(GENERATE)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    matrix_path = ROOT / "packages" / "ui" / "build" / "reports" / "contrast-matrix.json"
    assert matrix_path.exists()
    report = json.loads(matrix_path.read_text(encoding="utf-8"))
    assert report["findings"] == []
