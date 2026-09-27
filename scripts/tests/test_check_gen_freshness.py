"""Unit tests for tools/ci/check_gen_freshness.py (E03-T05, ADR-0013 rule 3).

Exercises the four Gherkin scenarios from the ticket by faking `subprocess.run`
so the test never actually invokes `pnpm generate` or touches real git state
(no network, deterministic, fast).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import check_gen_freshness as gen_gate


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_in_sync_tree_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scenario: An in-sync tree passes."""
    calls: list[list[str]] = []

    def fake_run(cmd, cwd=None):
        calls.append(cmd)
        if cmd[:2] == ["pnpm", "generate"]:
            return _proc(0)
        if cmd[:2] == ["git", "ls-files"]:
            return _proc(0, stdout="")
        if cmd[:2] == ["git", "diff"]:
            return _proc(0)
        if cmd[:2] == ["git", "status"]:
            return _proc(0, stdout="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(gen_gate, "_run", fake_run)
    assert gen_gate.main([]) == 0


def test_schema_edit_without_regeneration_fails_with_diff_and_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Scenario: A schema edit without regeneration fails."""

    def fake_run(cmd, cwd=None):
        if cmd[:2] == ["pnpm", "generate"]:
            return _proc(0)
        if cmd[:2] == ["git", "ls-files"]:
            return _proc(0, stdout="")
        if cmd[:2] == ["git", "diff"]:
            return _proc(
                1, stdout="--- a/packages/protocol/src/generated/rest.ts\n+++ ..."
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(gen_gate, "_run", fake_run)
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert "CI-GEN-001" in err
    assert "make gen" in err


def test_untracked_generated_output_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Scenario: Untracked generated output fails."""

    def fake_run(cmd, cwd=None):
        if cmd[:2] == ["pnpm", "generate"]:
            return _proc(0)
        if cmd[:2] == ["git", "ls-files"]:
            return _proc(0, stdout="")
        if cmd[:2] == ["git", "diff"]:
            return _proc(0)
        if cmd[:2] == ["git", "status"]:
            return _proc(0, stdout="?? packages/protocol/src/generated/new-file.ts\n")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(gen_gate, "_run", fake_run)
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert "CI-GEN-002" in err


def test_nondeterministic_generation_fails_before_diff_check(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Scenario: Non-deterministic generation is caught, before diff runs."""
    hash_calls = {"n": 0}
    diff_called = {"value": False}

    def fake_run(cmd, cwd=None):
        if cmd[:2] == ["pnpm", "generate"]:
            return _proc(0)
        if cmd[:2] == ["git", "ls-files"]:
            return _proc(0, stdout="")
        if cmd[:2] == ["git", "diff"]:
            diff_called["value"] = True
            return _proc(0)
        raise AssertionError(f"unexpected command: {cmd}")

    def fake_hash(root):
        hash_calls["n"] += 1
        return f"hash-{hash_calls['n']}"

    monkeypatch.setattr(gen_gate, "_run", fake_run)
    monkeypatch.setattr(gen_gate, "_hash_generated_tree", fake_hash)

    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert "CI-GEN-003" in err
    assert "codegen is not deterministic" in err
    assert diff_called["value"] is False


def test_generator_toolchain_failure_reports_ci_gen_004(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run(cmd, cwd=None):
        if cmd[:2] == ["pnpm", "generate"]:
            return _proc(1, stderr="boom")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(gen_gate, "_run", fake_run)
    assert gen_gate.main([]) == 1
    err = capsys.readouterr().err
    assert "CI-GEN-004" in err
