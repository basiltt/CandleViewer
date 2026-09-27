"""Lifecycle tests for `candleviewer.bus.service.BusService`."""

from __future__ import annotations

import pytest

from candleviewer.bus.models import QueuePolicy, Topic
from candleviewer.bus.service import BusService
from candleviewer.observability.health import HealthStatus


@pytest.mark.asyncio
async def test_bus_service_reports_stopped_before_start() -> None:
    service = BusService()
    assert service.health().status == HealthStatus.STOPPED


@pytest.mark.asyncio
async def test_bus_service_reports_ok_after_start(app_context: object) -> None:
    service = BusService()
    await service.start(app_context)  # type: ignore[arg-type]
    assert service.health().status == HealthStatus.OK


@pytest.mark.asyncio
async def test_bus_service_stop_drains_and_reports_stopped(app_context: object) -> None:
    service = BusService()
    await service.start(app_context)  # type: ignore[arg-type]

    topic = Topic(env="demo", domain="of", symbol="BTCUSDT", detail="trade")
    sub = service.bus.subscribe("oms", "demo.of.BTCUSDT.trade", QueuePolicy.NEVER_DROP)
    await service.bus.publish(topic, "t0")
    await sub.get()

    outstanding = await service.stop(grace_s=1.0)

    assert outstanding == {}
    assert service.health().status == HealthStatus.STOPPED
