"""RedactionFilter tests — the "new call site cannot bypass redaction" scenario.

`RedactionFilter` operates directly on `logging.LogRecord`s, independent of
whether `configure_logging()` has run — this is what proves a plain
`logging.getLogger(__name__)` call site (no structlog contact at all) still
gets redacted once the filter is on the handler.
"""

from __future__ import annotations

import logging

import pytest

from candleviewer.observability.logging import RedactionFilter


def _make_record(msg: str, args: tuple[object, ...] = ()) -> logging.LogRecord:
    return logging.LogRecord(
        name="httpx",
        level=logging.DEBUG,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


def test_stdlib_logger_dict_with_api_secret_is_redacted() -> None:
    record = logging.LogRecord(
        name="third_party",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="%s",
        args=({"api_secret": "CANARY-STDLIB-1"},),
        exc_info=None,
    )
    assert RedactionFilter().filter(record) is True
    assert "CANARY-STDLIB-1" not in str(record.args)


def test_stdlib_logger_plain_string_message_with_key_shaped_value_is_redacted() -> None:
    record = _make_record("using key CANARYBYBITKEY0123456789ABCDEF for signing")
    assert RedactionFilter().filter(record) is True
    assert "CANARYBYBITKEY0123456789ABCDEF" not in record.msg


def test_httpx_style_logger_name_record_is_redacted() -> None:
    record = logging.getLogger("httpx").makeRecord(
        "httpx",
        logging.DEBUG,
        __file__,
        1,
        "Authorization: Bearer CANARYBYBITKEY0123456789ABCDEF",
        (),
        None,
    )
    assert RedactionFilter().filter(record) is True
    assert "CANARYBYBITKEY0123456789ABCDEF" not in record.msg


def test_exception_traceback_text_is_redacted() -> None:
    import sys
    import traceback

    try:
        raise ValueError("api_secret=CANARYBYBITKEY0123456789ABCDEF")
    except ValueError:
        record = logging.getLogger("t").makeRecord(
            "t", logging.ERROR, __file__, 1, "boom", (), sys.exc_info()
        )
        record.exc_text = "".join(traceback.format_exception(*sys.exc_info()))

    assert RedactionFilter().filter(record) is True
    assert "CANARYBYBITKEY0123456789ABCDEF" not in (record.exc_text or "")


def test_filter_never_raises_and_drops_record_on_internal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Security notes failure mode: a redaction bug must drop the record, not crash."""
    import candleviewer.observability.logging as logging_mod

    def _boom(value: object, depth: int) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(logging_mod, "_redact_value", _boom)
    record = _make_record("hello")
    assert RedactionFilter().filter(record) is False


def test_extra_fields_on_the_record_are_also_redacted() -> None:
    record = _make_record("hello")
    record.__dict__["api_key_value"] = "irrelevant-key-name-not-exact-match"
    record.__dict__["headers"] = {"authorization": "Bearer CANARY-EXTRA"}
    assert RedactionFilter().filter(record) is True
    assert "CANARY-EXTRA" not in str(record.__dict__["headers"])
