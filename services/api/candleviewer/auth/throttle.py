"""Per-IP login throttle (E09-S01 "Technical notes": "Rate limiting uses a
token bucket keyed on both user_id and source address").

The per-user side of throttling is `users.failed_login_count`/`locked_until`
(persisted, survives a restart — see `LoginService`); this module is the
*independent* per-IP counter so "one attacker cannot lock every account"
(ticket "Scope / Deliverables"). In-process only (single-process deployment,
`20-architecture.md` C4) — a restart clears it, which is acceptable because
the per-account lockout persists across restarts regardless.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

Clock = Callable[[], float]


class PerIpLoginThrottle:
    """Sliding-window counter: more than `max_attempts` failures from one
    source IP within `window_s` seconds are refused, independent of which
    usernames were tried."""

    def __init__(
        self, *, max_attempts: int = 20, window_s: float = 60.0, clock: Clock = time.monotonic
    ) -> None:
        self._max_attempts = max_attempts
        self._window_s = window_s
        self._clock = clock
        self._attempts: dict[str, deque[float]] = {}

    def is_blocked(self, source_ip: str) -> bool:
        self._evict(source_ip)
        return len(self._attempts.get(source_ip, ())) >= self._max_attempts

    def record_failure(self, source_ip: str) -> None:
        self._evict(source_ip)
        self._attempts.setdefault(source_ip, deque()).append(self._clock())

    def _evict(self, source_ip: str) -> None:
        bucket = self._attempts.get(source_ip)
        if bucket is None:
            return
        cutoff = self._clock() - self._window_s
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
