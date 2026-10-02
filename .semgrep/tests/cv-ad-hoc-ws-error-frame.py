"""Fixtures for cv-ad-hoc-ws-error-frame (E17-T05)."""


def bad():
    return {"t": "err", "p": {"code": "x"}}  # ruleid: cv-ad-hoc-ws-error-frame


def good():
    return {"t": "ok", "p": {}}  # ok: cv-ad-hoc-ws-error-frame
