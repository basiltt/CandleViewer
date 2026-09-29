"""Positive/negative fixtures for cv-withdrawal-endpoint-ban.
Run with: semgrep --test --config .semgrep/cv-withdrawal-endpoint-ban.yml .semgrep/tests
"""


def bad_direct_withdraw(client: object) -> None:
    client.withdraw(coin="USDT", amount="10", address="0xabc")  # ruleid: cv-withdrawal-endpoint-ban


def bad_create_withdrawal(client: object) -> None:
    client.create_withdrawal(coin="USDT")  # ruleid: cv-withdrawal-endpoint-ban


def bad_universal_transfer(client: object) -> None:
    client.create_universal_transfer(coin="USDT")  # ruleid: cv-withdrawal-endpoint-ban


def bad_raw_path(session: object) -> None:
    session.post("/v5/asset/withdraw/create", json={})  # ruleid: cv-withdrawal-endpoint-ban


def ok_place_order(client: object) -> None:
    client.place_order(symbol="BTCUSDT", side="Buy", qty="1")  # ok: cv-withdrawal-endpoint-ban


def ok_get_positions(client: object) -> None:
    client.get_positions(category="linear")  # ok: cv-withdrawal-endpoint-ban
