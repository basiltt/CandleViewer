"""Domain errors for the bus module (M5)."""

from __future__ import annotations


class BusError(Exception):
    """Base exception for the M5 `bus` module."""


class InvalidTopicError(BusError, ValueError):
    """Raised when a topic string violates the `{env}.{domain}.{symbol?}.{detail?}`
    grammar, or a subscriber attempts to construct a topic containing a
    wildcard segment from unvalidated input (security note, E08-T03)."""


class BusNotStartedError(BusError):
    """Raised when `publish`/`subscribe` is called before `start()` or after
    `drain()`/`stop()` has closed the bus to new work."""


class BusShuttingDownError(BusError):
    """Raised when `publish` is called after `drain()` has stopped accepting
    new publishes."""
