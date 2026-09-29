"""Unit tests for scripts/gov_self_test.py (E01-Q02 canary/self-test mode).

The self-test mode is the guard against the worst outcome named in the
ticket: a green governance check that no longer checks anything. It runs
each GOV-00x checker against a deliberately-broken fixture tree bundled
under scripts/tests/fixtures/self_test/ and asserts every checker exits
non-zero (fails) against its known-bad fixture. If a checker instead exits
0 against broken input, the self-test itself must fail.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SCRIPTS_DIR.parent
SCRIPT = SCRIPTS_DIR / "gov_self_test.py"

sys.path.insert(0, str(SCRIPTS_DIR))

import gov_self_test


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_manifest_lists_every_checker_the_workflow_invokes() -> None:
    # Guards against the exact mutation named in the ticket: removing a
    # checker invocation from governance.yml without anyone noticing.
    workflow = (REPO_ROOT / ".github" / "workflows" / "governance.yml").read_text(
        encoding="utf-8"
    )
    for entry in gov_self_test.CHECKERS:
        assert entry.module_file in workflow, (
            f"{entry.name}: {entry.module_file} is in the self-test manifest "
            "but governance.yml no longer invokes it"
        )


def test_real_self_test_run_passes_on_bundled_fixtures() -> None:
    result = _run("--self-test")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SELF-TEST OK" in result.stdout


def test_self_test_fails_if_a_checker_exits_zero_on_broken_fixture(
    monkeypatch,
) -> None:
    def _fake_run_checker(entry, repo_root):
        return 0  # pretend every checker passed, even against broken input

    monkeypatch.setattr(gov_self_test, "_run_checker", _fake_run_checker)
    exit_code = gov_self_test.main(["--self-test"])
    assert exit_code == 1


def test_self_test_reports_which_checker_stayed_green(monkeypatch, capsys) -> None:
    target = next(e for e in gov_self_test.CHECKERS if e.name == "check_rule_refs")

    def _fake_run_checker(entry, repo_root):
        return 0 if entry is target else 1

    monkeypatch.setattr(gov_self_test, "_run_checker", _fake_run_checker)
    exit_code = gov_self_test.main(["--self-test"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "check_rule_refs" in out
    assert "FAIL (exited 0 against broken fixture)" in out
