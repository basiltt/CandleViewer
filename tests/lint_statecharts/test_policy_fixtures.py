"""E50-T16: CV-LINT-POLICY fixtures derived from every committed chart.

For each committed machine chart, mutated copies (key removed / wrong value)
must make CV-LINT-POLICY fail naming the chart; unmutated charts must pass.
Charts are discovered by glob, so B1/B8 are covered automatically once
committed. Keys the lint does not check yet (actionErrorPolicy,
guardErrorPolicy, strictTargets) are asserted on the committed charts only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import lint_statecharts as lint

MACHINES_DIR = REPO_ROOT / lint.DEFAULT_MACHINES_DIR
CHARTS = sorted(MACHINES_DIR.glob("*.machine.json"))
IDS = [p.name for p in CHARTS]

# Keys CV-LINT-POLICY enforces today, with a wrong value for each.
LINTED_KEYS: dict[str, Any] = {
    "strictConfig": False,
    "onUnhandled": "drop",
    "maxIterations": 0,
}
# Mandatory per catalogue 1.3c but NOT checked by the lint (finding, see PR).
UNLINTED_KEYS: dict[str, Any] = {
    "actionErrorPolicy": "rollback",
    "guardErrorPolicy": "raise",
    "strictTargets": True,
}


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _write(tmp_path: Path, name: str, chart: dict[str, Any]) -> Path:
    out = tmp_path / name
    out.write_text(json.dumps(chart), encoding="utf-8")
    return out


def _policy(path: Path) -> list[lint.Finding]:
    return [f for f in lint.lint_machine_file(path) if f.rule == "CV-LINT-POLICY"]


def test_charts_discovered() -> None:
    assert CHARTS, "no committed charts found"


@pytest.mark.parametrize("chart_path", CHARTS, ids=IDS)
def test_policy_green_on_committed_chart(chart_path: Path) -> None:
    assert _policy(chart_path) == []


@pytest.mark.parametrize("chart_path", CHARTS, ids=IDS)
@pytest.mark.parametrize("key", sorted(LINTED_KEYS))
def test_policy_fails_naming_chart_when_key_missing(
    chart_path: Path, key: str, tmp_path: Path
) -> None:
    chart = _load(chart_path)
    del chart[key]
    fixture = _write(tmp_path, chart_path.name, chart)
    findings = _policy(fixture)
    assert findings, f"{key} removed from {chart_path.name} but POLICY stayed green"
    assert any(key in f.message for f in findings)
    assert all(chart_path.name in f.format() for f in findings)


@pytest.mark.parametrize("chart_path", CHARTS, ids=IDS)
@pytest.mark.parametrize("key", sorted(LINTED_KEYS))
def test_policy_fails_naming_chart_on_wrong_value(
    chart_path: Path, key: str, tmp_path: Path
) -> None:
    chart = _load(chart_path)
    chart[key] = LINTED_KEYS[key]
    fixture = _write(tmp_path, chart_path.name, chart)
    findings = _policy(fixture)
    assert any(key in f.message for f in findings)
    assert all(chart_path.name in f.format() for f in findings)


@pytest.mark.parametrize("chart_path", CHARTS, ids=IDS)
@pytest.mark.parametrize("key", sorted(UNLINTED_KEYS))
def test_committed_chart_carries_unlinted_mandatory_key(chart_path: Path, key: str) -> None:
    assert _load(chart_path).get(key) == UNLINTED_KEYS[key]
