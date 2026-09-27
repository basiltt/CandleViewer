"""Unit tests for ReadOnlyGate (E09-T04)."""

from __future__ import annotations

from candleviewer.net.read_only_gate import ReadOnlyGate


def test_gate_defaults_to_writable() -> None:
    gate = ReadOnlyGate()
    assert gate.is_read_only is False


def test_gate_trip_sets_read_only_and_reason() -> None:
    gate = ReadOnlyGate()
    gate.trip(reason_code="net.public_binding_detected", reason_text="bad bind")
    assert gate.is_read_only is True
    assert gate.reason_code == "net.public_binding_detected"
    assert gate.reason_text == "bad bind"


def test_gate_clear_restores_writable_state() -> None:
    gate = ReadOnlyGate()
    gate.trip(reason_code="x", reason_text="y")
    gate.clear()
    assert gate.is_read_only is False
    assert gate.reason_code is None
    assert gate.reason_text is None
