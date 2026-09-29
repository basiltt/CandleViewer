#!/usr/bin/env python3
"""GOV-002: verify every C-x.y rule reference cited in the repo resolves to a
declaration in CONSTITUTION.md (C-16.4).

Exit codes: 0 clean, 1 violations found, 2 internal error.
Stdlib only (no third-party deps) so this runs before E02 scaffolds a package
manager.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass

RULE_ID_RE = re.compile(r"C-\d+\.\d+")
# A declaration is a bold rule id at the start of the line, e.g.
# "**C-2.6 Native exchange stop-loss invariant.** ..." — the closing "**"
# comes after the prose, not immediately after the id, so match on a
# word boundary rather than a closing "**".
DECL_RE_TEMPLATE = r"^\*\*{id}\b"
TRACKED_GLOBS = (".md", ".yaml", ".yml")
TRACKED_BASENAMES = ("CODEOWNERS",)
CONSTITUTION_FILE = "CONSTITUTION.md"
# Deliberately-broken governance self-test fixtures (scripts/gov_self_test.py)
# ship real tracked files with dangling rule ids on purpose. They must be
# excluded from the real GOV-002 scan or every normal run fails permanently.
EXCLUDED_PREFIX = "scripts/tests/fixtures/self_test/"


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    rule_id: str

    def render(self) -> str:
        return f"GOV-002 {self.path}:{self.line} {self.rule_id}"


def git_tracked_files(repo_root: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def is_scanned_file(path: str) -> bool:
    normalized = path.replace(os.sep, "/")
    if normalized.startswith(EXCLUDED_PREFIX):
        return False
    base = os.path.basename(path)
    if base in TRACKED_BASENAMES:
        return True
    return path.endswith(TRACKED_GLOBS)


def load_declared_ids(repo_root: str) -> set[str]:
    constitution_path = os.path.join(repo_root, CONSTITUTION_FILE)
    declared: set[str] = set()
    with open(constitution_path, encoding="utf-8") as fh:
        for line in fh:
            for candidate in RULE_ID_RE.findall(line):
                pattern = DECL_RE_TEMPLATE.format(id=re.escape(candidate))
                if re.match(pattern, line.strip()):
                    declared.add(candidate)
    return declared


def find_violations(repo_root: str, declared: set[str]) -> list[Violation]:
    violations: list[Violation] = []
    for rel_path in git_tracked_files(repo_root):
        if not is_scanned_file(rel_path):
            continue
        abs_path = os.path.join(repo_root, rel_path)
        try:
            with open(abs_path, encoding="utf-8") as fh:
                lines = fh.readlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise UnreadableFileError(f"cannot read {rel_path}: {exc}") from exc
        for lineno, line in enumerate(lines, start=1):
            for rule_id in RULE_ID_RE.findall(line):
                if rule_id not in declared:
                    violations.append(Violation(rel_path, lineno, rule_id))
    return violations


class UnreadableFileError(Exception):
    """Raised when a tracked text file cannot be decoded."""


def nearest_ids(rule_id: str, declared: set[str], limit: int = 5) -> list[str]:
    try:
        section = int(rule_id.split("-", 1)[1].split(".", 1)[0])
    except (IndexError, ValueError):
        return sorted(declared)[:limit]
    same_section = sorted(
        d for d in declared if d.startswith(f"C-{section}.")
    )
    if same_section:
        return same_section[:limit]
    return sorted(declared)[:limit]


def emit(violations: list[Violation], as_json: bool, github_actions: bool) -> None:
    if as_json:
        payload = [
            {"code": "GOV-002", "path": v.path, "line": v.line, "rule_id": v.rule_id}
            for v in violations
        ]
        print(json.dumps(payload, indent=2))
        return
    for v in violations:
        print(v.render())
        if github_actions:
            print(
                f"::error file={v.path},line={v.line}::"
                f"GOV-002 dangling rule reference {v.rule_id}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument(
        "--fix-suggest",
        action="store_true",
        help="for each violation, list the nearest existing declared ids",
    )
    args = parser.parse_args(argv)

    repo_root = os.path.abspath(args.repo_root)
    try:
        declared = load_declared_ids(repo_root)
        violations = find_violations(repo_root, declared)
    except UnreadableFileError as exc:
        print(f"GOV-002 internal error: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(f"GOV-002 internal error: git ls-files failed: {exc}", file=sys.stderr)
        return 2

    github_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    emit(violations, args.json, github_actions)

    if args.fix_suggest and violations and not args.json:
        for v in violations:
            suggestions = nearest_ids(v.rule_id, declared)
            print(f"  nearest declared ids for {v.rule_id}: {', '.join(suggestions) or 'none'}")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
