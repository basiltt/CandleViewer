#!/usr/bin/env python3
"""Generates the small data table `packages/protocol/scripts/
generate-policy-rules.mjs` turns into the TS `InstrumentPolicy` port (ticket
`E08-S02`, "Client and server never disagree" scenario).

Deliberately **stdlib-only** — same constraint and rationale as
`tools/gen/export_instrument_policy_corpus.py` (see that module's docstring):
the generated-code freshness gate runs `pnpm generate` on a bare Python 3.13
`setup-python` runner with no project dependencies installed.

This script does not encode the rounding/validation *algorithm* itself (that
would be a second implementation, exactly the class of bug `US-MKT-004`
guards against) — it only publishes the stable enum values
(`FilterViolationCode`, `PriceRoundMode`, `QtyRoundMode`) so the generated TS
module's own literal union types can never drift out of sync with
`services/api/candleviewer/exchange/policy.py`. The algorithm itself is
proven identical via the shared corpus (`export_instrument_policy_corpus.py`
/ `packages/fixtures/golden/policy/corpus.json`), not via this file.

Usage: `python tools/gen/export_instrument_policy_rules.py [--check]`
`--check` prints the would-be file content to stdout instead of writing it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = REPO_ROOT / "packages" / "fixtures" / "golden" / "policy" / "rules.json"

#: Mirrors `FilterViolationCode` in `services/api/candleviewer/exchange/
#: policy.py` verbatim (same convention/comment as `VIOLATION_CODES` in
#: `export_instrument_policy_corpus.py` — keep both in sync with the Python
#: `StrEnum` member order).
VIOLATION_CODES: tuple[str, ...] = (
    "PRICE_NOT_TICK_MULTIPLE",
    "QTY_NOT_LOT_MULTIPLE",
    "QTY_BELOW_MIN",
    "QTY_ABOVE_MAX",
    "NOTIONAL_BELOW_MIN",
    "SYMBOL_NOT_TRADING",
)

#: Mirrors `PriceRoundMode` / `QtyRoundMode` in the same module. Only one
#: member each is implemented on either side of the language boundary —
#: ticket scope explicitly excludes conservative/aggressive price modes.
PRICE_ROUND_MODES: tuple[str, ...] = ("nearest",)
QTY_ROUND_MODES: tuple[str, ...] = ("down",)


def build_document() -> dict[str, Any]:
    return {
        "$schema_note": (
            "GENERATED - do not hand-edit. Regenerate with "
            "`python tools/gen/export_instrument_policy_rules.py` "
            "(also run by `pnpm --filter @candleviewer/protocol generate`). "
            "Source of truth: services/api/candleviewer/exchange/policy.py."
        ),
        "violation_codes": list(VIOLATION_CODES),
        "price_round_modes": list(PRICE_ROUND_MODES),
        "qty_round_modes": list(QTY_ROUND_MODES),
    }


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    document = build_document()
    text = json.dumps(document, indent=2, sort_keys=False, ensure_ascii=False) + "\n"

    if "--check" in argv:
        sys.stdout.write(text)
        return 0

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"[export_instrument_policy_rules] wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
