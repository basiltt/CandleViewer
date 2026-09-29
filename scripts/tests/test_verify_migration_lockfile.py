"""Unit tests for tools/ci/verify_migration_lockfile.py (bugfix #1556 /
E07-T02).

Exercises the migrations-lockfile-integrity CI gate scenarios (tampered
revision, missing lockfile entry, deleted-but-locked revision, revision-id
mismatch, down_revision mismatch) plus the happy path, entirely against
`tmp_path` — no network, no real migration files touched (CONSTITUTION
C-13.5/C-13.7).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import verify_migration_lockfile as gate

_REV_0001 = """\
from __future__ import annotations

revision: str = "0001_initial"
down_revision: str | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
"""

_REV_0002 = """\
from __future__ import annotations

revision: str = "0002_second"
down_revision: str | None = "0001_initial"


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
"""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    versions_dir = tmp_path / "services/api/candleviewer/migrations/versions"
    versions_dir.mkdir(parents=True)
    (versions_dir / "0001_initial.py").write_bytes(_REV_0001.encode("utf-8"))
    (versions_dir / "0002_second.py").write_bytes(_REV_0002.encode("utf-8"))

    lockfile = tmp_path / "services/api/candleviewer/migrations/lockfile.json"
    lockfile.write_text(
        json.dumps(
            {
                "revisions": {
                    "0001_initial": {
                        "path": "services/api/candleviewer/migrations/versions/0001_initial.py",
                        "sha256": _sha256(_REV_0001.encode("utf-8")),
                        "down_revision": None,
                    },
                    "0002_second": {
                        "path": "services/api/candleviewer/migrations/versions/0002_second.py",
                        "sha256": _sha256(_REV_0002.encode("utf-8")),
                        "down_revision": "0001_initial",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    return lockfile, versions_dir, tmp_path


def test_verify_clean_repo_passes(tmp_path: Path) -> None:
    lockfile, versions_dir, repo_root = _make_repo(tmp_path)
    violations = gate.verify(lockfile, versions_dir, repo_root)
    assert violations == []


def test_verify_edited_applied_revision_fails_rule_9(tmp_path: Path) -> None:
    """AC (#1556 defect 2 / ticket #168 negative check): editing an
    already-applied revision fails with the rule-9 message."""
    lockfile, versions_dir, repo_root = _make_repo(tmp_path)
    (versions_dir / "0001_initial.py").write_text(
        _REV_0001 + "\n# tampered\n", encoding="utf-8"
    )

    violations = gate.verify(lockfile, versions_dir, repo_root)

    assert any(v.code == "CI-MIG-LOCK-001" for v in violations)
    assert any("forward-only in production" in v.message for v in violations)


def test_verify_new_revision_missing_lockfile_entry_fails(tmp_path: Path) -> None:
    lockfile, versions_dir, repo_root = _make_repo(tmp_path)
    (versions_dir / "0003_third.py").write_text(
        'revision: str = "0003_third"\ndown_revision: str | None = "0002_second"\n',
        encoding="utf-8",
    )

    violations = gate.verify(lockfile, versions_dir, repo_root)

    assert any(
        v.code == "CI-MIG-LOCK-002" and v.revision == "0003_third" for v in violations
    )


def test_verify_locked_revision_deleted_from_disk_fails(tmp_path: Path) -> None:
    lockfile, versions_dir, repo_root = _make_repo(tmp_path)
    (versions_dir / "0002_second.py").unlink()

    violations = gate.verify(lockfile, versions_dir, repo_root)

    assert any(
        v.code == "CI-MIG-LOCK-003" and v.revision == "0002_second" for v in violations
    )


def test_verify_revision_id_mismatch_fails(tmp_path: Path) -> None:
    lockfile, versions_dir, repo_root = _make_repo(tmp_path)
    tampered = _REV_0001.replace('"0001_initial"', '"0001_renamed"')
    (versions_dir / "0001_initial.py").write_text(tampered, encoding="utf-8")
    lock_data = json.loads(lockfile.read_text(encoding="utf-8"))
    lock_data["revisions"]["0001_initial"]["sha256"] = _sha256(tampered.encode("utf-8"))
    lockfile.write_text(json.dumps(lock_data), encoding="utf-8")

    violations = gate.verify(lockfile, versions_dir, repo_root)

    assert any(v.code == "CI-MIG-LOCK-004" for v in violations)


def test_verify_down_revision_mismatch_fails(tmp_path: Path) -> None:
    lockfile, versions_dir, repo_root = _make_repo(tmp_path)
    tampered = _REV_0002.replace(
        'down_revision: str | None = "0001_initial"',
        "down_revision: str | None = None",
    )
    (versions_dir / "0002_second.py").write_text(tampered, encoding="utf-8")
    lock_data = json.loads(lockfile.read_text(encoding="utf-8"))
    lock_data["revisions"]["0002_second"]["sha256"] = _sha256(tampered.encode("utf-8"))
    lockfile.write_text(json.dumps(lock_data), encoding="utf-8")

    violations = gate.verify(lockfile, versions_dir, repo_root)

    assert any(v.code == "CI-MIG-LOCK-005" for v in violations)


def test_main_exits_nonzero_on_violation(tmp_path: Path, capsys, monkeypatch) -> None:
    lockfile, versions_dir, repo_root = _make_repo(tmp_path)
    (versions_dir / "0001_initial.py").write_text(
        _REV_0001 + "\n# tampered\n", encoding="utf-8"
    )

    exit_code = gate.main(
        [
            "--lockfile",
            str(lockfile),
            "--versions-dir",
            str(versions_dir),
            "--repo-root",
            str(repo_root),
        ]
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "CI-MIG-LOCK-001" in captured.err


def test_main_exits_zero_on_clean_repo(tmp_path: Path) -> None:
    lockfile, versions_dir, repo_root = _make_repo(tmp_path)

    exit_code = gate.main(
        [
            "--lockfile",
            str(lockfile),
            "--versions-dir",
            str(versions_dir),
            "--repo-root",
            str(repo_root),
        ]
    )

    assert exit_code == 0


def test_verify_edit_and_own_lockfile_update_fails_against_base(tmp_path: Path) -> None:
    """AC (#1556 QA follow-up): comparing the PR's own tree against itself
    lets a PR tamper with an applied revision *and* rewrite its own sha256 in
    the lockfile self-consistently. Rule 9 must still catch it by comparing
    against the merge-base lockfile."""
    lockfile, versions_dir, repo_root = _make_repo(tmp_path)
    base_revisions = json.loads(lockfile.read_text(encoding="utf-8"))["revisions"]

    tampered = _REV_0001 + "\n# tampered in the same PR\n"
    (versions_dir / "0001_initial.py").write_text(tampered, encoding="utf-8")
    lock_data = json.loads(lockfile.read_text(encoding="utf-8"))
    lock_data["revisions"]["0001_initial"]["sha256"] = _sha256(tampered.encode("utf-8"))
    lockfile.write_text(json.dumps(lock_data), encoding="utf-8")

    # The self-consistent edit doesn't trip CI-MIG-LOCK-006 without a base to
    # compare against — that's the exact gap this test guards...
    violations_without_base = gate.verify(lockfile, versions_dir, repo_root)
    assert not any(v.code == "CI-MIG-LOCK-006" for v in violations_without_base)

    # ...but comparing against the merge-base lockfile catches it.
    violations = gate.verify(lockfile, versions_dir, repo_root, base_revisions)
    assert any(
        v.code == "CI-MIG-LOCK-006" and v.revision == "0001_initial" for v in violations
    )


def test_verify_revision_removed_from_lockfile_fails_against_base(
    tmp_path: Path,
) -> None:
    lockfile, versions_dir, repo_root = _make_repo(tmp_path)
    base_revisions = json.loads(lockfile.read_text(encoding="utf-8"))["revisions"]

    (versions_dir / "0002_second.py").unlink()
    lock_data = json.loads(lockfile.read_text(encoding="utf-8"))
    del lock_data["revisions"]["0002_second"]
    lockfile.write_text(json.dumps(lock_data), encoding="utf-8")

    violations = gate.verify(lockfile, versions_dir, repo_root, base_revisions)

    assert any(
        v.code == "CI-MIG-LOCK-006" and v.revision == "0002_second" for v in violations
    )


def test_verify_unchanged_repo_passes_against_base(tmp_path: Path) -> None:
    lockfile, versions_dir, repo_root = _make_repo(tmp_path)
    base_revisions = json.loads(lockfile.read_text(encoding="utf-8"))["revisions"]

    violations = gate.verify(lockfile, versions_dir, repo_root, base_revisions)

    assert violations == []


def test_missing_lockfile_is_internal_error(tmp_path: Path) -> None:
    exit_code = gate.main(
        [
            "--lockfile",
            str(tmp_path / "does-not-exist.json"),
            "--versions-dir",
            str(tmp_path),
            "--repo-root",
            str(tmp_path),
        ]
    )
    assert exit_code == 2
