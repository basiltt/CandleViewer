#!/usr/bin/env python3
"""GOV-008: every epic ticket must appear in its STRIDE threat model's ticket map.

For each ``docs/security/threat-models/E<nn>-*.md`` (case-insensitive) that has a
control-to-ticket section (a heading containing "ticket"), every non-epic ticket key
``E<nn>-*`` from ``docs/plan/backlog/all-tickets.json`` must be mentioned inside that
section (heading containing "ticket" up to the next ``## ``). Tickets labelled
``retired`` are skipped. A missing key is a model defect. Grouped rows like
``E22-D01 / D02`` count.

``BASELINE_GAPS`` records known pre-existing gaps (warned, not failed). It is a
shrink-only ratchet: when the live gap set is a strict subset of the baseline the
check FAILS until the stale keys are removed; new gaps beyond the baseline fail.

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
# Known pre-existing gaps per epic (follow-ups). Shrink-only: never add keys.
BASELINE_GAPS: dict[str, frozenset[str]] = {
    "E25": frozenset(
        {f"E25-D0{i}" for i in range(1, 9)}
        | {"E25-K01", "E25-T05", "E25-T06", "E25-T07", "E25-Q04", "E25-Q05"}
        | {"E25-S01", "E25-S02", "E25-S03", "E25-S04", "E25-S06"}
        | {"E25-X01"}
    ),
}


def _section(text: str) -> str | None:
    """Return the ticket-map section: heading containing 'ticket' to the next '## '."""
    m = HEADING_RE.search(text)
    if not m:
        return None
    end = re.compile(r"^## ", re.MULTILINE).search(text, m.end())
    return text[m.start() : end.start() if end else len(text)]


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


def check(
    root: Path = ROOT,
    baseline: dict[str, frozenset[str]] | None = None,
    warnings: list[str] | None = None,
) -> list[str]:
    """Return GOV-008 violation messages (empty when clean)."""
    base = BASELINE_GAPS if baseline is None else baseline
    tickets = json.loads(
        (root / "docs/plan/backlog/all-tickets.json").read_text(encoding="utf-8")
    )
    keys = [
        t["key"]
        for t in tickets
        if KEY_RE.match(t["key"]) and "retired" not in (t.get("labels") or [])
    ]
    problems: list[str] = []
    for path in sorted((root / "docs/security/threat-models").glob("*.md")):
        m = MODEL_RE.match(path.name)
        if not m:
            continue
        section = _section(path.read_text(encoding="utf-8", errors="replace"))
        if section is None:
            continue
        epic = m.group(1).upper()
        missing = {
            k for k in keys if k.startswith(epic + "-") and not _mentioned(k, section)
        }
        known = base.get(epic, frozenset())
        new = sorted(missing - known)
        if new:
            problems.append(f"GOV-008 {path.name}: ticket map missing {', '.join(new)}")
        resolved = sorted(known - missing)
        if resolved:
            problems.append(
                f"GOV-008 baseline for {epic} is stale - remove {', '.join(resolved)}"
            )
        elif missing and not new and warnings is not None:
            warnings.append(
                f"GOV-008 warning (baseline) {path.name}: missing {', '.join(sorted(missing))}"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GOV-008 threat-model ticket map")
    parser.add_argument("--repo-root", default=str(ROOT))
    args = parser.parse_args(argv)
    try:
        warnings: list[str] = []
        problems = check(Path(args.repo_root), warnings=warnings)
    except (OSError, ValueError, KeyError) as exc:
        print(f"GOV-008 internal error: {exc}", file=sys.stderr)
        return 2
    for line in warnings + problems:
        print(line)
    if problems:
        print("::error::GOV-008 threat model ticket map is incomplete")
        return 1
    print("GOV-008 ok: every epic ticket appears in its threat model")
    return 0


if __name__ == "__main__":
    sys.exit(main())
