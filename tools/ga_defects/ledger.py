"""Design-QA ledger parser (schema owned by E49-D01; documented below until that lands).

CSV header: ``finding_id,severity,status,component,opened``. ``severity`` is P0..P3 and ``status``
is one of open|in-progress|fixed|accepted|wontfix. Open findings are status open|in-progress.
Malformed rows are counted and skipped, never guessed at.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

SEVERITIES = ("P0", "P1", "P2", "P3")
OPEN_STATUSES = frozenset({"open", "in-progress"})
CLOSED_STATUSES = frozenset({"fixed", "accepted", "wontfix"})
HEADER = ("finding_id", "severity", "status", "component", "opened")


@dataclass(frozen=True)
class LedgerCounts:
    open_by_severity: dict[str, int]
    malformed_rows: int


def parse_ledger(path: Path) -> LedgerCounts | None:
    """None when the ledger file does not exist (reported as missing, not as zero findings)."""
    if not path.is_file():
        return None
    counts = dict.fromkeys(SEVERITIES, 0)
    bad = 0
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None or tuple(c.strip() for c in header) != HEADER:
            raise ValueError(f"ledger header must be {','.join(HEADER)}")
        for row in reader:
            if not row:
                continue
            if len(row) != len(HEADER) or not row[0].strip():
                bad += 1
                continue
            sev, status = row[1].strip().upper(), row[2].strip().lower()
            if sev not in counts or status not in OPEN_STATUSES | CLOSED_STATUSES:
                bad += 1
                continue
            if status in OPEN_STATUSES:
                counts[sev] += 1
    return LedgerCounts(counts, bad)
