"""Tests for scripts/check_bypass_register.py (CI-PROT-004)."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from check_bypass_register import RegisterError, check_rows, load_rows, main

VALID_REGISTER = """# Branch-protection bypass register

| Actor | Scope of bypass | Justification | Review date |
|---|---|---|---|
| `bot-a` | push release commit | mechanical diff | 2026-03-01 |
| `@owner` | break-glass | emergency only | 2026-03-01 |
"""

FAR_FUTURE_REGISTER = """# Branch-protection bypass register

| Actor | Scope of bypass | Justification | Review date |
|---|---|---|---|
| `bot-a` | push release commit | mechanical diff | 2099-01-01 |
"""

SPLIT_TABLE_REGISTER = """# Branch-protection bypass register

| Actor | Scope of bypass | Justification | Review date |
|---|---|---|---|
| `bot-a` | push release commit | mechanical diff | 2026-03-01 |

| `bot-b` | break-glass | emergency only | 2026-03-15 |
"""

STALE_REGISTER = """# Branch-protection bypass register

| Actor | Scope of bypass | Justification | Review date |
|---|---|---|---|
| `bot-a` | push release commit | mechanical diff | 2020-01-01 |
"""

EMPTY_REGISTER = """# Branch-protection bypass register

No table here.
"""

MALFORMED_DATE_REGISTER = """# Branch-protection bypass register

| Actor | Scope of bypass | Justification | Review date |
|---|---|---|---|
| `bot-a` | push release commit | mechanical diff | not-a-date |
"""


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "bypass-register.md"
    p.write_text(content, encoding="utf-8")
    return p


def test_load_rows_parses_all_data_rows(tmp_path: Path) -> None:
    path = _write(tmp_path, VALID_REGISTER)
    rows = load_rows(str(path))
    assert len(rows) == 2
    assert rows[0][0] == "`bot-a`"


def test_load_rows_missing_file_raises() -> None:
    with pytest.raises(RegisterError):
        load_rows("does/not/exist.md")


def test_check_rows_clean_when_all_dates_future() -> None:
    rows = [["actor", "scope", "why", "2026-03-01"]]
    errors = check_rows(rows, dt.date(2026, 1, 1))
    assert errors == []


def test_check_rows_flags_stale_review_date() -> None:
    rows = [["actor", "scope", "why", "2020-01-01"]]
    errors = check_rows(rows, dt.date(2026, 1, 1))
    assert len(errors) == 1
    assert "CI-PROT-004" in errors[0]
    assert "stale" in errors[0]


def test_check_rows_flags_empty_register() -> None:
    errors = check_rows([], dt.date(2026, 1, 1))
    assert len(errors) == 1
    assert "no rows" in errors[0]


def test_check_rows_flags_unparseable_date() -> None:
    rows = [["actor", "scope", "why", "not-a-date"]]
    errors = check_rows(rows, dt.date(2026, 1, 1))
    assert len(errors) == 1
    assert "no parseable review date" in errors[0]


def test_check_rows_flags_malformed_row() -> None:
    errors = check_rows([["only", "two"]], dt.date(2026, 1, 1))
    assert len(errors) == 1
    assert "malformed row" in errors[0]


def test_check_rows_flags_far_future_review_date() -> None:
    rows = [["actor", "scope", "why", "2099-01-01"]]
    errors = check_rows(rows, dt.date(2026, 1, 1))
    assert len(errors) == 1
    assert "CI-PROT-004" in errors[0]
    assert "more than one quarter" in errors[0]


def test_load_rows_parses_rows_split_by_blank_line(tmp_path: Path) -> None:
    path = _write(tmp_path, SPLIT_TABLE_REGISTER)
    rows = load_rows(str(path))
    assert len(rows) == 2
    assert rows[1][0] == "`bot-b`"


def test_main_exits_zero_for_clean_register(tmp_path: Path) -> None:
    path = _write(tmp_path, VALID_REGISTER)
    assert main(["--register", str(path), "--today", "2026-01-01"]) == 0


def test_main_exits_one_for_stale_register(tmp_path: Path) -> None:
    path = _write(tmp_path, STALE_REGISTER)
    assert main(["--register", str(path), "--today", "2026-01-01"]) == 1


def test_main_exits_two_for_missing_file(tmp_path: Path) -> None:
    assert main(["--register", str(tmp_path / "nope.md"), "--today", "2026-01-01"]) == 2


def test_main_exits_one_for_empty_register(tmp_path: Path) -> None:
    path = _write(tmp_path, EMPTY_REGISTER)
    assert main(["--register", str(path), "--today", "2026-01-01"]) == 1


def test_main_exits_one_for_malformed_date(tmp_path: Path) -> None:
    path = _write(tmp_path, MALFORMED_DATE_REGISTER)
    assert main(["--register", str(path), "--today", "2026-01-01"]) == 1


def test_main_exits_one_for_far_future_review_date(tmp_path: Path) -> None:
    path = _write(tmp_path, FAR_FUTURE_REGISTER)
    assert main(["--register", str(path), "--today", "2026-01-01"]) == 1
