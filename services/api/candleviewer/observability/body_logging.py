"""Body-logging time-box helper (SR-123).

`CV_LOG_BODIES_UNTIL` is an RFC 3339 instant; absent means the feature is off
(the only default in every environment, per the ticket's Definition of Done).
This module only decides *whether* logging is currently allowed and exposes a
hook point for the caller to record activation as an audit event — M24 may
depend only on M1 (`config`) per `CONSTITUTION.md` C-3.1, so it cannot import
the M19 `audit` module directly. The HTTP-edge caller (M23 `api`, which may
depend on every module's public interface) is expected to pass an
`on_activate` callback that calls into `candleviewer.audit`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

OnActivate = Callable[[datetime], None]


class BodyLoggingGate:
    """Decides whether request/response bodies may be logged right now."""

    def __init__(
        self,
        *,
        until: datetime | None,
        on_activate: OnActivate | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._until = until
        self._clock = clock or (lambda: datetime.now(UTC))
        if until is not None and on_activate is not None:
            on_activate(until)

    @property
    def until(self) -> datetime | None:
        return self._until

    def enabled(self) -> bool:
        """True only while a time-box is set and not yet expired."""
        if self._until is None:
            return False
        return self._clock() < self._until
