"""GOV-008 — every epic ticket appears in its threat model's ticket map."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_threat_model_ticket_map as mod  # path shim above, same as sibling tests


def _repo(tmp_path: Path, keys: list[str], model: str, name: str = "E99-x.md") -> Path:
    (tmp_path / "docs/plan/backlog").mkdir(parents=True)
    (tmp_path / "docs/security/threat-models").mkdir(parents=True)
    tickets = [{"key": k} for k in keys] + [{"key": "E99"}]
    (tmp_path / "docs/plan/backlog/all-tickets.json").write_text(
        json.dumps(tickets), encoding="utf-8"
    )
    (tmp_path / "docs/security/threat-models" / name).write_text(
        model, encoding="utf-8"
    )
    return tmp_path


def test_threat_model_complete_passes(tmp_path: Path) -> None:
    root = _repo(
        tmp_path, ["E99-S01", "E99-S02"], "## 11. Ticket map\nE99-S01 E99-S02\n"
    )
    assert mod.check(root) == []


def test_threat_model_missing_key_named(tmp_path: Path) -> None:
    root = _repo(tmp_path, ["E99-S01", "E99-S02"], "## 11. Ticket map\nE99-S01\n")
    problems = mod.check(root)
    assert (
        len(problems) == 1 and "E99-S02" in problems[0] and "E99-S01" not in problems[0]
    )


def test_threat_model_grouped_row_counts(tmp_path: Path) -> None:
    root = _repo(tmp_path, ["E99-D01", "E99-D02"], "## 11. Ticket map\nE99-D01 / D02\n")
    assert mod.check(root) == []


def test_threat_model_without_map_section_skipped(tmp_path: Path) -> None:
    assert mod.check(_repo(tmp_path, ["E99-S01"], "## Notes\nnothing\n")) == []


def test_threat_model_epic_key_not_required(tmp_path: Path) -> None:
    assert mod.check(_repo(tmp_path, [], "## Ticket map\n")) == []


def test_threat_model_prose_mention_does_not_count(tmp_path: Path) -> None:
    model = "Intro mentions E99-S02.\n\n## 11. Ticket map\nE99-S01\n\n## 12. Other\nE99-S02\n"
    problems = mod.check(_repo(tmp_path, ["E99-S01", "E99-S02"], model))
    assert len(problems) == 1 and "E99-S02" in problems[0]


def test_threat_model_retired_ticket_excluded(tmp_path: Path) -> None:
    root = _repo(tmp_path, ["E99-S01", "E99-S02"], "## 11. Ticket map\nE99-S01\n")
    path = root / "docs/plan/backlog/all-tickets.json"
    path.write_text(
        json.dumps([{"key": "E99-S01"}, {"key": "E99-S02", "labels": ["retired"]}]),
        encoding="utf-8",
    )
    assert mod.check(root) == []
