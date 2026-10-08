"""Pair proving the autouse structlog reset (#2057): test A configures logging; test B, ordered
after it, must see pristine structlog state."""

from __future__ import annotations

import logging

import structlog
from structlog.testing import capture_logs

from candleviewer.observability.logging import configure_logging

_module_logger = structlog.get_logger("isolation-standin")


def test_a_configure_logging_leaves_state_behind() -> None:
    configure_logging(env="demo")
    # Function-local logger: a module-level one first used here would be pinned by the cache,
    # which no reset can undo (that is why production modules resolve loggers per call).
    structlog.get_logger("isolation-a").info("emitted_under_configured_logging")
    assert structlog.is_configured()
    assert structlog.contextvars.get_contextvars() == {"env": "demo"}


def test_b_state_is_pristine_after_a() -> None:
    assert not structlog.is_configured()
    assert structlog.contextvars.get_contextvars() == {}
    assert not any(type(h).__name__ == "_RawQueueHandler" for h in logging.getLogger().handlers)
    with capture_logs() as logs:
        _module_logger.info("fresh_emit")
    assert [e["event"] for e in logs] == ["fresh_emit"]
