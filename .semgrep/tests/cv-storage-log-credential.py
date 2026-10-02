"""Fixtures for cv-storage-log-credential (E07-X02, C-12.6)."""
import logging

logger = logging.getLogger(__name__)


def bad(dsn, password):
    logger.info("connecting", dsn)  # ruleid: cv-storage-log-credential
    logger.error("failed", extra=password)  # ruleid: cv-storage-log-credential
    logger.info(f"using {dsn}")  # ruleid: cv-storage-log-credential


def good(symbol):
    logger.info("exported", symbol)  # ok: cv-storage-log-credential
