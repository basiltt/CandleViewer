#!/usr/bin/env python3
"""Bugfix #1556 (parent E07-T02, issue #168): migration lockfile integrity gate.

Enforces `docs/plan/21-database-schema.md` §9.3 rule 9, "migrations are
forward-only in production": once a revision file has been recorded in
`services/api/candleviewer/migrations/lockfile.json`, editing it is a CI
failure. Also catches a new `versions/*.py` file landing without a matching
lockfile entry, and a `down_revision` chain that disagrees between the
lockfile and the file's own `revision`/`down_revision` assignments.

Exit codes: 0 clean, 1 a violation was found, 2 internal error (lockfile
missing/malformed). Stdlib only — no network, no third-party imports, so
this runs identically in CI and locally with a bare `python3`.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_LOCKFILE = Path("services/api/candleviewer/migrations/lockfile.json")
DEFAULT_VERSIONS_DIR = Path("services/api/candleviewer/migrations/versions")

RULE_9_MESSAGE = "migrations are forward-only in production"


class LockfileError(Exception):
    pass


@dataclass(frozen=True)
class Violation:
    code: str
    revision: str
    message: str


def _load_lockfile(path: Path) -> dict[str, dict[str, object]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise LockfileError(f"lockfile not found: {path}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LockfileError(f"lockfile is not valid JSON: {path}: {exc}") from exc
    revisions = data.get("revisions")
    if not isinstance(revisions, dict):
        raise LockfileError(f"lockfile missing object 'revisions': {path}")
    return revisions


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _extract_revision_ids(path: Path) -> tuple[str | None, str | None]:
    """Return (revision, down_revision) string literals from an Alembic
    version file's module-level assignments, without importing it."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    revision: str | None = None
    down_revision: str | None = None
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign) and not isinstance(node, ast.Assign):
            continue
        targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            value = node.value
            literal: str | None
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                literal = value.value
            elif isinstance(value, ast.Constant) and value.value is None:
                literal = None
            else:
                continue
            if target.id == "revision":
                revision = literal
            elif target.id == "down_revision":
                down_revision = literal
    return revision, down_revision


def verify(lockfile_path: Path, versions_dir: Path, repo_root: Path) -> list[Violation]:
    violations: list[Violation] = []
    revisions = _load_lockfile(lockfile_path)

    on_disk = {
        f.stem: f
        for f in sorted(versions_dir.glob("*.py"))
        if f.name != "__init__.py"
    }

    # CI-MIG-LOCK-002: a versions/*.py file exists with no lockfile entry.
    for rev_id, file_path in on_disk.items():
        if rev_id not in revisions:
            violations.append(
                Violation(
                    code="CI-MIG-LOCK-002",
                    revision=rev_id,
                    message=(
                        f"{file_path} has no entry in {lockfile_path}; add one in this PR "
                        f"({RULE_9_MESSAGE})."
                    ),
                )
            )

    for rev_id, entry in revisions.items():
        rel_path = entry.get("path")
        expected_sha = entry.get("sha256")
        expected_down = entry.get("down_revision")
        if not isinstance(rel_path, str) or not isinstance(expected_sha, str):
            raise LockfileError(f"malformed lockfile entry for {rev_id!r} in {lockfile_path}")

        file_path = repo_root / rel_path
        if not file_path.is_file():
            # CI-MIG-LOCK-003: lockfile references a revision that no longer
            # exists on disk. Deleting an applied revision is itself a
            # forward-only violation, not a lockfile-maintenance shortcut.
            violations.append(
                Violation(
                    code="CI-MIG-LOCK-003",
                    revision=rev_id,
                    message=f"{rel_path} is recorded in {lockfile_path} but is missing from disk.",
                )
            )
            continue

        actual_sha = _sha256_of(file_path)
        if actual_sha != expected_sha:
            # CI-MIG-LOCK-001: the core rule-9 gate — an applied revision's
            # bytes changed since it was locked.
            violations.append(
                Violation(
                    code="CI-MIG-LOCK-001",
                    revision=rev_id,
                    message=(
                        f"{rel_path} has been edited since it was locked "
                        f"(expected sha256={expected_sha}, got {actual_sha}): {RULE_9_MESSAGE}."
                    ),
                )
            )

        actual_revision, actual_down = _extract_revision_ids(file_path)
        if actual_revision is not None and actual_revision != rev_id:
            violations.append(
                Violation(
                    code="CI-MIG-LOCK-004",
                    revision=rev_id,
                    message=(
                        f"{rel_path} declares revision={actual_revision!r} but the lockfile "
                        f"key is {rev_id!r}."
                    ),
                )
            )
        if actual_down != expected_down:
            violations.append(
                Violation(
                    code="CI-MIG-LOCK-005",
                    revision=rev_id,
                    message=(
                        f"{rel_path} declares down_revision={actual_down!r} but the lockfile "
                        f"records down_revision={expected_down!r}."
                    ),
                )
            )

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lockfile", type=Path, default=DEFAULT_LOCKFILE)
    parser.add_argument("--versions-dir", type=Path, default=DEFAULT_VERSIONS_DIR)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    try:
        violations = verify(args.lockfile, args.versions_dir, args.repo_root)
    except LockfileError as exc:
        print(f"CI-MIG-LOCK-000 internal error: {exc}", file=sys.stderr)
        return 2

    if violations:
        for v in violations:
            print(f"{v.code} [{v.revision}]: {v.message}", file=sys.stderr)
        return 1

    print(f"OK: {len(_load_lockfile(args.lockfile))} revision(s) verified against {args.lockfile}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
