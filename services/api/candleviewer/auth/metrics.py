"""Prometheus metrics for session lifetime (E09-S03 "Observability").

Labels are closed sets (revocation `reason` is normalised by
`normalise_reason`) so cardinality stays bounded.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

auth_sessions_active = Gauge(
    "auth_sessions_active", "Live (unrevoked) sessions minted by this process."
)
auth_session_revocations_total = Counter(
    "auth_session_revocations_total", "Sessions revoked, by reason.", ["reason"]
)
auth_refresh_total = Counter("auth_refresh_total", "Successful refresh-token rotations.")
auth_refresh_reuse_total = Counter(
    "auth_refresh_reuse_total", "Rotated refresh tokens presented again (family revoked)."
)
auth_idle_locks_total = Counter(
    "auth_idle_locks_total", "Requests refused because the session was idle-locked."
)
auth_revocation_latency_seconds = Histogram(
    "auth_revocation_latency_seconds",
    "Seconds from session revocation to its WebSocket connection being closed.",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

_KNOWN_REASONS = frozenset(
    {
        "logout",
        "logout_all",
        "rotated",
        "rotation_reuse",
        "expired",
        "idle",
        "admin",
        "user_revoked",
        "locked",
        "timeout",
        "unlock_attempts_exceeded",
    }
)


def normalise_reason(reason: str | None) -> str:
    """Clamp a free-form revocation reason to the closed label set."""
    return reason if reason in _KNOWN_REASONS else "other"
