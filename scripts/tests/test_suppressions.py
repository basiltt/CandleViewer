"""Unit tests for the shared suppression grammar (tools/ci/suppressions.py)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.suppressions import (
    REVIEW_MAX_DAYS,
    field_problems,
    parse_nosemgrep,
    rule_matches,
)

TODAY = date(2026, 10, 6)


def test_parse_splits_rule_list_and_keeps_rest() -> None:
    (m,) = parse_nosemgrep("# nosemgrep: a, b c reason=x owner=@o review=2026-12-31")
    assert m.rules == ("a", "b", "c")
    assert "owner=@o" in m.rest


def test_rule_match_is_exact_never_prefix() -> None:
    assert rule_matches("pkg.cv-adapter", ("cv-adapter",))
    assert rule_matches("pkg.cv-adapter", ("pkg.cv-adapter",))
    assert not rule_matches("cv-adapter", ("cv-adapter-isolation-other",))
    assert not rule_matches("cv-log-secret", ("cv-log",))


def test_valid_fields_pass() -> None:
    assert field_problems("reason=x owner=@a/b-c review=2026-12-31", TODAY) == []


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("owner=@a review=2026-12-31", "missing reason"),
        ("reason=x owner=a review=2026-12-31", "owner"),
        ("reason=x owner=@ review=2026-12-31", "owner"),
        ("reason=x owner=@a review=2026-13-45", "YYYY-MM-DD"),
        ("reason=x owner=@a review=2026-10-05", "expired"),
        ("reason=x owner=@a review=2099-01-01", "expiry too far"),
        ("myreason=x owner=@a review=2026-12-31", "missing reason"),
    ],
)
def test_bad_fields_block(text: str, needle: str) -> None:
    assert any(needle in p for p in field_problems(text, TODAY))


def test_cap_is_configurable() -> None:
    assert REVIEW_MAX_DAYS == 180
    assert field_problems("reason=x owner=@a review=2026-10-16", TODAY, max_days=5)
