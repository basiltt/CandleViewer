"""Fixtures for cv-rules-no-sensitive-log."""
import logging

import structlog

_log = logging.getLogger(__name__)
LOG = logging.getLogger("x")


def bad(input_snapshot: dict, balance: str) -> None:
    _log.info("run %s", input_snapshot)  # ruleid: cv-rules-no-sensitive-log
    _log.debug("bal %s", balance)  # ruleid: cv-rules-no-sensitive-log


class Runner:
    def bad_attr(self, equity: str, snap: dict, state: dict) -> None:
        self._log.info("eq %s", equity)  # ruleid: cv-rules-no-sensitive-log
        self.logger.debug("s %s", snap)  # ruleid: cv-rules-no-sensitive-log
        LOG.info("st %s", state)  # ruleid: cv-rules-no-sensitive-log
        _log.info("run", extra={"wallet": state})  # ruleid: cv-rules-no-sensitive-log
        structlog.get_logger().info("x", balance=equity)  # ruleid: cv-rules-no-sensitive-log


def ok(rule_id: str, count: int) -> None:
    _log.info("run %s fired %d", rule_id, count)  # ok: cv-rules-no-sensitive-log
