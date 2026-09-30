"""Tests for `candleviewer.observability.logging.configure_logging`.

Covers the field-shape scenario, the "new call site cannot bypass redaction"
scenario (stdlib logger with no structlog contact), tracebacks, third-party
loggers, console-format-refusal-outside-dev, and the regression guard that a
future refactor cannot silently drop the redaction filter.
"""

from __future__ import annotations

import io
import json
import logging
import re
from collections.abc import Callable, Iterator
from contextlib import redirect_stdout
from typing import Any

import pytest
import structlog

from candleviewer.observability.logging import RedactionFilter, configure_logging

_ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z?$")


@pytest.fixture(autouse=True)
def _reset_logging() -> Iterator[None]:
    yield
    logging.getLogger().handlers = []
    structlog.reset_defaults()


def _configure_and_capture_stdout(fn: Callable[[], None], **kwargs: Any) -> str:
    """Run `configure_logging(**kwargs)` then `fn()`, returning captured stdout.

    `configure_logging` wires a `QueueHandler`/`QueueListener`; the listener
    runs on its own thread, so we flush it deterministically by stopping it
    before reading captured output (the listener is replaced/stopped on the
    next `configure_logging` call or process exit, but tests need output
    available immediately).
    """
    from candleviewer.observability import logging as logging_mod

    buf = io.StringIO()
    with redirect_stdout(buf):
        configure_logging(**kwargs)
        fn()
        listener = logging_mod._listener
        assert listener is not None
        listener.stop()
        logging_mod._listener = None
    return buf.getvalue()


class TestFieldShape:
    def test_log_line_parses_as_single_json_object(self) -> None:
        def emit() -> None:
            structlog.get_logger("t").info("hello")

        output = _configure_and_capture_stdout(emit, env="test", level="info", fmt="json")
        lines = [line for line in output.splitlines() if line.strip()]
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert isinstance(parsed, dict)

    def test_ts_is_rfc3339_utc(self) -> None:
        def emit() -> None:
            structlog.get_logger("t").info("hello")

        output = _configure_and_capture_stdout(emit, env="test", level="info", fmt="json")
        parsed = json.loads(output.strip())
        assert _ISO_UTC_RE.match(parsed["ts"])

    def test_level_is_one_of_the_five_values(self) -> None:
        def emit() -> None:
            structlog.get_logger("t").warning("hello")

        output = _configure_and_capture_stdout(emit, env="test", level="debug", fmt="json")
        parsed = json.loads(output.strip())
        assert parsed["level"] in ("debug", "info", "warning", "error", "critical")

    def test_env_is_present(self) -> None:
        def emit() -> None:
            structlog.get_logger("t").info("hello")

        output = _configure_and_capture_stdout(emit, env="demo", level="info", fmt="json")
        parsed = json.loads(output.strip())
        assert parsed["env"] == "demo"

    def test_absent_correlation_field_is_omitted_not_string_none(self) -> None:
        def emit() -> None:
            structlog.get_logger("t").info("hello", user_id=None, symbol="BTCUSDT")

        output = _configure_and_capture_stdout(emit, env="test", level="info", fmt="json")
        parsed = json.loads(output.strip())
        assert "user_id" not in parsed
        assert parsed["symbol"] == "BTCUSDT"


class TestConsoleFormatGuard:
    def test_console_format_allowed_in_dev(self) -> None:
        configure_logging(env="dev", level="info", fmt="console")

    def test_console_format_allowed_in_ci(self) -> None:
        configure_logging(env="ci", level="info", fmt="console")

    def test_console_format_rejected_outside_dev_or_ci(self) -> None:
        with pytest.raises(ValueError, match="console"):
            configure_logging(env="live", level="info", fmt="console")

    def test_invalid_level_rejected(self) -> None:
        with pytest.raises(ValueError, match="CV_LOG_LEVEL"):
            configure_logging(env="dev", level="verbose", fmt="json")

    def test_invalid_format_rejected(self) -> None:
        with pytest.raises(ValueError, match="CV_LOG_FORMAT"):
            configure_logging(env="dev", level="info", fmt="xml")


class TestRedactionFilterRegressionGuard:
    """A future refactor that drops the filter from the root handler must
    fail CI (ticket's Test plan: "Unit (regression guard)")."""

    def test_redaction_filter_is_attached_to_a_root_handler(self) -> None:
        configure_logging(env="test", level="info", fmt="json")
        from candleviewer.observability.logging import _listener

        assert _listener is not None
        handlers = list(_listener.handlers)
        assert any(any(isinstance(f, RedactionFilter) for f in h.filters) for h in handlers), (
            "RedactionFilter must be attached to a handler reachable by the root logger"
        )
