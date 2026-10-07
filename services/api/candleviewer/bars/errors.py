"""Domain errors for the bars module (M8)."""

from __future__ import annotations


class BarsError(Exception):
    """Base exception for the M8 `bars` module."""


class BarSpecError(BarsError, ValueError):
    """A bar spec or wire `(bar_type, param)` pair is invalid.

    Messages are human-readable sentences naming the offending field; they surface
    verbatim in SCR-042 and map to an RFC 7807 422 at the HTTP edge.
    """


class SyntheticBarPersistError(BarsError):
    """A synthetic (densified) bar reached the persistence boundary (§3.3a: never persisted)."""


class SpecCapExceeded(BarsError):
    """SR-E12-04 / BR-30: registering one more distinct spec would exceed a hard cap.

    `code` is the stable token (`spec_cap_exceeded`); the message is a sentence for SCR-042
    that names the cap, its limit and the specs currently active under it.
    """

    code = "spec_cap_exceeded"

    def __init__(self, cap: str, limit: int, active: tuple[str, ...]) -> None:
        self.cap, self.limit, self.active = cap, limit, active
        shown = ", ".join(active[:8]) + (" and more" if len(active) > 8 else "")
        super().__init__(
            f"The {cap} limit of {limit} bar series is reached; close one of the active "
            f"series ({shown or 'none'}) before opening another."
        )
