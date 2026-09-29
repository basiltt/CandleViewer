"""Unit tests for scripts/validate-backlog.py (GOV-004).

Module filename has a hyphen (matching the CLI entry point name), so it is
loaded via importlib rather than a plain `import`.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "validate_backlog", SCRIPTS_DIR / "validate-backlog.py"
)
validate_backlog = importlib.util.module_from_spec(_SPEC)
sys.modules["validate_backlog"] = validate_backlog
_SPEC.loader.exec_module(validate_backlog)


SCHEMA_SRC = SCRIPTS_DIR.parent / "docs" / "plan" / "backlog" / "schema"


def _copy_schemas(repo_root: Path) -> None:
    dest = repo_root / "docs" / "plan" / "backlog" / "schema"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("ticket.schema.json", "backlog-file.schema.json"):
        (dest / name).write_text((SCHEMA_SRC / name).read_text(encoding="utf-8"), encoding="utf-8")


def _write_docs(repo_root: Path) -> None:
    plan = repo_root / "docs" / "plan"
    plan.mkdir(parents=True, exist_ok=True)
    (plan / "01-sdlc-and-branching.md").write_text(
        "**`type/*`**:\n"
        "`type/epic`, `type/story`, `type/task`, `type/spike`, `type/bug`, `type/chore`\n\n"
        "**`area/*`**:\n"
        "`area/docs`\n\n"
        "**`priority/*`**:\n"
        "`priority/p0-critical`, `priority/p1-high`, `priority/p2-normal`, `priority/p3-low`\n",
        encoding="utf-8",
    )
    (plan / "30-release-roadmap.md").write_text(
        "| S01 | 2026-09-25 | 2026-10-01 | R0 |\n"
        "| S02 | 2026-10-02 | 2026-10-08 | R0 |\n"
        "| S03 | 2026-10-09 | 2026-10-15 | R0 |\n"
        "| S04 | 2026-10-16 | 2026-10-22 | R0 |\n",
        encoding="utf-8",
    )


BASE_TICKET = {
    "labels": ["type/task", "area/docs", "priority/p1-high"],
    "component": "docs",
    "phase": "P0 Foundations",
    "priority": "P1 High",
    "perspective": "Development",
    "risk": "None",
    "milestone": "R0 Foundations",
    "body": (
        "## Context\nc\n## Scope / Deliverables\nc\n## Out of scope\nc\n"
        "## Acceptance criteria\nc\n## Technical notes / design\nc\n## Test plan\nc\n"
        "## Security notes\nc\n## Accessibility notes\nc\n## Performance notes\nc\n"
        "## Observability\nc\n## Definition of Done\nc\n## Dependencies\nc\n"
        "## Branch\nc\n## References\nc\n"
    ),
}


def _ticket(**overrides) -> dict:
    t = dict(BASE_TICKET)
    t.update(overrides)
    return t


def _epic(key: str, estimate: int = 3) -> dict:
    return _ticket(
        key=key, kind="Epic", title=f"Epic {key}", parent=None,
        blocked_by=[], sprint="Sprint 01", estimate=estimate,
    )


def _write_backlog_file(repo_root: Path, filename: str, tickets: list[dict]) -> None:
    backlog = repo_root / "docs" / "plan" / "backlog"
    backlog.mkdir(parents=True, exist_ok=True)
    (backlog / filename).write_text(json.dumps(tickets, ensure_ascii=False), encoding="utf-8")


def _setup(tmp_path: Path) -> Path:
    _copy_schemas(tmp_path)
    _write_docs(tmp_path)
    return tmp_path


def test_valid_backlog_exits_zero(tmp_path: Path) -> None:
    _setup(tmp_path)
    epic = _epic("E01", estimate=1)
    child = _ticket(
        key="E01-T01", kind="Task", title="Do the thing", parent="E01",
        blocked_by=[], sprint="Sprint 01", estimate=1,
    )
    _write_backlog_file(tmp_path, "E01.json", [epic, child])

    exit_code = validate_backlog.main(["--repo-root", str(tmp_path), "--quiet"])
    assert exit_code == 0


# Regression: encodes E01-Q01 case 4.1 (originating case id) -- a ticket missing a
# required field must be rejected with a field-pointer error.
def test_missing_required_field_rejected_with_pointer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(tmp_path)
    epic = _epic("E02", estimate=1)
    child = _ticket(
        key="E02-T01", kind="Task", title="Do the thing", parent="E02",
        blocked_by=[], sprint="Sprint 01", estimate=1,
    )
    del child["perspective"]
    _write_backlog_file(tmp_path, "E02.json", [epic, child])

    exit_code = validate_backlog.main(["--repo-root", str(tmp_path)])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "GOV-004" in out
    assert "E02.json#1" in out
    assert "perspective" in out.lower()


# Regression: encodes E01-Q01 case 4.2 (originating case id) -- a blocked_by
# pointing at a nonexistent key must be rejected.
def test_dangling_dependency_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(tmp_path)
    epic = _epic("E03", estimate=1)
    child = _ticket(
        key="E03-T01", kind="Task", title="Do the thing", parent="E03",
        blocked_by=["E99-S42"], sprint="Sprint 01", estimate=1,
    )
    _write_backlog_file(tmp_path, "E03.json", [epic, child])

    exit_code = validate_backlog.main(["--repo-root", str(tmp_path)])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "unresolvable dependency" in out
    assert "E99-S42" in out


# Regression: encodes E01-Q01 case 4.3 (originating case id) -- a dependency cycle
# must be rejected with the cycle path shown.
def test_dependency_cycle_reported_with_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(tmp_path)
    epic = _epic("E04", estimate=2)
    t1 = _ticket(
        key="E04-T01", kind="Task", title="First", parent="E04",
        blocked_by=["E04-T02"], sprint="Sprint 01", estimate=1,
    )
    t2 = _ticket(
        key="E04-T02", kind="Task", title="Second", parent="E04",
        blocked_by=["E04-T01"], sprint="Sprint 01", estimate=1,
    )
    _write_backlog_file(tmp_path, "E04.json", [epic, t1, t2])

    exit_code = validate_backlog.main(["--repo-root", str(tmp_path)])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "dependency cycle" in out
    assert "E04-T01" in out and "E04-T02" in out


# Regression: encodes E01-Q01 case 4.5 (originating case id) -- a design ticket must
# be scheduled ahead of its consumer per the design-ahead rule.
def test_design_ahead_rule_enforced(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(tmp_path)
    epic = _epic("E05", estimate=2)
    design = _ticket(
        key="E05-D01", kind="Chore", title="Design the screen", parent="E05",
        blocked_by=[], sprint="Sprint 04", estimate=1,
    )
    story = _ticket(
        key="E05-S01", kind="Story", title="Build the screen", parent="E05",
        blocked_by=["E05-D01"], sprint="Sprint 05", estimate=1,
    )
    _write_backlog_file(tmp_path, "E05.json", [epic, design, story])

    exit_code = validate_backlog.main(["--repo-root", str(tmp_path)])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "design-ahead violation" in out
    assert "E05-S01" in out and "E05-D01" in out


# Regression: encodes E01-Q01 case 4.4 (originating case id) -- an out-of-Fibonacci
# estimate on a Story must be rejected.
def test_oversized_story_estimate_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(tmp_path)
    epic = _epic("E06", estimate=13)
    story = _ticket(
        key="E06-S01", kind="Story", title="Too big", parent="E06",
        blocked_by=[], sprint="Sprint 01", estimate=13,
    )
    _write_backlog_file(tmp_path, "E06.json", [epic, story])

    exit_code = validate_backlog.main(["--repo-root", str(tmp_path)])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "GOV-004" in out
    assert "estimate" in out.lower()


# Regression: encodes E01-Q01 case 4.6 (originating case id) -- malformed JSON must
# exit 2 (internal error), distinct from a schema-violation exit 1.
def test_malformed_json_exits_two(tmp_path: Path) -> None:
    _setup(tmp_path)
    backlog = tmp_path / "docs" / "plan" / "backlog"
    backlog.mkdir(parents=True, exist_ok=True)
    (backlog / "E07.json").write_text("{not valid json", encoding="utf-8")

    exit_code = validate_backlog.main(["--repo-root", str(tmp_path)])
    assert exit_code == 2


def test_json_output_is_structured(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _setup(tmp_path)
    epic = _epic("E08", estimate=1)
    child = _ticket(
        key="E08-T01", kind="Task", title="Do the thing", parent="E08",
        blocked_by=[], sprint="Sprint 01", estimate=1,
    )
    _write_backlog_file(tmp_path, "E08.json", [epic, child])

    exit_code = validate_backlog.main(["--repo-root", str(tmp_path), "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert exit_code == 0
    assert payload["files"] == 1
    assert payload["tickets"] == 2
    assert payload["errors"] == []


def test_summary_mode_prints_epic_rollup(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _setup(tmp_path)
    epic = _epic("E09", estimate=1)
    child = _ticket(
        key="E09-T01", kind="Task", title="Do the thing", parent="E09",
        blocked_by=[], sprint="Sprint 01", estimate=1,
    )
    _write_backlog_file(tmp_path, "E09.json", [epic, child])

    validate_backlog.main(["--repo-root", str(tmp_path), "--summary", "--quiet"])
    out = capsys.readouterr().out

    assert "E09" in out
    assert "1" in out
