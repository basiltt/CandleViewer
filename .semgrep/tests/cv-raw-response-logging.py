"""Fixtures for cv-raw-response-logging (E08-X03): raw exchange responses,
headers or secret-shaped variables must never reach a logger, metric label
or span attribute.
Run with: python tools/ci/check_semgrep_rule_tests.py
"""


def handle_bad(logger, response) -> None:
    logger.info("got response", response)  # ruleid: cv-raw-response-logging


def handle_span_bad(span, headers) -> None:
    span.set_attribute("http.headers", headers)  # ruleid: cv-raw-response-logging


def handle_ok(logger, response) -> None:
    logger.info("request completed", status=response.status_code)  # ok: cv-raw-response-logging


def handle_underscore_logger_bad(_logger, response) -> None:
    _logger.warning("got response", response)  # ruleid: cv-raw-response-logging


def handle_fstring_bad(logger, response) -> None:
    logger.info(f"got response {response}")  # ruleid: cv-raw-response-logging


def handle_percent_format_bad(logger, response) -> None:
    logger.info("got response %s" % response)  # ruleid: cv-raw-response-logging
