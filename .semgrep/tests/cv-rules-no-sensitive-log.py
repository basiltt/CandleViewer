"""Fixtures for cv-rules-no-sensitive-log."""
import logging

_log = logging.getLogger(__name__)


def bad(input_snapshot: dict, balance: str) -> None:
    _log.info("run %s", input_snapshot)  # ruleid: cv-rules-no-sensitive-log
    _log.debug("bal %s", balance)  # ruleid: cv-rules-no-sensitive-log


def ok(rule_id: str, count: int) -> None:
    _log.info("run %s fired %d", rule_id, count)  # ok: cv-rules-no-sensitive-log
