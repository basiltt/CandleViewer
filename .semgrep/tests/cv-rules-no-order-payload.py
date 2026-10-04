"""Fixtures for cv-rules-no-order-payload."""


def bad() -> dict:
    return {"symbol": "BTCUSDT", "orderType": "Market"}  # ruleid: cv-rules-no-order-payload


def bad2() -> dict:
    return {"orderLinkId": "x", "qty": "1"}  # ruleid: cv-rules-no-order-payload


def ok() -> dict:
    return {"symbol": "BTCUSDT", "intent": "flatten"}  # ok: cv-rules-no-order-payload
