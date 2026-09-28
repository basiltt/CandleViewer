"""OMS `Validator`/`ReadOnlyCheck` (E09-T04 AC3): the read-only degradation
gate order placement must call. Uses a fake satisfying the structural
`ReadOnlyCheck` protocol so this suite never imports `candleviewer.net`
(M14's §3 allow-list does not include it).
"""

from __future__ import annotations

import pytest

from candleviewer.oms.validator import OrderPlacementRefused, Validator


class _FakeReadOnlyCheck:
    def __init__(
        self,
        *,
        is_read_only: bool,
        reason_code: str | None = None,
        reason_text: str | None = None,
    ) -> None:
        self.is_read_only = is_read_only
        self.reason_code = reason_code
        self.reason_text = reason_text


def test_assert_order_placement_allowed_passes_when_not_read_only() -> None:
    gate = _FakeReadOnlyCheck(is_read_only=False)
    validator = Validator(read_only_gate=gate)

    validator.assert_order_placement_allowed()  # must not raise


def test_assert_order_placement_allowed_refuses_when_read_only() -> None:
    gate = _FakeReadOnlyCheck(
        is_read_only=True,
        reason_code="net.public_binding_detected",
        reason_text="off-mesh binding detected",
    )
    validator = Validator(read_only_gate=gate)

    with pytest.raises(OrderPlacementRefused) as exc_info:
        validator.assert_order_placement_allowed()

    assert exc_info.value.reason_code == "net.public_binding_detected"
    assert exc_info.value.reason_text == "off-mesh binding detected"


def test_order_placement_refused_falls_back_to_default_reason_text() -> None:
    gate = _FakeReadOnlyCheck(is_read_only=True, reason_code=None, reason_text=None)
    validator = Validator(read_only_gate=gate)

    with pytest.raises(OrderPlacementRefused) as exc_info:
        validator.assert_order_placement_allowed()

    assert exc_info.value.reason_code == "net.read_only"
    assert "read-only" in exc_info.value.reason_text.lower()
