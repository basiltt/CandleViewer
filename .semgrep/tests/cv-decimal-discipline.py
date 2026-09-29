"""Fixtures for cv-decimal-discipline (E08-X03): `float` used for a price
or quantity variable/parameter in the adapter/ingestion path.
Run with: python tools/ci/check_semgrep_rule_tests.py
"""

from decimal import Decimal


def place_order_bad(price: float, qty: float) -> None:  # ruleid: cv-decimal-discipline
    ...


def place_order_ok(price: Decimal, qty: Decimal) -> None:  # ok: cv-decimal-discipline
    ...
