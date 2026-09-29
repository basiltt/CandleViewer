#!/usr/bin/env python3
"""GOV-006: markdownlint + relative-link resolution over governance documents
(E01-Q02 scope bullet: "markdownlint over governance documents +
relative-link resolution missing from workflow").

Scope is deliberately narrow -- the governance-specific docs that describe
the `governance` required check and its GOV-00n codes -- not every Markdown
file in the repo (that is a separate, unscoped concern):

    CONTRIBUTING.md
    docs/plan/backlog/testplans/E01-governance.md
    docs/plan/backlog/testplans/E01-governance-charter.md
    docs/plan/security-reviews/E01-X02-findings.md

Two independent, stdlib-only checks (no npm/markdownlint-cli2 dependency,
matching the other GOV-00n checkers so this runs before E02 scaffolds the
JS toolchain):

1. Lint: no hard tabs, no trailing whitespace, headings increase by at most
   one level at a time, no bare (unlabelled) autolinks, single trailing
   newline. Deliberately small -- the goal is to catch obvious rot, not to
   replace a full markdownlint ruleset.
2. Relative-link resolution: every Markdown inline link `[text](target)`
   whose target is a relative path (not `http(s)://`, not a bare `#anchor`,
   not `mailto:`) must resolve, relative to the file, to a file that exists
   in the working tree.

Exit codes: 0 clean, 1 violations found, 2 internal error.
Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass

GOVERNANCE_DOCS = (
    "CONTRIBUTING.md",
    "docs/plan/backlog/testplans/E01-governance.md",
    "docs/plan/backlog/testplans/E01-governance-charter.md",
    "docs/plan/security-reviews/E01-X02-findings.md",
)

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+\S")
BARE_AUTOLINK_RE = re.compile(r"(?<![(\[])<https?://[^>]+>")


@dataclass(frozen=True)
class Violation:
    code: str
    path: str
    line: int
    detail: str

    def render(self) -> str:
        return f"{self.code} {self.path}:{self.line} {self.detail}"


class InternalError(Exception):
    """Raised for conditions that mean the check itself is broken."""


def _is_external_or_anchor(target: str) -> bool:
    if target.startswith("#"):
        return True
    for scheme in ("http://", "https://", "mailto:"):
        if target.startswith(scheme):
            return True
    return False


def _lint_lines(rel_path: str, lines: list[str]) -> list[Violation]:
    violations: list[Violation] = []
    prev_level = 0
    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\n")
        if "\t" in line:
            violations.append(
                Violation("GOV-006", rel_path, lineno, "hard tab (use spaces)")
            )
        if line != line.rstrip() and line.strip() != "":
            # Two trailing spaces is the Markdown hard-line-break idiom;
            # only flag 1 or 3+ trailing spaces as accidental whitespace.
            trailing = len(line) - len(line.rstrip())
            if trailing not in (0, 2):
                violations.append(
                    Violation("GOV-006", rel_path, lineno, "trailing whitespace")
                )
        heading_match = HEADING_RE.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            if prev_level and level > prev_level + 1:
                violations.append(
                    Violation(
                        "GOV-006",
                        rel_path,
                        lineno,
                        f"heading level jumps from h{prev_level} to h{level}",
                    )
                )
            prev_level = level
        if BARE_AUTOLINK_RE.search(line):
            violations.append(
                Violation("GOV-006", rel_path, lineno, "bare unlabelled autolink")
            )
    if lines and not lines[-1].endswith("\n"):
        violations.append(
            Violation("GOV-006", rel_path, len(lines), "missing trailing newline")
        )
    return violations


def _check_links(repo_root: str, rel_path: str, lines: list[str]) -> list[Violation]:
    violations: list[Violation] = []
    doc_dir = os.path.dirname(os.path.join(repo_root, rel_path))
    for lineno, line in enumerate(lines, start=1):
        for match in LINK_RE.finditer(line):
            target = match.group(1)
            if _is_external_or_anchor(target):
                continue
            target_path = target.split("#", 1)[0]
            if not target_path:
                continue
            resolved = os.path.normpath(os.path.join(doc_dir, target_path))
            if not os.path.exists(resolved):
                violations.append(
                    Violation(
                        "GOV-006",
                        rel_path,
                        lineno,
                        f"relative link target does not exist: {target}",
                    )
                )
    return violations


def find_violations(repo_root: str, docs: tuple[str, ...]) -> list[Violation]:
    violations: list[Violation] = []
    for rel_path in docs:
        abs_path = os.path.join(repo_root, rel_path)
        if not os.path.exists(abs_path):
            raise InternalError(f"governance doc not found: {rel_path}")
        try:
            with open(abs_path, encoding="utf-8") as fh:
                lines = fh.readlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise InternalError(f"cannot read {rel_path}: {exc}") from exc
        violations.extend(_lint_lines(rel_path, lines))
        violations.extend(_check_links(repo_root, rel_path, lines))
    return violations


def emit(violations: list[Violation], as_json: bool, github_actions: bool) -> None:
    if as_json:
        payload = [
            {"code": v.code, "path": v.path, "line": v.line, "detail": v.detail}
            for v in violations
        ]
        print(json.dumps(payload, indent=2))
        return
    for v in violations:
        print(v.render())
        if github_actions:
            print(f"::error file={v.path},line={v.line}::{v.code} {v.detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument(
        "--docs",
        nargs="+",
        default=None,
        help="override the default governance-doc file list (repo-relative paths)",
    )
    args = parser.parse_args(argv)

    repo_root = os.path.abspath(args.repo_root)
    docs = tuple(args.docs) if args.docs else GOVERNANCE_DOCS
    try:
        violations = find_violations(repo_root, docs)
    except InternalError as exc:
        print(f"GOV-006 internal error: {exc}", file=sys.stderr)
        return 2

    github_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    emit(violations, args.json, github_actions)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
