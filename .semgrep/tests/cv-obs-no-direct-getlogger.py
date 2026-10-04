"""Fixtures for cv-obs-no-direct-getlogger (E04-X02)."""
import logging

import structlog

bad = logging.getLogger(__name__)  # ruleid: cv-obs-no-direct-getlogger
ok = structlog.get_logger(__name__)  # ok: cv-obs-no-direct-getlogger
