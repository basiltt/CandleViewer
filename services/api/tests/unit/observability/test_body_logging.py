"""Tests for `candleviewer.observability.body_logging.BodyLoggingGate` (SR-123)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from candleviewer.observability.body_logging import BodyLoggingGate


def test_disabled_by_default_when_until_is_none() -> None:
    gate = BodyLoggingGate(until=None)
    assert gate.enabled() is False


def test_enabled_while_before_the_time_box() -> None:
    future = datetime.now(UTC) + timedelta(hours=1)
    gate = BodyLoggingGate(until=future)
    assert gate.enabled() is True


def test_auto_expires_after_the_time_box() -> None:
    past = datetime.now(UTC) - timedelta(seconds=1)
    gate = BodyLoggingGate(until=past)
    assert gate.enabled() is False


def test_activation_callback_fires_when_a_time_box_is_set() -> None:
    calls: list[datetime] = []
    future = datetime.now(UTC) + timedelta(hours=1)
    BodyLoggingGate(until=future, on_activate=calls.append)
    assert calls == [future]


def test_activation_callback_does_not_fire_when_not_set() -> None:
    calls: list[datetime] = []
    BodyLoggingGate(until=None, on_activate=calls.append)
    assert calls == []


def test_enabled_uses_injected_clock_not_wall_clock() -> None:
    fixed_now = datetime(2026, 1, 1, tzinfo=UTC)
    until = fixed_now + timedelta(minutes=1)
    gate = BodyLoggingGate(until=until, clock=lambda: fixed_now)
    assert gate.enabled() is True
    gate_expired = BodyLoggingGate(until=until, clock=lambda: until + timedelta(seconds=1))
    assert gate_expired.enabled() is False
