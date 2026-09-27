"""Tests for `scripts/lint_exchange_vocabulary.py` (P3/L1, E08-T01
acceptance criterion 3: "a PR referencing `retCode` or `orderLinkId` in
`candleviewer/ingestion/` must fail the P3 lint check, naming the offending
file/line/principle")."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVICES_API_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVICES_API_ROOT / "scripts"))

from lint_exchange_vocabulary import find_violations, main  # noqa: E402


def test_find_violations_on_clean_tree_is_empty() -> None:
    assert find_violations(SERVICES_API_ROOT) == []


def test_main_on_clean_tree_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(SERVICES_API_ROOT)]) == 0


def test_leaked_ret_code_in_ingestion_fails_naming_file_line_principle(
    tmp_path: Path,
) -> None:
    offender = SERVICES_API_ROOT / "candleviewer" / "ingestion" / "_p3_test_leak.py"
    offender.write_text(
        "# leaked Bybit vocabulary for the P3/L1 negative test\n"
        "def handle(payload: dict) -> None:\n"
        "    ret_code = payload['retCode']\n"
        "    print(ret_code)\n",
        encoding="utf-8",
    )
    try:
        violations = find_violations(SERVICES_API_ROOT)
    finally:
        offender.unlink()
    matches = [v for v in violations if "_p3_test_leak.py" in v]
    assert len(matches) == 1
    assert "_p3_test_leak.py:3:" in matches[0]
    assert "retCode" in matches[0]
    assert "P3/L1" in matches[0]


def test_leaked_order_link_id_in_ingestion_is_caught(tmp_path: Path) -> None:
    offender = SERVICES_API_ROOT / "candleviewer" / "ingestion" / "_p3_test_leak2.py"
    offender.write_text("order_link_id = payload['orderLinkId']\n", encoding="utf-8")
    try:
        violations = find_violations(SERVICES_API_ROOT)
    finally:
        offender.unlink()
    matches = [v for v in violations if "_p3_test_leak2.py" in v]
    assert len(matches) == 1
    assert "orderLinkId" in matches[0]


def test_bybit_adapter_package_is_exempt(tmp_path: Path) -> None:
    bybit_dir = SERVICES_API_ROOT / "candleviewer" / "exchange" / "bybit"
    offender = bybit_dir / "_p3_test_allowed.py"
    offender.write_text("ret_code = payload['retCode']\n", encoding="utf-8")
    try:
        violations = find_violations(SERVICES_API_ROOT)
    finally:
        offender.unlink()
    assert not any("_p3_test_allowed.py" in v for v in violations)


def test_main_prints_violations_and_returns_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    offender = SERVICES_API_ROOT / "candleviewer" / "ingestion" / "_p3_test_leak3.py"
    offender.write_text("x = payload['retCode']\n", encoding="utf-8")
    try:
        exit_code = main(["--root", str(SERVICES_API_ROOT)])
    finally:
        offender.unlink()
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "_p3_test_leak3.py:1:" in out
