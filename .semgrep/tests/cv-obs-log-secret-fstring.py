"""Fixtures for cv-obs-log-secret-fstring (E04-X02)."""


def bad_fstring(log: object, api_secret: str) -> None:
    log.info(f"signing with {api_secret}")  # ruleid: cv-obs-log-secret-fstring


def bad_percent(log: object, session_token: str) -> None:
    log.warning("token %s" % session_token)  # ruleid: cv-obs-log-secret-fstring


def ok_structured(log: object, masked_id: str) -> None:
    log.info("key added", masked_id=masked_id)  # ok: cv-obs-log-secret-fstring


def ok_fstring_benign(log: object, symbol: str) -> None:
    log.info(f"subscribed {symbol}")  # ok: cv-obs-log-secret-fstring
