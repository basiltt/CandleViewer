"""Regenerate the corpus golden hashes - a reviewed act (E35-Q02 "golden drift" scenario).

Run from ``services/api``::

    uv run python -m tests.rules.roundtrip.update_goldens --reason "<why the hash changed>"
"""

from __future__ import annotations

import argparse
import json
import sys

from candleviewer.rules.ir import IR_HASH_VERSION, ir_hash
from tests.rules.roundtrip.test_corpus_gate import GOLDEN, RULES, load


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reason", required=True, help="written reason, copied into the PR body")
    args = ap.parse_args(argv)
    if not args.reason.strip():
        print("a non-empty --reason is required", file=sys.stderr)
        return 2
    out = {
        "ir_hash_version": IR_HASH_VERSION,
        "reason": args.reason.strip(),
        "hashes": {p.name: ir_hash(load(p)) for p in RULES},
    }
    GOLDEN.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(RULES)} golden hashes to {GOLDEN}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
