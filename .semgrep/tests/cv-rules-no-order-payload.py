"""Fixtures for cv-rules-no-order-payload."""


def bad() -> dict:
    return {"symbol": "BTCUSDT", "orderType": "Market"}  # ruleid: cv-rules-no-order-payload


def bad2() -> dict:
    return {"orderLinkId": "x", "qty": "1"}  # ruleid: cv-rules-no-order-payload


def bad_kwargs() -> dict:
    return dict(symbol="BTCUSDT", orderType="Market")  # ruleid: cv-rules-no-order-payload


def bad_subscript(payload: dict) -> None:
    payload["stopLoss"] = "1"  # ruleid: cv-rules-no-order-payload


def bad_snake() -> dict:
    return {"symbol": "BTCUSDT", "stop_loss": "1"}  # ruleid: cv-rules-no-order-payload


def bad_snake_kwargs() -> dict:
    return dict(order_link_id="x")  # ruleid: cv-rules-no-order-payload


def ok() -> dict:
    return {"symbol": "BTCUSDT", "intent": "flatten"}  # ok: cv-rules-no-order-payload


def ok_kwargs() -> dict:
    return dict(symbol="BTCUSDT", intent="flatten")  # ok: cv-rules-no-order-payload
