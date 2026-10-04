"""Fixtures for cv-obs-no-print (E04-X02)."""


def bad() -> None:
    print("hello")  # ruleid: cv-obs-no-print


def ok(log: object) -> None:
    log.info("hello")  # ok: cv-obs-no-print
