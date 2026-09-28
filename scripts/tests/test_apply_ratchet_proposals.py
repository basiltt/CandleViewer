"""Unit tests for tools/ci/apply_ratchet_proposals.py (E03-T04)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.apply_ratchet_proposals import apply_proposals, main


def _baselines(tmp_path: Path, packages: dict[str, dict[str, object]]) -> Path:
    path = tmp_path / "coverage-baselines.json"
    path.write_text(
        json.dumps({"tolerance_pp": 0.5, "packages": packages}), encoding="utf-8"
    )
    return path


def test_apply_proposals_raises_baseline(tmp_path: Path) -> None:
    baselines = _baselines(
        tmp_path,
        {
            "packages/protocol": {
                "floor": 85.0,
                "baseline": 88.0,
                "artifact": "a",
                "report_format": "lcov",
            }
        },
    )
    changes = apply_proposals({"packages/protocol": 89.4}, baselines)
    assert changes == ["packages/protocol: 88.0% -> 89.4%"]

    updated = json.loads(baselines.read_text(encoding="utf-8"))
    assert updated["packages"]["packages/protocol"]["baseline"] == 89.4


def test_apply_proposals_ignores_lower_or_equal_values(tmp_path: Path) -> None:
    baselines = _baselines(
        tmp_path,
        {
            "packages/ui": {
                "floor": 80.0,
                "baseline": 91.0,
                "artifact": "a",
                "report_format": "lcov",
            }
        },
    )
    changes = apply_proposals({"packages/ui": 90.0}, baselines)
    assert changes == []
    updated = json.loads(baselines.read_text(encoding="utf-8"))
    assert updated["packages"]["packages/ui"]["baseline"] == 91.0


def test_apply_proposals_ignores_unknown_package(tmp_path: Path) -> None:
    baselines = _baselines(tmp_path, {})
    assert apply_proposals({"does/not-exist": 99.0}, baselines) == []


def test_main_no_proposals_file_is_a_noop(tmp_path: Path, monkeypatch: object) -> None:
    baselines = _baselines(tmp_path, {})
    rc = main([str(tmp_path / "missing.json"), str(baselines)])
    assert rc == 0


def test_main_applies_and_writes_github_output(
    tmp_path: Path, monkeypatch: object
) -> None:
    baselines = _baselines(
        tmp_path,
        {
            "packages/protocol": {
                "floor": 85.0,
                "baseline": 88.0,
                "artifact": "a",
                "report_format": "lcov",
            }
        },
    )
    proposals = tmp_path / "proposals.json"
    proposals.write_text(json.dumps({"packages/protocol": 89.4}), encoding="utf-8")
    gh_output = tmp_path / "gh_output.txt"
    monkeypatch.setattr(
        "os.environ", {**__import__("os").environ, "GITHUB_OUTPUT": str(gh_output)}
    )

    rc = main([str(proposals), str(baselines)])
    assert rc == 0
    content = gh_output.read_text(encoding="utf-8")
    assert "changed=true" in content
    assert "packages/protocol" in content


def test_main_wrong_arg_count_returns_two() -> None:
    assert main([]) == 2
