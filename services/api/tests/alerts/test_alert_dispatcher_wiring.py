"""E40-T04: the alerts service starts/stops the dispatcher; the app builds it behind the flag."""

from __future__ import annotations

from typing import Any

import pytest
from _dispatch_env import Clock, MemStore

from candleviewer.alerts.dispatcher import AlertDispatcher, default_adapters
from candleviewer.alerts.service import AlertsService


async def test_service_starts_dispatcher_before_evaluator_and_stops_it() -> None:
    clock = Clock()
    disp = AlertDispatcher(MemStore(clock), default_adapters(None), worker="w", now=clock)
    seen: list[bool] = []

    async def factory() -> Any:
        seen.append(disp._task is not None)
        return None

    svc = AlertsService()
    svc.bind(factory, disp)
    await svc.start(None)  # type: ignore[arg-type]  # ctx is unused on this path
    assert seen == [True] and svc.dispatcher is disp
    await svc.stop(1.0)
    assert disp._task is None


def test_app_dispatcher_refuses_webhook_flag_and_builds_otherwise() -> None:
    from candleviewer.app import _alert_dispatcher
    from candleviewer.observability.metrics import Metrics

    with pytest.raises(ValueError, match="E40-S03"):
        _alert_dispatcher(None, Metrics("dev"), True)  # type: ignore[arg-type]  # pg unused
    d = _alert_dispatcher(None, Metrics("dev"), False)  # type: ignore[arg-type]  # pg lazy
    assert isinstance(d, AlertDispatcher)
