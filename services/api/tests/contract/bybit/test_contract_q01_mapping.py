"""E08-Q02 meta-test: every E08-Q01 case owned by E08-Q02 is implemented or explicitly deferred.

Parses `qa/plans/e08-market-data-test-plan.md`, so a new owned case (or a deleted test) fails
here instead of silently reducing coverage.
"""

from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLAN = HERE.parents[4] / "qa" / "plans" / "e08-market-data-test-plan.md"
ID = re.compile(r"E08-TC-[A-Z]\d{2}")
ROW = re.compile(r"^\|\s*\**(E08-TC-[A-Z]\d{2})\**\s*\|")


def _owned_ids() -> set[str]:
    owned: set[str] = set()
    for line in PLAN.read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if m and "E08-Q02" in line.rstrip().rstrip("|").rsplit("|", 1)[-1]:
            owned.add(m.group(1))
    return owned


def _tested_ids() -> set[str]:
    found: set[str] = set()
    for path in HERE.glob("test_*.py"):
        if path.name != Path(__file__).name:
            found |= set(ID.findall(path.read_text(encoding="utf-8")))
    return found


def _deferred_ids() -> set[str]:
    out: set[str] = set()
    for line in (HERE / "E08_Q02_COVERAGE.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*(E08-TC-[A-Z]\d{2})\s*\|\s*deferred\s*->\s*#\d+\s*\|\s*\S", line)
        if m:
            out.add(m.group(1))
    return out


def test_plan_document_is_found_and_owns_a_plausible_number_of_cases() -> None:
    assert len(_owned_ids()) >= 35


def test_every_owned_case_is_tested_or_deferred_with_a_ticket() -> None:
    uncovered = _owned_ids() - _tested_ids() - _deferred_ids()
    assert not uncovered, f"E08-Q02 cases with neither a test nor a deferral: {sorted(uncovered)}"


def test_no_case_is_both_tested_and_deferred() -> None:
    both = _tested_ids() & _deferred_ids()
    assert not both, f"remove from the deferred table once implemented: {sorted(both)}"


def test_deferred_table_only_names_owned_cases() -> None:
    assert _deferred_ids() <= _owned_ids()
