"""Per-call structlog lookup shared by the ingestion modules.

`cache_logger_on_first_use=True` pins a module-level `structlog.get_logger()` to the processor
chain live at first use; after `configure_logging()` runs again, its events escape
`structlog.testing.capture_logs()` (order-dependent flakes: #1898, #1921, #1979, #2004).
Emit sites call `get_logger(__name__)` each time. Never call it on a per-frame hot path.
"""

from __future__ import annotations

import structlog


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Resolve a fresh logger bound to the current structlog configuration."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]  # structlog returns Any
