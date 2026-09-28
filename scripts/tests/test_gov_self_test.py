"""Unit tests for scripts/gov_self_test.py (the governance job's canary
self-test mode, E01-Q02 acceptance criterion "The job proves it can still
fail").
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import gov_self_test


def test_all_broken_fixtures_produce_nonzero_exit() -> None:
    """Every registered checker must fail against its own known-broken
    fixture; this is the exact property the governance job's --self-test
    step relies on."""
    for code, builder in gov_self_test.BROKEN_FIXTURE_BUILDERS.items():
        import tempfile

        with tempfile.TemporaryDirectory(prefix=f"test-gov-self-test-{code}-") as tmp:
            root = Path(tmp)
            module, argv = builder(root)
            exit_code = module.main(argv)
            assert exit_code != 0, f"{code} checker exited 0 against a broken fixture"


def test_manifest_matches_real_governance_workflow() -> None:
    """The manifest in this file must stay in sync with the real
    .github/workflows/governance.yml — this is what catches "a checker
    invocation was silently deleted from the workflow"."""
    errors = gov_self_test.check_manifest_matches_workflow(gov_self_test.GOVERNANCE_WORKFLOW)
    assert errors == []


def test_manifest_flags_a_missing_workflow_step(tmp_path: Path) -> None:
    """Mutation check: if governance.yml no longer contains a step for a
    manifest entry, the reconciliation must report it."""
    broken_workflow = tmp_path / "governance.yml"
    broken_workflow.write_text(
        "jobs:\n  governance:\n    steps:\n      - name: Some unrelated step\n",
        encoding="utf-8",
    )
    errors = gov_self_test.check_manifest_matches_workflow(broken_workflow)
    assert any("GOV-002" in e for e in errors)


def test_manifest_flags_missing_workflow_file(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.yml"
    errors = gov_self_test.check_manifest_matches_workflow(missing)
    assert errors and "not found" in errors[0]


def test_run_self_test_returns_zero_when_everything_fails_correctly() -> None:
    assert gov_self_test.run_self_test() == 0


def test_main_returns_zero_on_clean_repo_state() -> None:
    assert gov_self_test.main([]) == 0
