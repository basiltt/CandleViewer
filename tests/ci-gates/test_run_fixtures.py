"""E03-Q01: pytest wrapper over `tests/ci-gates/run_fixtures.py`'s CASES so
`make ci-gate-fixture`/CI can assert every new scripted fixture matches its
expected PASS/FAIL outcome (the ticket's black-box plan, `PLAN.md` §2).

Existing fixtures owned by other tickets (coverage, contract, migrations,
gen-freshness, security severity, bypass-register) are exercised by their
own upstream suites under `scripts/tests/` / `services/api/tests/` and are
re-run, not duplicated, here — see `PLAN.md` §1 Automation column.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

CI_GATES_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CI_GATES_DIR))

from run_fixtures import CASES, FixtureCase


@pytest.mark.parametrize("case", CASES, ids=[c.case_id for c in CASES])
def test_fixture_matches_expectation(case: FixtureCase) -> None:
    observed_pass, detail = case.run()
    assert observed_pass == case.expect_pass, (
        f"{case.case_id} ({case.description}): expected "
        f"{'PASS' if case.expect_pass else 'FAIL'}, observed "
        f"{'PASS' if observed_pass else 'FAIL'} -- {detail}"
    )


def test_all_case_ids_are_unique() -> None:
    ids = [c.case_id for c in CASES]
    assert len(ids) == len(set(ids)), f"duplicate case ids: {ids}"
