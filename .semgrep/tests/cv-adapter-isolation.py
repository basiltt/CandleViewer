"""Fixtures for cv-adapter-isolation, placed under services/api/candleviewer/oms/
in the real tree conceptually; for --test we simulate a file *outside* the
bybit adapter boundary that must not mention Bybit.
Run with: python tools/ci/check_semgrep_rule_tests.py (covers cv-adapter-isolation)
"""


def place_order_bad() -> str:
    return "bybit"  # ruleid: cv-adapter-isolation


def place_order_ok() -> str:
    return "exchange"  # ok: cv-adapter-isolation
