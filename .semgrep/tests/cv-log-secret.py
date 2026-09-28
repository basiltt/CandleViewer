"""Fixtures for cv-log-secret.
Run with: semgrep --test --config .semgrep/cv-log-secret.yml .semgrep/tests
"""
import logging

logger = logging.getLogger(__name__)


def bad_log_settings(settings: object) -> None:
    logger.info("startup config", settings)  # ruleid: cv-log-secret


def bad_log_secret_field(api_key: str) -> None:
    logger.debug("signing request", api_key)  # ruleid: cv-log-secret  # lgtm[py/clear-text-logging-sensitive-data]  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.logger-credential-leak -- intentional negative fixture for cv-log-secret; never executed


def bad_log_kwarg(token: str) -> None:
    logger.info("session", extra=token)  # ruleid: cv-log-secret


def ok_log_masked(masked_id: str) -> None:
    logger.info("key added", masked_id)  # ok: cv-log-secret


def ok_log_trace(correlation_id: str) -> None:
    logger.info("request", correlation_id)  # ok: cv-log-secret
