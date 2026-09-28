#!/usr/bin/env python3
"""E03-T06: fixture integrity gate for the `integration` CI job.

Verifies every recorded fixture referenced by `tests/fixtures/MANIFEST.sha256`
resolves on disk and its SHA-256 matches the recorded digest, per the
ticket's "Technical notes": "each recorded fixture carries a SHA-256
recorded in `tests/fixtures/MANIFEST.sha256`, verified before use (a
corrupted fixture silently changing golden outputs is worse than a missing
one)".

Manifest format (one entry per line, git-diff-friendly, sorted by path):
    <sha256-hex>  <repo-relative-path>

Distinct error codes so a missing fixture never looks like a skip:
    CI-INT-001  fixture unavailable (path in the manifest does not resolve
                on disk — the ticket's LFS-pointer-unresolved scenario)
    CI-INT-002  fixture checksum mismatch (corrupted or silently edited)

Exit codes: 0 clean, 1 a CI-INT-* violation was found, 2 internal error
(manifest missing/malformed). Stdlib only.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MANIFEST = Path("tests/fixtures/MANIFEST.sha256")


class ManifestError(Exception):
    pass


@dataclass(frozen=True)
class ManifestEntry:
    digest: str
    path: str


@dataclass(frozen=True)
class Violation:
    code: str
    path: str
    message: str


def parse_manifest(manifest_path: Path) -> list[ManifestEntry]:
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ManifestError(f"manifest not found: {manifest_path}") from exc

    entries: list[ManifestEntry] = []
    for line_no, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(None, 1)
        if len(parts) != 2:
            raise ManifestError(f"{manifest_path}:{line_no}: malformed entry {stripped!r}")
        digest, path = parts
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
            raise ManifestError(f"{manifest_path}:{line_no}: not a sha256 hex digest: {digest!r}")
        entries.append(ManifestEntry(digest=digest.lower(), path=path))
    return entries


def _sha256_of(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def verify(entries: list[ManifestEntry], *, repo_root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for entry in entries:
        resolved = repo_root / entry.path
        if not resolved.is_file():
            violations.append(
                Violation(
                    code="CI-INT-001",
                    path=entry.path,
                    message=(
                        f"fixture unavailable: {entry.path} does not resolve on disk "
                        "(missing file or unresolved LFS pointer)"
                    ),
                )
            )
            continue
        actual = _sha256_of(resolved)
        if actual != entry.digest:
            violations.append(
                Violation(
                    code="CI-INT-002",
                    path=entry.path,
                    message=(
                        f"fixture checksum mismatch: {entry.path} expected {entry.digest} "
                        f"got {actual}"
                    ),
                )
            )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="path to the MANIFEST.sha256 file (default: tests/fixtures/MANIFEST.sha256)",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="repo root fixture paths are relative to (default: cwd)",
    )
    args = parser.parse_args(argv)

    try:
        entries = parse_manifest(args.manifest)
    except ManifestError as exc:
        print(f"internal error: {exc}", file=sys.stderr)
        return 2

    if not entries:
        print(f"internal error: {args.manifest} has no entries", file=sys.stderr)
        return 2

    violations = verify(entries, repo_root=args.repo_root)
    for v in violations:
        print(f"{v.code}: {v.message}", file=sys.stderr)

    if violations:
        print(f"fixture manifest check FAILED ({len(violations)} violation(s))", file=sys.stderr)
        return 1

    print(f"fixture manifest check passed ({len(entries)} fixture(s) verified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
