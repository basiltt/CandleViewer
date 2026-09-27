#!/usr/bin/env python3
"""SR-132: verify every GitHub Actions workflow references actions by a
40-hex-character commit SHA (never a floating tag/branch) and never uses the
``pull_request_target`` trigger.

Exit codes: 0 clean, 1 violations found, 2 internal error (bad path / no
workflows found when a specific path was requested).

CI-GATE-003 is the resolver error code raised when this check fails inside
the ``ci-required`` gate job (see ``.github/workflows/pr.yml``).

Stdlib only — this must run before any package manager is bootstrapped.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# `uses:` lines referencing local paths (`./`) or Docker refs (`docker://`)
# are exempt from SHA pinning — they aren't fetched from the marketplace.
USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<ref>\S+)\s*(?:#.*)?$")
SHA_SUFFIX_RE = re.compile(r"@([0-9a-f]{40})$")
COMMENT_LINE_RE = re.compile(r"^\s*#")
PULL_REQUEST_TARGET_RE = re.compile(r"^\s*(?:-\s*)?pull_request_target\b")


@dataclass(frozen=True)
class Violation:
    path: Path
    line_no: int
    line: str
    reason: str

    def format(self) -> str:
        return f"{self.path}:{self.line_no}: {self.reason}: {self.line.strip()}"


def _iter_workflow_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    found: list[Path] = []
    for pattern in ("*.yml", "*.yaml"):
        found.extend(sorted(root.glob(pattern)))
    return found


def check_file(path: Path) -> list[Violation]:
    violations: list[Violation] = []
    text = path.read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), start=1):
        if COMMENT_LINE_RE.match(line):
            continue

        if PULL_REQUEST_TARGET_RE.match(line):
            violations.append(
                Violation(
                    path,
                    line_no,
                    line,
                    "pull_request_target is prohibited (SR-132)",
                )
            )

        m = USES_RE.match(line)
        if not m:
            continue
        ref = m.group("ref").strip('"').strip("'")
        if ref.startswith(("./", "docker://")):
            continue
        if "@" not in ref:
            violations.append(
                Violation(path, line_no, line, "unpinned action reference (no @ref)")
            )
            continue
        if not SHA_SUFFIX_RE.search(ref):
            violations.append(
                Violation(
                    path,
                    line_no,
                    line,
                    "unpinned action reference (not a 40-hex commit SHA)",
                )
            )
    return violations


def check_paths(paths: list[Path]) -> list[Violation]:
    violations: list[Violation] = []
    for root in paths:
        for wf in _iter_workflow_files(root):
            violations.extend(check_file(wf))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        default=[".github/workflows"],
        help="Workflow file(s) or directory to check (default: .github/workflows)",
    )
    args = parser.parse_args(argv)

    resolved = [Path(p) for p in args.paths]
    for p in resolved:
        if not p.exists():
            print(f"error: path does not exist: {p}", file=sys.stderr)
            return 2

    violations = check_paths(resolved)
    if violations:
        print("CI-GATE-003: unpinned or unsafe action reference(s) found:", file=sys.stderr)
        for v in violations:
            print(f"  {v.format()}", file=sys.stderr)
        return 1

    print("check_action_pins: OK — all actions SHA-pinned, no pull_request_target")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
