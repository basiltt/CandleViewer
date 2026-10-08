"""Fixtures for cv-module-level-structlog-logger (#2008)."""
import structlog
import structlog.stdlib
from structlog import get_logger
from structlog import get_logger as gl
from typing import Any

logger = structlog.get_logger(__name__)  # ruleid: cv-module-level-structlog-logger
LOGGER: Any = structlog.get_logger("x")  # ruleid: cv-module-level-structlog-logger
log = structlog.stdlib.get_logger(__name__)  # ruleid: cv-module-level-structlog-logger
bare = get_logger(__name__)  # ruleid: cv-module-level-structlog-logger
aliased = gl(__name__)  # ruleid: cv-module-level-structlog-logger
bound = structlog.get_logger(__name__).bind(a=1)  # ruleid: cv-module-level-structlog-logger


class ClassBody:
    logger = structlog.get_logger(__name__)  # ruleid: cv-module-level-structlog-logger


def _log() -> Any:
    return structlog.get_logger(__name__)  # ok: cv-module-level-structlog-logger


def per_call() -> None:
    lg = structlog.get_logger(__name__)  # ok: cv-module-level-structlog-logger
    lg.info("x")


async def per_call_async() -> None:
    lg = structlog.stdlib.get_logger(__name__)  # ok: cv-module-level-structlog-logger
    lg.info("x")


class Holder:
    def m(self) -> None:
        self.lg = structlog.get_logger(__name__)  # ok: cv-module-level-structlog-logger

        self.lg2 = get_logger(__name__).bind(a=1)  # ok: cv-module-level-structlog-logger
