"""Fixtures for cv-no-float-prices (E12-X03, 23-ws-protocol.md §3.1 decimal contract).
Run with: python tools/ci/check_semgrep_rule_tests.py
"""

from decimal import Decimal

from candleviewer.bars.rows import to_double


def builder_high_bad(bar, trade):
    return max(float(bar.high), float(trade.price))  # ruleid: cv-no-float-prices


def notional_bad(row):
    return float(row.price) * row.qty  # ruleid: cv-no-float-prices


def payload_bad(r):
    return float(r["turnover"])  # ruleid: cv-no-float-prices


def turnover_bad(row):
    vwap, volume = float(row.get("vwap")), float(row.get("volume"))
    return vwap * volume  # ruleid: cv-no-float-prices


def builder_high_ok(bar, trade):
    return max(bar.high, Decimal(trade.price))  # ok: cv-no-float-prices


def store_boundary_ok(row):
    return {"price": to_double(row.price)}  # ok: cv-no-float-prices


def timeout_ok(cfg):
    return float(cfg.timeout_s) * 2  # ok: cv-no-float-prices


def to_double(value: Decimal) -> float:
    return float(value)  # ok: cv-no-float-prices
