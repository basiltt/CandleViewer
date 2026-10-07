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
