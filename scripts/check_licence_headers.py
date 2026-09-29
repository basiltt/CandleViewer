#!/usr/bin/env python3
"""Licence header check (ADR-0013 "[always]" job: licence-header).

CandleViewer is UNLICENSED/private (see package.json). This check enforces
the inverse of a typical OSS licence-header gate: it fails if any tracked
source file carries a *third-party* OSS licence banner (e.g. copied in from
another project) without a corresponding entry in `docs/plan/NOTICE.md` /
an explicit allowlist, since that would create an undisclosed licensing
obligation for a private repo (CONSTITUTION §9 #14, licence allowlist).

Exit codes: 0 clean, 1 violations found.
Stdlib only.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# A conservative set of phrases that indicate a pasted-in third-party licence
# banner rather than this repo's own copyright.
SPDX_RE = re.compile(r"SPDX-License-Identifier:\s*(\S+)", re.IGNORECASE)
BANNED_PATTERNS = [
    re.compile(r"Permission is hereby granted, free of charge", re.IGNORECASE),
    re.compile(r"Redistribution and use in source and binary forms", re.IGNORECASE),
]


def _matches_banned(text: str) -> bool:
    spdx_match = SPDX_RE.search(text)
    if spdx_match and spdx_match.group(1).upper() != "UNLICENSED":
        return True
    return any(p.search(text) for p in BANNED_PATTERNS)

ALLOWLIST_PATH = Path("scripts/licence-header-allowlist.txt")

SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py"}


def _tracked_source_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout
    return [
        Path(line)
        for line in out.splitlines()
        if Path(line).suffix in SOURCE_SUFFIXES
    ]


def _allowlist() -> set[str]:
    if not ALLOWLIST_PATH.exists():
        return set()
    return {
        line.strip()
        for line in ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def main() -> int:
    allowlist = _allowlist()
    violations: list[str] = []
    for path in _tracked_source_files():
        if path.as_posix() in allowlist:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        head = "\n".join(text.splitlines()[:20])
        if _matches_banned(head):
            violations.append(f"{path}: undeclared third-party licence banner")

    if violations:
        print("licence-header check failed — undeclared third-party licence banner:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        print(
            f"Add the file to {ALLOWLIST_PATH} with justification if this is intentional "
            "(CONSTITUTION §9 #14 licence allowlist).",
            file=sys.stderr,
        )
        return 1

    print("check_licence_headers: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
