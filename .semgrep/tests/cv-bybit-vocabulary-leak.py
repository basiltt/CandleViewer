"""Fixtures for cv-bybit-vocabulary-leak (E08-X03). Simulates a module
*outside* services/api/candleviewer/exchange/bybit/ that leaks Bybit-native
field/header vocabulary vs. one that stays on normalised domain names.
Run with: python tools/ci/check_semgrep_rule_tests.py
"""


def handle_order_response_bad(payload: dict) -> str:
    return payload["retCode"]  # ruleid: cv-bybit-vocabulary-leak


def handle_order_response_ok(payload: dict) -> str:
    return payload["status_code"]  # ok: cv-bybit-vocabulary-leak
