"""Regression tests for QA defect #1578 blocker 1.

`ReadOnlyGate.subscribe()` existed but had no production caller, so a
tripped gate never published the mandatory blocking banner on the `system`
WS topic (AC3, `23-ws-protocol.md` §6). These tests fail without
`register_system_topic_subscriber` actually publishing to the bus.
"""

from __future__ import annotations

import asyncio

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy
from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.net.system_topic import register_system_topic_subscriber


async def test_gate_trip_publishes_a_critical_notice_on_the_system_topic() -> None:
    bus = Bus()
    gate = ReadOnlyGate()
    sub = bus.subscribe("test", "demo.system", QueuePolicy.CONFLATE_LATEST)
    register_system_topic_subscriber(bus=bus, env="demo", read_only_gate=gate)

    gate.trip(reason_code="net.public_binding_detected", reason_text="unsafe bind")
    await asyncio.sleep(0)  # let the scheduled publish task run

    payload = sub.get_nowait()
    assert payload["kind"] == "notice"
    assert payload["severity"] == "critical"
    assert payload["read_only"] is True
    assert payload["reason_code"] == "net.public_binding_detected"
    assert payload["message"] == "unsafe bind"


async def test_gate_clear_publishes_an_info_notice_on_the_system_topic() -> None:
    bus = Bus()
    gate = ReadOnlyGate()
    gate.trip(reason_code="net.public_binding_detected", reason_text="unsafe bind")
    sub = bus.subscribe("test", "demo.system", QueuePolicy.CONFLATE_LATEST)
    register_system_topic_subscriber(bus=bus, env="demo", read_only_gate=gate)

    from candleviewer.net.binding_check import BindingCheckResult

    passing = BindingCheckResult(
        safe=True,
        bound_addresses=("127.0.0.1:8000",),
        reason_code="net.binding_safe",
        reason_text="All listening sockets are loopback/mesh-only.",
    )
    gate.clear(check_result=passing)
    await asyncio.sleep(0)

    payload = sub.get_nowait()
    assert payload["kind"] == "notice"
    assert payload["severity"] == "info"
    assert payload["read_only"] is False


async def test_subscriber_only_publishes_to_the_configured_environment_topic() -> None:
    bus = Bus()
    gate = ReadOnlyGate()
    live_sub = bus.subscribe("test", "live.system", QueuePolicy.CONFLATE_LATEST)
    demo_sub = bus.subscribe("test", "demo.system", QueuePolicy.CONFLATE_LATEST)
    register_system_topic_subscriber(bus=bus, env="demo", read_only_gate=gate)

    gate.trip(reason_code="net.public_binding_detected", reason_text="unsafe bind")
    await asyncio.sleep(0)

    assert demo_sub.qsize() == 1
    assert live_sub.qsize() == 0
