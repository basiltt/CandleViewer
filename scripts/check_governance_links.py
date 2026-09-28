#!/usr/bin/env python3
"""E01-Q02: relative-link resolution check over governance documents.

Scans a fixed set of governance markdown files for markdown-style relative
links (`[text](path)`, excluding `http(s)://`, `mailto:`, and pure in-page
`#anchor` links) and verifies the target path exists on disk, relative to
the linking file's own directory. A rename that leaves a dangling relative
link is exactly the silent-decay case this ticket exists to catch.

Exit codes: 0 clean, 1 dangling link(s) found, 2 internal error.
Stdlib only.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

DEFAULT_TARGETS = (
    "CONSTITUTION.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "CLAUDE.md",
)
DEFAULT_GLOB_DIRS = ("docs/plan", "docs/plan/27-adrs", ".claude/rules")


def _iter_markdown_files(repo_root: str) -> list[str]:
    files = [p for p in DEFAULT_TARGETS if os.path.isfile(os.path.join(repo_root, p))]
    for rel_dir in DEFAULT_GLOB_DIRS:
        abs_dir = os.path.join(repo_root, rel_dir)
        if not os.path.isdir(abs_dir):
            continue
        for name in sorted(os.listdir(abs_dir)):
            if name.endswith(".md"):
                files.append(os.path.join(rel_dir, name))
    return files


def _is_external_or_anchor(target: str) -> bool:
    target = target.split(" ", 1)[0]  # strip an optional "title" suffix
    if not target or target.startswith("#"):
        return True
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target))  # scheme: e.g. http:, mailto:


def check(repo_root: str) -> list[str]:
    violations: list[str] = []
    for rel_path in _iter_markdown_files(repo_root):
        abs_path = os.path.join(repo_root, rel_path)
        try:
            with open(abs_path, encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError as exc:
            raise RuntimeError(f"cannot read {rel_path}: {exc}") from exc

        for lineno, line in enumerate(lines, start=1):
            for match in LINK_RE.finditer(line):
                target = match.group(1).strip()
                if _is_external_or_anchor(target):
                    continue
                target_path, _, _anchor = target.partition("#")
                if not target_path:
                    continue
                resolved = os.path.normpath(
                    os.path.join(os.path.dirname(abs_path), target_path)
                )
                if not os.path.exists(resolved):
                    violations.append(f"GOV-LINK {rel_path}:{lineno} dangling link -> {target}")
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)

    repo_root = os.path.abspath(args.repo_root)
    try:
        violations = check(repo_root)
    except RuntimeError as exc:
        print(f"GOV-LINK internal error: {exc}", file=sys.stderr)
        return 2

    if violations:
        for v in violations:
            print(v)
        return 1
    print("GOV-LINK: all relative links in governance documents resolve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
