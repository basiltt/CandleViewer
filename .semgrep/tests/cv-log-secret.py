"""Fixtures for cv-log-secret.
Run with: python tools/ci/check_semgrep_rule_tests.py (covers cv-log-secret)
"""
import logging

logger = logging.getLogger(__name__)


def bad_log_settings(settings: object) -> None:
    logger.info("startup config", settings)  # ruleid: cv-log-secret


def bad_log_secret_field(api_key: str) -> None:
    logger.debug("signing request", api_key)  # ruleid: cv-log-secret


def bad_log_kwarg(token: str) -> None:
    logger.info("session", extra=token)  # ruleid: cv-log-secret


def ok_log_masked(masked_id: str) -> None:
    logger.info("key added", masked_id)  # ok: cv-log-secret


def ok_log_trace(correlation_id: str) -> None:
    logger.info("request", correlation_id)  # ok: cv-log-secret
