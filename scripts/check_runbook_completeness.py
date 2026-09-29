#!/usr/bin/env python3
"""E03-T15: runbook completeness gate.

`docs/ci-runbook.md` documents a triage recipe for every `CI-<FAMILY>-<NNN>`
error code the pipeline can emit. Code drifts from docs the moment someone
adds a new check without a paragraph to go with it, so this script makes
that drift a CI failure instead of a stale-docs bug report:

1. Scans workflow and tool sources (`.github/workflows/**/*.yml`,
   `tools/ci/**/*.py`, `tools/ci/**/*.mjs`, `scripts/**/*.py`,
   `scripts/**/*.mjs`) for the `CI-[A-Z]+-\\d{3}` pattern and collects the
   set of codes actually emitted by the pipeline.
2. Scans `docs/ci-runbook.md` for the same pattern to find the set of codes
   the runbook documents a recipe for.
3. Fails (exit 1) when a code is emitted but not documented. A documented
   code with no current emitter is not a failure (families get retired
   before their prose does); it is reported as an informational note only.

Stdlib only — no network access performed by this module.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CODE_RE = re.compile(r"CI-[A-Z]+-\d{3}")

# Source globs scanned for emitted codes. Deliberately narrow (CI tooling and
# workflow YAML only) so that e.g. this checker's own docstring examples or
# ticket-backlog prose do not count as "emitted".
SOURCE_GLOBS: tuple[str, ...] = (
    ".github/workflows/**/*.yml",
    ".github/workflows/**/*.yaml",
    "tools/ci/**/*.py",
    "tools/ci/**/*.mjs",
    "scripts/**/*.py",
    "scripts/**/*.mjs",
)

# Directories excluded even if they match a glob above (caches, this file's
# own test fixtures under scripts/tests/ still count deliberately since the
# tests assert on the same codes production code emits).
EXCLUDED_DIR_PARTS = ("__pycache__",)

DEFAULT_RUNBOOK_PATH = "docs/ci-runbook.md"


class RunbookCompletenessError(Exception):
    """Raised when an emitted code has no runbook section (exit 1)."""


def _iter_source_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in SOURCE_GLOBS:
        for path in repo_root.glob(pattern):
            if not path.is_file():
                continue
            if any(part in EXCLUDED_DIR_PARTS for part in path.parts):
                continue
            files.append(path)
    return files


def collect_emitted_codes(repo_root: Path) -> dict[str, list[str]]:
    """Return {code: [relative file paths mentioning it]}."""
    emitted: dict[str, list[str]] = {}
    for path in _iter_source_files(repo_root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for match in CODE_RE.findall(text):
            rel = str(path.relative_to(repo_root)).replace("\\", "/")
            emitted.setdefault(match, [])
            if rel not in emitted[match]:
                emitted[match].append(rel)
    return emitted


def collect_documented_codes(runbook_path: Path) -> set[str]:
    if not runbook_path.is_file():
        raise RunbookCompletenessError(f"runbook not found: {runbook_path}")
    text = runbook_path.read_text(encoding="utf-8")
    return set(CODE_RE.findall(text))


def check(repo_root: Path, runbook_path: Path) -> tuple[list[str], list[str]]:
    """Return (missing, extra) code lists, both sorted.

    ``missing`` codes are emitted but undocumented (a hard failure).
    ``extra`` codes are documented but not currently emitted (informational).
    """
    emitted = collect_emitted_codes(repo_root)
    documented = collect_documented_codes(runbook_path)
    missing = sorted(set(emitted) - documented)
    extra = sorted(documented - set(emitted))
    return missing, extra


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="Repository root (default: cwd)")
    parser.add_argument(
        "--runbook",
        default=DEFAULT_RUNBOOK_PATH,
        help=f"Path to the runbook (default: {DEFAULT_RUNBOOK_PATH})",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    runbook_path = repo_root / args.runbook

    try:
        missing, extra = check(repo_root, runbook_path)
    except RunbookCompletenessError as exc:
        print(f"CI-DOC-001: {exc}", file=sys.stderr)
        return 2

    if extra:
        print(
            "note: runbook documents codes with no current emitter "
            f"(not a failure): {', '.join(extra)}",
            file=sys.stderr,
        )

    if missing:
        emitted = collect_emitted_codes(repo_root)
        print(
            "CI-DOC-001: the following error codes are emitted by CI tooling "
            "but have no docs/ci-runbook.md section:",
            file=sys.stderr,
        )
        for code in missing:
            sources = ", ".join(emitted[code])
            print(f"  - {code} (seen in: {sources})", file=sys.stderr)
        return 1

    print(
        f"runbook completeness OK: {len(collect_documented_codes(runbook_path))} codes documented"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
