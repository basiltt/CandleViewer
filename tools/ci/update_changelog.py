#!/usr/bin/env python3
"""E03-T11: append new commits since the last tag to CHANGELOG.md's
`## Unreleased` section (called by `.github/workflows/changelog.yml` on
every merge to `main`).

Usage:
    python tools/ci/update_changelog.py --commits-json commits.json \\
        --changelog CHANGELOG.md

`commits-json` is a JSON array of `{"sha": "...", "message": "..."}` objects
for commits since the last tag (the workflow produces this via `git log`).

Exit codes: 0 updated (or nothing to do), 1 internal error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.ci.changelog_lib import (  # noqa: E402
    Category,
    ParsedCommit,
    build_changelog_update,
    check_security_wording,
    parse_commit,
)

_CATEGORY_ORDER = [
    Category.BREAKING,
    Category.FEATURES,
    Category.FIXES,
    Category.PERFORMANCE,
    Category.SECURITY,
]

_HEADING = "## Unreleased"


def _default_changelog() -> str:
    lines = ["# Changelog", "", "All notable changes to CandleViewer are documented here.", ""]
    lines.append(_HEADING)
    for cat in _CATEGORY_ORDER:
        lines.append("")
        lines.append(f"### {cat.value}")
    lines.append("")
    return "\n".join(lines)


def _load_commits(path: Path) -> list[ParsedCommit]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [parse_commit(item["sha"], item["message"]) for item in raw]


def _render_unreleased_section(existing: dict[Category, list[str]]) -> list[str]:
    out = [_HEADING]
    for cat in _CATEGORY_ORDER:
        out.append("")
        out.append(f"### {cat.value}")
        out.extend(existing.get(cat, []))
    out.append("")
    return out


def _parse_existing_unreleased(text: str) -> tuple[str, str, dict[Category, list[str]]]:
    """Split `text` into (before, after, entries-under-Unreleased-by-category)."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == _HEADING)
    except StopIteration:
        return text.rstrip("\n") + "\n\n", "", {}

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## ") and lines[i].strip() != _HEADING:
            end = i
            break

    before = "\n".join(lines[:start]).rstrip("\n") + "\n\n"
    after = "\n".join(lines[end:])
    if after and not after.endswith("\n"):
        after += "\n"

    entries: dict[Category, list[str]] = {}
    current: Category | None = None
    for line in lines[start + 1 : end]:
        stripped = line.strip()
        matched = next((c for c in _CATEGORY_ORDER if stripped == f"### {c.value}"), None)
        if matched is not None:
            current = matched
            continue
        if current is not None and stripped.startswith("- "):
            entries.setdefault(current, []).append(line)
    return before, after, entries


def apply_update(changelog_text: str, commits: list[ParsedCommit]) -> tuple[str, bool]:
    """Return (new_text, changed)."""
    update = build_changelog_update(commits)
    if not update.has_entries():
        return changelog_text, False

    before, after, existing = _parse_existing_unreleased(changelog_text)
    for cat, new_lines in update.entries.items():
        existing.setdefault(cat, []).extend(new_lines)

    security_result = check_security_wording(existing.get(Category.SECURITY, []))
    if not security_result.ok:
        for line in security_result.violations:
            print(
                f"WARNING: Security changelog line may contain exploit detail: {line!r}",
                file=sys.stderr,
            )

    section = "\n".join(_render_unreleased_section(existing))
    new_text = before + section + "\n" + after
    return new_text, True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commits-json", type=Path, required=True)
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    args = parser.parse_args(argv)

    commits = _load_commits(args.commits_json)

    if args.changelog.exists():
        text = args.changelog.read_text(encoding="utf-8")
    else:
        text = _default_changelog()

    new_text, changed = apply_update(text, commits)
    args.changelog.write_text(new_text, encoding="utf-8", newline="\n")

    if changed:
        print(f"CHANGELOG.md updated ({args.changelog}).")
    else:
        print("No changelog-worthy commits; CHANGELOG.md left unchanged (still written).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
