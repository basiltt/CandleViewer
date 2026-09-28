#!/usr/bin/env python3
"""E03-T08: SR-131 -- reject a floating (undigested) base image in a Dockerfile.

ADR-0013 rule 8 / ticket acceptance scenario "A floating base image is
rejected": a `FROM` line without an `@sha256:<digest>` pin must fail the
build, naming the unpinned base image. This runs alongside hadolint (which
lints Dockerfile style/best-practice, not digest pinning specifically) as
the `dockerfile-pins` step in `.github/workflows/main.yml`.

Error code: CI-IMG-001 (unpinned base image).

Exit codes: 0 clean, 1 violations found, 2 internal error (no Dockerfiles
found when a specific path was requested).

Stdlib only.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

FROM_RE = re.compile(
    r"^\s*FROM\s+(?P<image>\S+?)(?:\s+AS\s+\S+)?\s*(?:#.*)?$",
    re.IGNORECASE,
)
DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class Violation:
    path: Path
    line_no: int
    line: str
    reason: str

    def format(self) -> str:
        return f"{self.path}:{self.line_no}: CI-IMG-001: {self.reason}: {self.line.strip()}"


def _iter_dockerfiles(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(
        p
        for p in root.rglob("Dockerfile*")
        if p.is_file() and "node_modules" not in p.parts and ".git" not in p.parts
    )


def _known_stage_names(lines: list[str]) -> set[str]:
    names: set[str] = set()
    stage_re = re.compile(r"\bAS\s+(\S+)\s*$", re.IGNORECASE)
    for line in lines:
        m = stage_re.search(line.split("#", 1)[0])
        if m:
            names.add(m.group(1))
    return names


def check_file(path: Path) -> list[Violation]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    stage_names = _known_stage_names(lines)
    violations: list[Violation] = []
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = FROM_RE.match(line)
        if not m:
            continue
        image = m.group("image")
        if image.lower() == "scratch":
            continue
        if image in stage_names:
            continue
        if not DIGEST_RE.search(image):
            violations.append(
                Violation(
                    path=path,
                    line_no=i,
                    line=line,
                    reason=f"unpinned base image {image!r} (missing @sha256:<digest>)",
                )
            )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Dockerfile path(s) or directory root(s) to scan (default: repo root)",
    )
    args = parser.parse_args(argv)

    all_violations: list[Violation] = []
    any_found = False
    for raw in args.paths:
        root = Path(raw)
        if not root.exists():
            print(f"CI-IMG-001: path not found: {root}", file=sys.stderr)
            return 2
        files = _iter_dockerfiles(root)
        any_found = any_found or bool(files)
        for f in files:
            all_violations.extend(check_file(f))

    if not any_found:
        print("CI-IMG-001: no Dockerfiles found", file=sys.stderr)
        return 2

    for v in all_violations:
        print(v.format(), file=sys.stderr)

    return 1 if all_violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
