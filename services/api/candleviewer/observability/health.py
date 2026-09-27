"""Health reporting types, re-exported at module top level for convenience.

Every module's `service.py` imports `HealthReport`/`HealthStatus` from here
(`candleviewer.observability.health`) rather than from `models` directly, so
that the public import path stays stable if the storage of these types
changes later.
"""

from __future__ import annotations

from candleviewer.observability.models import HealthReport, HealthStatus

__all__ = ["HealthReport", "HealthStatus"]
