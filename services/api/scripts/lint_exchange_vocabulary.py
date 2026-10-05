#!/usr/bin/env python3
"""P3/L1 lint (`docs/plan/24-internal-schemas.md` §17.4, `20-architecture.md`
P3): no exchange-specific vocabulary — `retCode`, `orderLinkId` and other
exchange camelCase field names — may appear anywhere under `candleviewer/ingestion/`
or `candleviewer/exchange/` **outside** the adapter package (C-2.2).

Exit codes: 0 clean, 1 violation(s) found (each printed as
`<path>:<line>: <token>` so CI output names the offending file/line).
Stdlib only — this must run before any lint tooling is installed.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Exchange v5 camelCase / wire vocabulary that must stay confined to the
# adapter package. Word-bounded so e.g. `order_link_id` (snake_case, the
# internal name) never false-positives.
_FORBIDDEN_TOKENS = (
    "retCode",
    "retMsg",
    "orderLinkId",
    "orderId",
    "positionIdx",
    "triggerBy",
    "triggerDirection",
    "reduceOnly",
    "closeOnTrigger",
    "tpTriggerBy",
    "slTriggerBy",
    "tpslMode",
    "timeInForce",
)
_TOKEN_RE = re.compile(r"\b(?:" + "|".join(re.escape(t) for t in _FORBIDDEN_TOKENS) + r")\b")

# Packages this rule protects: every consumer of the exchange adapter, per
# C-2.2/P3 ("everything else uses `exchange/base/` interfaces"). The
# taxonomy's own home (`exchange/base/`) is exempt from the *scan* — its
# docstrings legitimately cite exchange retCode numbers, verbatim, for
# traceability from the internal code back to the wire mapping table
# (§8.6) — but it never *uses* the vocabulary as a field/attribute name,
# which is what acceptance criterion 3 (ticket body) actually guards
# against for `candleviewer/ingestion/`.
_PROTECTED_ROOTS = ("candleviewer/ingestion",)
# The lint's own exempt root must name the adapter path it polices.
# nosemgrep: cv-adapter-isolation — B5-b, owner @CandleViewer/security, review 2026-12-31
_EXEMPT_ROOT = "candleviewer/exchange/bybit"


def _iter_python_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def find_violations(services_api_root: Path) -> list[str]:
    violations: list[str] = []
    candleviewer_root = services_api_root / "candleviewer"
    for protected in _PROTECTED_ROOTS:
        package_dir = services_api_root / protected
        if not package_dir.is_dir():
            continue
        for path in _iter_python_files(package_dir):
            rel = path.relative_to(services_api_root).as_posix()
            if rel.startswith(_EXEMPT_ROOT):
                continue
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), start=1):
                match = _TOKEN_RE.search(line)
                if match:
                    violations.append(
                        f"{rel}:{lineno}: forbidden exchange vocabulary "
                        f"{match.group(0)!r} outside the adapter package (P3/L1, "
                        f"docs/plan/24-internal-schemas.md Sec.17.4)"
                    )
    del candleviewer_root
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="services/api directory (default: parent of this script's dir)",
    )
    args = parser.parse_args(argv)
    violations = find_violations(args.root)
    for v in violations:
        print(v)
    if violations:
        print(f"\n{len(violations)} P3/L1 violation(s) found.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
