"""Unit tests for tools/ci/verify_fixture_manifest.py (E03-T06).

Exercises the ticket's two fixture-integrity scenarios (missing fixture,
checksum mismatch) plus the happy path, entirely against `tmp_path` —
no network, no real fixtures touched (CONSTITUTION C-13.5/C-13.7).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import verify_fixture_manifest as gate


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_parse_manifest_skips_blank_lines_and_comments(tmp_path: Path) -> None:
    manifest = tmp_path / "MANIFEST.sha256"
    manifest.write_text(
        "# a comment\n\n" + ("a" * 64) + "  some/path.jsonl\n",
        encoding="utf-8",
    )
    entries = gate.parse_manifest(manifest)
    assert entries == [gate.ManifestEntry(digest="a" * 64, path="some/path.jsonl")]


def test_parse_manifest_rejects_malformed_entry(tmp_path: Path) -> None:
    manifest = tmp_path / "MANIFEST.sha256"
    manifest.write_text("not-a-valid-line\n", encoding="utf-8")
    with pytest.raises(gate.ManifestError):
        gate.parse_manifest(manifest)


def test_parse_manifest_rejects_non_hex_digest(tmp_path: Path) -> None:
    manifest = tmp_path / "MANIFEST.sha256"
    manifest.write_text(("zz" * 32) + "  some/path.jsonl\n", encoding="utf-8")
    with pytest.raises(gate.ManifestError):
        gate.parse_manifest(manifest)


def test_parse_manifest_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(gate.ManifestError):
        gate.parse_manifest(tmp_path / "does-not-exist.sha256")


def test_verify_in_sync_fixture_passes(tmp_path: Path) -> None:
    """Scenario: a fixture whose digest matches the manifest passes clean."""
    fixture = tmp_path / "raw" / "sample.jsonl"
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(b"hello world\n")
    entry = gate.ManifestEntry(digest=_sha256(b"hello world\n"), path="raw/sample.jsonl")

    violations = gate.verify([entry], repo_root=tmp_path)

    assert violations == []


def test_verify_missing_fixture_fails_with_ci_int_001(tmp_path: Path) -> None:
    """Scenario: a missing fixture fails loudly instead of skipping."""
    entry = gate.ManifestEntry(digest="a" * 64, path="raw/does-not-exist.jsonl")

    violations = gate.verify([entry], repo_root=tmp_path)

    assert len(violations) == 1
    assert violations[0].code == "CI-INT-001"
    assert "raw/does-not-exist.jsonl" in violations[0].message


def test_verify_corrupted_fixture_fails_with_ci_int_002(tmp_path: Path) -> None:
    """Meta-test: a deliberately corrupted checksum must fail with CI-INT-002."""
    fixture = tmp_path / "raw" / "sample.jsonl"
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(b"corrupted content")
    entry = gate.ManifestEntry(digest=_sha256(b"original content"), path="raw/sample.jsonl")

    violations = gate.verify([entry], repo_root=tmp_path)

    assert len(violations) == 1
    assert violations[0].code == "CI-INT-002"


def test_main_exits_zero_on_clean_manifest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fixture = tmp_path / "raw" / "sample.jsonl"
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(b"data")
    manifest = tmp_path / "MANIFEST.sha256"
    manifest.write_text(f"{_sha256(b'data')}  raw/sample.jsonl\n", encoding="utf-8")

    exit_code = gate.main(["--manifest", str(manifest), "--repo-root", str(tmp_path)])

    assert exit_code == 0
    assert "passed" in capsys.readouterr().out


def test_main_exits_one_on_violation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manifest = tmp_path / "MANIFEST.sha256"
    manifest.write_text(f"{'a' * 64}  raw/missing.jsonl\n", encoding="utf-8")

    exit_code = gate.main(["--manifest", str(manifest), "--repo-root", str(tmp_path)])

    assert exit_code == 1
    assert "CI-INT-001" in capsys.readouterr().err


def test_main_exits_two_on_missing_manifest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = gate.main(["--manifest", str(tmp_path / "nope.sha256"), "--repo-root", str(tmp_path)])

    assert exit_code == 2
    assert "internal error" in capsys.readouterr().err


def test_main_exits_two_on_empty_manifest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manifest = tmp_path / "MANIFEST.sha256"
    manifest.write_text("# only a comment\n", encoding="utf-8")

    exit_code = gate.main(["--manifest", str(manifest), "--repo-root", str(tmp_path)])

    assert exit_code == 2
    assert "no entries" in capsys.readouterr().err
