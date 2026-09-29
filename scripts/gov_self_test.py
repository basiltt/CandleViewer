#!/usr/bin/env python3
"""E01-Q02 canary/self-test mode for the governance regression pack.

Runs each GOV-00x checker against a deliberately-broken fixture tree bundled
under scripts/tests/fixtures/self_test/ and asserts every checker exits
non-zero against its known-bad fixture. This is the guard named in the
ticket against the worst outcome: a green `governance` check that has
silently stopped checking anything (a checker exiting 0 unconditionally is
indistinguishable from a passing checker in the CI log unless something
actively runs it against input it must reject).

The manifest below (CHECKERS) is compared, in
scripts/tests/test_gov_self_test.py, against the literal script paths
invoked by .github/workflows/governance.yml — so removing a checker
invocation from the workflow without removing it here fails that test
(the "mutation check" named in the ticket's test plan).

Exit codes: 0 every checker correctly failed against its broken fixture
(or --self-test was not requested and there was nothing else to do),
1 at least one checker exited 0 against broken input, 2 internal error
(e.g. a fixture path is missing).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
FIXTURES_ROOT = os.path.join(HERE, "tests", "fixtures", "self_test")


@dataclass(frozen=True)
class CheckerEntry:
    name: str
    script_rel_path: str  # relative to repo root, e.g. "scripts/check_rule_refs.py"
    build_argv: Callable[[], list[str]]

    @property
    def module_file(self) -> str:
        """Basename used to cross-check governance.yml mentions the script."""
        return os.path.basename(self.script_rel_path)


def _repo_root_argv(fixture_dir: str) -> list[str]:
    return ["--repo-root", fixture_dir]


def _reconciliation_argv(fixture_dir: str) -> list[str]:
    return [
        "--desired-state",
        os.path.join(fixture_dir, "branch-protection.json"),
        "--constitution",
        os.path.join(fixture_dir, "CONSTITUTION.md"),
        "--workflows-glob",
        os.path.join(fixture_dir, "workflows", "*.yml"),
    ]


def _markdown_governance_docs_argv(fixture_dir: str) -> list[str]:
    return ["--repo-root", fixture_dir, "--docs", "CONTRIBUTING.md"]


def _bypass_register_argv(fixture_dir: str) -> list[str]:
    return ["--register", os.path.join(fixture_dir, "bypass-register.md")]


CHECKERS: tuple[CheckerEntry, ...] = (
    CheckerEntry(
        "check_rule_refs",
        os.path.join("scripts", "check_rule_refs.py"),
        lambda: _repo_root_argv(os.path.join(FIXTURES_ROOT, "rule_refs_broken")),
    ),
    CheckerEntry(
        "check_sot_duplication",
        os.path.join("scripts", "check_sot_duplication.py"),
        lambda: _repo_root_argv(os.path.join(FIXTURES_ROOT, "sot_broken")),
    ),
    CheckerEntry(
        "check_codeowners_coverage",
        os.path.join("scripts", "check_codeowners_coverage.py"),
        lambda: _repo_root_argv(os.path.join(FIXTURES_ROOT, "codeowners_broken")),
    ),
    CheckerEntry(
        "check_issue_forms",
        os.path.join("scripts", "check_issue_forms.py"),
        lambda: _repo_root_argv(os.path.join(FIXTURES_ROOT, "issue_forms_broken")),
    ),
    CheckerEntry(
        "validate-backlog",
        os.path.join("scripts", "validate-backlog.py"),
        lambda: _repo_root_argv(os.path.join(FIXTURES_ROOT, "backlog_broken")),
    ),
    CheckerEntry(
        "check_required_check_reconciliation",
        os.path.join("scripts", "check_required_check_reconciliation.py"),
        lambda: _reconciliation_argv(
            os.path.join(FIXTURES_ROOT, "reconciliation_broken")
        ),
    ),
    CheckerEntry(
        "check_markdown_governance_docs",
        os.path.join("scripts", "check_markdown_governance_docs.py"),
        lambda: _markdown_governance_docs_argv(
            os.path.join(FIXTURES_ROOT, "markdown_broken")
        ),
    ),
    CheckerEntry(
        "check_bypass_register",
        os.path.join("scripts", "check_bypass_register.py"),
        lambda: _bypass_register_argv(
            os.path.join(FIXTURES_ROOT, "bypass_register_broken")
        ),
    ),
)


def _run_checker(entry: CheckerEntry, repo_root: str) -> int:
    script_path = os.path.join(repo_root, entry.script_rel_path)
    argv = entry.build_argv()
    result = subprocess.run(
        [sys.executable, script_path, *argv],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode


def run_self_test(repo_root: str) -> int:
    failures: list[str] = []
    for entry in CHECKERS:
        exit_code = _run_checker(entry, repo_root)
        if exit_code == 0:
            failures.append(entry.name)
            print(f"  {entry.name}: FAIL (exited 0 against broken fixture)")
        else:
            print(f"  {entry.name}: OK (exited {exit_code} against broken fixture)")

    if failures:
        print(
            "SELF-TEST FAILED: the following checkers did not fail against a "
            f"deliberately broken fixture: {', '.join(failures)}"
        )
        return 1

    print(
        f"SELF-TEST OK: all {len(CHECKERS)} checkers correctly failed on broken fixtures"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=REPO_ROOT)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run every checker against its bundled broken fixture and assert it fails",
    )
    args = parser.parse_args(argv)

    if not args.self_test:
        print("gov_self_test: nothing to do (pass --self-test)")
        return 0

    repo_root = os.path.abspath(args.repo_root)
    for entry in CHECKERS:
        script_path = os.path.join(repo_root, entry.script_rel_path)
        if not os.path.isfile(script_path):
            print(
                f"gov_self_test internal error: missing checker script {script_path}",
                file=sys.stderr,
            )
            return 2

    return run_self_test(repo_root)


if __name__ == "__main__":
    sys.exit(main())
