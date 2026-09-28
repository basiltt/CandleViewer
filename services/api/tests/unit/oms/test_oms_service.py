"""OmsService lifecycle (E09-T04): `start()` builds `Validator` from the
injected `ReadOnlyCheck`, never importing `candleviewer.net` itself.
"""

from __future__ import annotations

from types import SimpleNamespace

from candleviewer.observability.health import HealthStatus
from candleviewer.oms.service import OmsService


async def test_start_constructs_a_validator_bound_to_the_injected_gate() -> None:
    gate = SimpleNamespace(is_read_only=False, reason_code=None, reason_text=None)
    ctx = SimpleNamespace(oms_read_only_gate=gate)
    service = OmsService()

    await service.start(ctx)

    assert service.validator is not None
    service.validator.assert_order_placement_allowed()  # does not raise
    assert service.health().status == HealthStatus.OK


async def test_stop_marks_the_service_stopped() -> None:
    gate = SimpleNamespace(is_read_only=False, reason_code=None, reason_text=None)
    ctx = SimpleNamespace(oms_read_only_gate=gate)
    service = OmsService()
    await service.start(ctx)

    await service.stop(grace_s=0.1)

    assert service.health().status == HealthStatus.STOPPED
