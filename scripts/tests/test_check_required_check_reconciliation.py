"""Unit tests for scripts/check_required_check_reconciliation.py (GOV-005)."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import check_required_check_reconciliation as recon

FIXTURE_CONSTITUTION = """\
## 9. Quality gates (required CI checks)

| # | Check name | Gate |
|---|---|---|
| 1 | `lint` | ESLint etc |
| 2 | `typecheck` | tsc etc |
| 3 | `unit-backend` | pytest |

## 10. Something else
"""


def _write_constitution(tmp_path: Path) -> Path:
    path = tmp_path / "CONSTITUTION.md"
    path.write_text(FIXTURE_CONSTITUTION, encoding="utf-8")
    return path


def test_load_constitution_check_names_extracts_all_rows(tmp_path: Path) -> None:
    path = _write_constitution(tmp_path)
    names = recon.load_constitution_check_names(str(path))
    assert names == ["lint", "typecheck", "unit-backend"]


def test_load_constitution_check_names_missing_table_raises(tmp_path: Path) -> None:
    path = tmp_path / "CONSTITUTION.md"
    path.write_text("no table here", encoding="utf-8")
    try:
        recon.load_constitution_check_names(str(path))
        assert False, "expected ReconciliationError"
    except recon.ReconciliationError:
        pass


def test_reconcile_clean_when_fully_covered() -> None:
    desired = {
        "required_status_checks": {"contexts": ["lint"]},
        "x-pending-contexts": ["typecheck", "unit-backend"],
    }
    errors = recon.reconcile(desired, ["lint", "typecheck", "unit-backend"], set())
    assert errors == []


def test_reconcile_allows_bootstrap_only_governance_context() -> None:
    desired = {
        "required_status_checks": {"contexts": ["governance"]},
        "x-pending-contexts": ["lint"],
    }
    errors = recon.reconcile(desired, ["lint"], set())
    assert errors == []


def test_reconcile_flags_unknown_context_name() -> None:
    desired = {
        "required_status_checks": {"contexts": ["not-a-real-check"]},
        "x-pending-contexts": [],
    }
    errors = recon.reconcile(desired, ["lint"], set())
    assert any("not-a-real-check" in e for e in errors)


def test_reconcile_flags_missing_check_from_both_lists() -> None:
    desired = {
        "required_status_checks": {"contexts": ["lint"]},
        "x-pending-contexts": [],
    }
    errors = recon.reconcile(desired, ["lint", "typecheck"], set())
    assert any("typecheck" in e and "missing" in e for e in errors)


def test_reconcile_flags_name_in_both_contexts_and_pending() -> None:
    desired = {
        "required_status_checks": {"contexts": ["lint"]},
        "x-pending-contexts": ["lint"],
    }
    errors = recon.reconcile(desired, ["lint"], set())
    assert any("both" in e for e in errors)


def test_reconcile_flags_required_context_without_workflow_job() -> None:
    desired = {
        "required_status_checks": {"contexts": ["lint"]},
        "x-pending-contexts": [],
    }
    errors = recon.reconcile(desired, ["lint"], workflow_job_names={"typecheck"})
    assert any("no job named 'lint'" in e for e in errors)


def test_reconcile_skips_workflow_check_when_no_workflows_exist() -> None:
    desired = {
        "required_status_checks": {"contexts": ["lint"]},
        "x-pending-contexts": [],
    }
    errors = recon.reconcile(desired, ["lint"], workflow_job_names=set())
    assert errors == []


def test_load_workflow_job_names_extracts_top_level_jobs(tmp_path: Path) -> None:
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    (wf_dir / "ci.yml").write_text(
        "name: CI\non: [pull_request]\njobs:\n  lint:\n    runs-on: ubuntu-latest\n"
        "  typecheck:\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    names = recon.load_workflow_job_names(str(wf_dir / "*.yml"))
    assert names == {"lint", "typecheck"}


def test_load_workflow_job_names_empty_when_no_files(tmp_path: Path) -> None:
    names = recon.load_workflow_job_names(str(tmp_path / "*.yml"))
    assert names == set()
