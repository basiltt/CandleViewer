#!/usr/bin/env python3
"""E17-T01: generate Python constants for ``23-ws-protocol.md`` section 6 + the envelope enums.

Output: ``packages/protocol/generated/ws_constants.py`` (committed; never hand-edit).
Topic patterns come from the section 6 tables, frame types / encodings from the
envelope schema in ``ws-schemas.json``. Deterministic; stdlib only.

Usage: ``python tools/contracts/gen_ws_constants.py [--check]``
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MD = REPO / "docs" / "plan" / "23-ws-protocol.md"
BUNDLE = REPO / "packages" / "protocol" / "ws-schemas.json"
OUT = REPO / "packages" / "protocol" / "generated" / "ws_constants.py"
ENVELOPE = "cv://ws/v1/envelope.schema.json"
S6 = re.compile(r"^## 6\. Topic catalogue.*?(?=^## 7\.)", re.MULTILINE | re.DOTALL)
ROW = re.compile(r"^\|\s*`([a-z_]+(?:\.[^`|]*)?)`\s*\|", re.MULTILINE)
HEADER = '''"""GENERATED FILE - DO NOT EDIT BY HAND.

Generator: tools/contracts/gen_ws_constants.py (E17-T01). Sources:
docs/plan/23-ws-protocol.md section 6 and packages/protocol/ws-schemas.json.
Edit the Markdown and run `make gen`.
"""

from __future__ import annotations

'''


def topic_patterns(markdown: str) -> list[str]:
    m = S6.search(markdown)
    if m is None:
        raise ValueError("could not locate section 6")
    seen: list[str] = []
    for row in ROW.finditer(m.group(0)):
        if row.group(1) not in seen:
            seen.append(row.group(1))
    return seen


def render(markdown: str, bundle: dict[str, object]) -> str:
    schemas = bundle["schemas"]
    assert isinstance(schemas, dict)
    props = schemas[ENVELOPE]["properties"]
    frame_types = list(props["t"]["enum"])
    encodings = list(props["e"]["enum"])
    topics = topic_patterns(markdown)
    if not topics:
        raise ValueError("no topic patterns found in section 6")

    def tup(name: str, values: list[str]) -> str:
        body = "".join(f"    {json.dumps(v)},\n" for v in values)
        return f"{name}: tuple[str, ...] = (\n{body})\n\n"

    families = sorted({t.split(".")[0] for t in topics})
    out = HEADER
    out += tup("FRAME_TYPES", frame_types)
    out += tup("ENCODINGS", encodings)
    out += tup("TOPIC_PATTERNS", topics)
    out += tup("TOPIC_FAMILIES", families)
    return out.rstrip("\n") + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    text = render(MD.read_text(encoding="utf-8"), json.loads(BUNDLE.read_text(encoding="utf-8")))
    if args.check:
        cur = OUT.read_bytes().decode("utf-8") if OUT.exists() else ""
        if cur != text:
            print(f"[gen_ws_constants] {OUT} is stale; run `make gen`.", file=sys.stderr)
            return 1
        print("[gen_ws_constants] OK")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(text.encode("utf-8"))
    print(f"[gen_ws_constants] wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
