"""GOV-007 — owned docs carry no tool-injected blocks; turbo opt-out present (#1907)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_owned_docs_untouched as mod  # path shim above, same as sibling tests

MARKER = "<!-- BEGIN:turborepo-agent-rules -->"


def _repo(tmp_path: Path, *, agents: str, turbo: dict[str, object] | None) -> Path:
    (tmp_path / "AGENTS.md").write_text(agents, encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# CLAUDE\n", encoding="utf-8")
    if turbo is not None:
        (tmp_path / "turbo.json").write_text(json.dumps(turbo), encoding="utf-8")
    return tmp_path


def test_check_clean_repo_passes(tmp_path: Path) -> None:
    root = _repo(tmp_path, agents="# AGENTS\n", turbo={"agentGuidance": False})
    assert mod.check(root) == []


def test_check_injected_block_in_agents_md_fails_naming_file(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        agents=f"# AGENTS\n\n{MARKER}\nstuff\n",
        turbo={"agentGuidance": False},
    )
    problems = mod.check(root)
    assert len(problems) == 1
    assert "AGENTS.md" in problems[0] and "turborepo-agent-rules" in problems[0]


def test_check_missing_turbo_opt_out_fails(tmp_path: Path) -> None:
    root = _repo(tmp_path, agents="# AGENTS\n", turbo={"tasks": {}})
    problems = mod.check(root)
    assert problems == ['GOV-007 turbo.json must set "agentGuidance": false (#1907)']


def test_check_opt_out_true_is_a_violation(tmp_path: Path) -> None:
    root = _repo(tmp_path, agents="# AGENTS\n", turbo={"agentGuidance": True})
    assert len(mod.check(root)) == 1


def test_check_no_turbo_json_is_fine(tmp_path: Path) -> None:
    root = _repo(tmp_path, agents="# AGENTS\n", turbo=None)
    assert mod.check(root) == []


@pytest.mark.parametrize("marker", mod.MARKERS)
def test_check_either_marker_is_detected(tmp_path: Path, marker: str) -> None:
    root = _repo(tmp_path, agents=f"x\n{marker}\n", turbo={"agentGuidance": False})
    assert len(mod.check(root)) == 1


def test_real_repo_is_clean() -> None:
    assert mod.check(mod.ROOT) == []
