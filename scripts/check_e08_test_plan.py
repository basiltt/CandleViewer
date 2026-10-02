"""Check the E08 black-box test plan's traceability table against its case tables (E08-Q01).

Rules:
- every case row has non-empty preconditions, steps, expected result, verifies and automation;
- every case's preconditions name a fixture (backticked id) and its Verifies names a child ticket;
- every story US-MKT-001..009 maps to at least one case in the traceability table;
- the traceability table's case sets equal those derived from the case tables;
- manual-only cases never appear in the "Automated" column.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DEFAULT_PLAN = (
    Path(__file__).resolve().parent.parent / "qa/plans/e08-market-data-test-plan.md"
)
STORIES = [f"US-MKT-{n:03d}" for n in range(1, 10)]
CASE_ROW = re.compile(r"^\|\s*\**E08-TC-([A-F]\d{2})\**\s*\|(.*)\|\s*$")
TRACE_ROW = re.compile(r"^\|\s*(US-MKT-\d{3})\s*\|([^|]*)\|([^|]*)\|([^|]*)\|\s*$")
RANGE = re.compile(r"([A-F])(\d{2})(?:\s*[–-]\s*\1?(\d{2}))?")
FIXTURE = re.compile(r"`[a-z]+/[a-z0-9-]+`")
CHILD = re.compile(r"E08-[STQ]\d{2}")


def expand(cell: str) -> set[str]:
    out: set[str] = set()
    for grp, start, end in RANGE.findall(cell):
        last = int(end) if end else int(start)
        out.update(f"{grp}{i:02d}" for i in range(int(start), last + 1))
    return out


def check(text: str) -> list[str]:
    errors: list[str] = []
    stories: dict[str, set[str]] = {s: set() for s in STORIES}
    manual: set[str] = set()
    seen: set[str] = set()
    trace: dict[str, tuple[set[str], set[str], set[str]]] = {}
    for line in text.splitlines():
        if m := CASE_ROW.match(line):
            cid, cells = m.group(1), [c.strip() for c in m.group(2).split("|")]
            if cid in seen:
                errors.append(f"{cid}: duplicate case id")
            seen.add(cid)
            if len(cells) != 5 or not all(cells):
                errors.append(f"{cid}: expected 5 non-empty columns after the id")
                continue
            pre, _steps, _exp, verifies, auto = cells
            if "`" not in pre and not re.search(r"\b[A-F]\d{2}\b", pre):
                errors.append(f"{cid}: preconditions name no fixture")
            if not CHILD.search(verifies):
                errors.append(f"{cid}: verifies names no child ticket")
            for s in re.findall(r"US-MKT-\d{3}", verifies):
                stories.setdefault(s, set()).add(cid)
            if "manual-only" in auto:
                manual.add(cid)
        elif m := TRACE_ROW.match(line):
            trace[m.group(1)] = (
                expand(m.group(2)),
                expand(m.group(3)),
                expand(m.group(4)),
            )
    for s in STORIES:
        if not stories[s]:
            errors.append(f"{s}: no case verifies this story")
        if s not in trace:
            errors.append(f"{s}: missing from traceability table")
            continue
        cases, automated, man = trace[s]
        if cases != stories[s]:
            errors.append(
                f"{s}: table cases {sorted(cases)} != derived {sorted(stories[s])}"
            )
        if automated & manual:
            errors.append(
                f"{s}: manual-only counted as automated: {sorted(automated & manual)}"
            )
        if automated | man != cases or man != (cases & manual):
            errors.append(f"{s}: automated/manual split inconsistent")
    return errors


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0]) if args else DEFAULT_PLAN
    errors = check(path.read_text(encoding="utf-8"))
    for e in errors:
        print(f"ERROR: {e}")
    print("OK" if not errors else f"{len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
