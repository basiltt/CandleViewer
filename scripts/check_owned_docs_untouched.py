#!/usr/bin/env python3
"""GOV-007: owned governance documents must not carry tool-injected blocks.

`AGENTS.md` and `CLAUDE.md` are single-owner documents (CONSTITUTION C-16.5).
Since turbo 2.11 the `turbo` CLI appends a managed ``turborepo-agent-rules``
block to ``AGENTS.md`` whenever it detects an AI agent (see #1907). The repo
opts out via ``"agentGuidance": false`` in ``turbo.json``; this check makes
the opt-out load-bearing by failing if the marker ever appears, and if the
opt-out is ever removed from ``turbo.json``.

Exit codes: 0 clean, 1 violation(s), 2 internal error. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNED_DOCS = ("AGENTS.md", "CLAUDE.md")
MARKERS = ("<!-- BEGIN:turborepo-agent-rules -->", "<!-- END:turborepo-agent-rules -->")


def check(root: Path = ROOT) -> list[str]:
    """Return a list of GOV-007 violation messages (empty when clean)."""
    problems: list[str] = []
    for name in OWNED_DOCS:
        path = root / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in MARKERS:
            if marker in text:
                problems.append(
                    f"GOV-007 {name} contains tool-injected marker {marker!r} (#1907)"
                )
                break
    turbo = root / "turbo.json"
    if turbo.exists():
        try:
            config = json.loads(turbo.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            problems.append(f"GOV-007 turbo.json is not valid JSON: {exc}")
            return problems
        if config.get("agentGuidance") is not False:
            problems.append(
                'GOV-007 turbo.json must set "agentGuidance": false (#1907)'
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GOV-007 owned-docs injection check")
    parser.add_argument(
        "--repo-root",
        default=str(ROOT),
        help="repository root (default: this checkout)",
    )
    args = parser.parse_args(argv)
    try:
        problems = check(Path(args.repo_root))
    except OSError as exc:  # pragma: no cover - defensive
        print(f"GOV-007 internal error: {exc}", file=sys.stderr)
        return 2
    for line in problems:
        print(line)
    if problems:
        print(
            "::error::GOV-007 owned docs carry tool-injected content or the turbo opt-out is missing"
        )
        return 1
    print(
        "GOV-007 ok: no tool-injected blocks in owned docs; turbo agentGuidance opted out"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
