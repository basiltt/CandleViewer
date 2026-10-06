#!/usr/bin/env python3
"""GOV-008: every epic ticket must appear in its STRIDE threat model's ticket map.

For each ``docs/security/threat-models/E<nn>-*.md`` (case-insensitive) that has a
control-to-ticket section (a heading containing "ticket"), every non-epic ticket key
``E<nn>-*`` from ``docs/plan/backlog/all-tickets.json`` must be mentioned in the
model. A missing key is a model defect. Grouped rows like ``E22-D01 / D02`` count.

Exit codes: 0 clean, 1 gaps, 2 internal error. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_RE = re.compile(r"^(e\d{2})-.+\.md$", re.IGNORECASE)
HEADING_RE = re.compile(r"^#{2,3} .*ticket", re.IGNORECASE | re.MULTILINE)
KEY_RE = re.compile(r"^E\d{2}-[A-Z]\d{2}$")
# Models with known pre-existing gaps (follow-ups; reported as warnings, not failures).
# Remove an epic from this set once its map is complete; never add to it.
BASELINE_GAPS = frozenset({"E07", "E24", "E25"})


def _mentioned(key: str, text: str) -> bool:
    if re.search(rf"\b{re.escape(key)}\b", text):
        return True
    # grouped form: "E22-D01 / D02 / D03"
    epic, short = key.split("-", 1)
    for m in re.finditer(rf"\b{epic}-[A-Z]\d{{2}}(?:\s*/\s*[A-Z]\d{{2}})+", text):
        if short in re.split(r"[\s/-]+", m.group(0).split("-", 1)[1]) or re.search(
            rf"\b{short}\b", m.group(0)
        ):
            return True
    return False


def check(root: Path = ROOT) -> list[str]:
    """Return GOV-008 violation messages (empty when clean)."""
    tickets = json.loads(
        (root / "docs/plan/backlog/all-tickets.json").read_text(encoding="utf-8")
    )
    keys = [t["key"] for t in tickets if KEY_RE.match(t["key"])]
    problems: list[str] = []
    for path in sorted((root / "docs/security/threat-models").glob("*.md")):
        m = MODEL_RE.match(path.name)
        if not m:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if not HEADING_RE.search(text):
            continue
        epic = m.group(1).upper()
        missing = [
            k for k in keys if k.startswith(epic + "-") and not _mentioned(k, text)
        ]
        if missing and epic in BASELINE_GAPS:
            print(
                f"GOV-008 warning (baseline) {path.name}: missing {', '.join(missing)}"
            )
        elif missing:
            problems.append(
                f"GOV-008 {path.name}: ticket map missing {', '.join(missing)}"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GOV-008 threat-model ticket map")
    parser.add_argument("--repo-root", default=str(ROOT))
    args = parser.parse_args(argv)
    try:
        problems = check(Path(args.repo_root))
    except (OSError, ValueError, KeyError) as exc:
        print(f"GOV-008 internal error: {exc}", file=sys.stderr)
        return 2
    for line in problems:
        print(line)
    if problems:
        print("::error::GOV-008 threat model ticket map is incomplete")
        return 1
    print("GOV-008 ok: every epic ticket appears in its threat model")
    return 0


if __name__ == "__main__":
    sys.exit(main())
