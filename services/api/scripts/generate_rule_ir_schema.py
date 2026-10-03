"""Regenerate (or ``--check``) the committed rule IR JSON Schema (E35-T01).

Usage: uv run python scripts/generate_rule_ir_schema.py [--check]
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

from candleviewer.rules.ir.schema import render_schema

TARGET = Path(__file__).resolve().parents[1] / "candleviewer" / "rules" / "ir" / "rule-ir.json"


def main(argv: list[str]) -> int:
    generated = render_schema()
    if "--check" in argv:
        committed = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if committed == generated:
            return 0
        sys.stderr.write(
            "rule-ir.json is stale; run scripts/generate_rule_ir_schema.py\n"
            + "".join(
                difflib.unified_diff(
                    committed.splitlines(True), generated.splitlines(True), "committed", "generated"
                )
            )
        )
        return 1
    TARGET.write_text(generated, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
