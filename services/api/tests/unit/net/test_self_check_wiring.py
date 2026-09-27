"""End-to-end wiring: BindingSelfCheck -> ReadOnlyGate + net_binding_safe.

Covers the acceptance criteria that a public/off-mesh binding actually
degrades the app (trips the gate) and that gauge drift is observable,
rather than only asserting the self-check's own return value in isolation.
"""

from __future__ import annotations

from candleviewer.net.binding_check import (
    BindingSelfCheck,
    apply_self_check_result,
)
from candleviewer.net.cidr import CidrAllowList
from candleviewer.net.read_only_gate import ReadOnlyGate

MESH_CIDR = "100.64.0.0/10"


class _FakeGauge:
    def __init__(self) -> None:
        self.value: float | None = None

    def set(self, value: float) -> None:
        self.value = value


def test_public_binding_trips_the_gate_and_zeros_the_gauge() -> None:
    check = BindingSelfCheck(address_enumerator=lambda: ["0.0.0.0:8000"])
    gate = ReadOnlyGate()
    gauge = _FakeGauge()

    apply_self_check_result(check.run(), read_only_gate=gate, gauge=gauge)

    assert gate.is_read_only is True
    assert gate.reason_code == "net.public_binding_detected"
    assert gauge.value == 0


def test_off_mesh_lan_binding_trips_the_gate() -> None:
    check = BindingSelfCheck(
        address_enumerator=lambda: ["192.168.1.50:8000"],
        allow_list=CidrAllowList([MESH_CIDR]),
    )
    gate = ReadOnlyGate()

    apply_self_check_result(check.run(), read_only_gate=gate)

    assert gate.is_read_only is True
    assert gate.reason_code == "net.off_mesh_binding_detected"


def test_safe_binding_clears_a_previously_tripped_gate_and_sets_gauge_to_one() -> None:
    gate = ReadOnlyGate()
    gate.trip(reason_code="net.public_binding_detected", reason_text="stale")
    gauge = _FakeGauge()
    check = BindingSelfCheck(address_enumerator=lambda: ["127.0.0.1:8000"])

    apply_self_check_result(check.run(), read_only_gate=gate, gauge=gauge)

    assert gate.is_read_only is False
    assert gauge.value == 1


def test_safe_binding_on_an_already_writable_gate_is_a_noop() -> None:
    gate = ReadOnlyGate()
    check = BindingSelfCheck(address_enumerator=lambda: ["127.0.0.1:8000"])

    apply_self_check_result(check.run(), read_only_gate=gate)

    assert gate.is_read_only is False


def test_drift_after_resume_is_caught_by_a_second_run() -> None:
    """Simulates the hourly re-check reacting to a binding that changed."""
    bound: list[str] = ["127.0.0.1:8000"]
    check = BindingSelfCheck(address_enumerator=lambda: list(bound))
    gate = ReadOnlyGate()
    gauge = _FakeGauge()

    apply_self_check_result(check.run(), read_only_gate=gate, gauge=gauge)
    assert gate.is_read_only is False
    assert gauge.value == 1

    bound.clear()
    bound.append("0.0.0.0:8000")
    apply_self_check_result(check.run(), read_only_gate=gate, gauge=gauge)

    assert gate.is_read_only is True
    assert gauge.value == 0
