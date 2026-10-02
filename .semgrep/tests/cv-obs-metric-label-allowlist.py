"""Fixtures for cv-obs-metric-label-allowlist (E04-X02)."""


def bad(reg: object) -> None:
    reg.counter("cv_x_total", "help", ("account_id",))  # ruleid: cv-obs-metric-label-allowlist


def ok(reg: object) -> None:
    reg.counter("cv_y_total", "help", ("symbol", "result"))  # ok: cv-obs-metric-label-allowlist
