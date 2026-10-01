"""Golden-snapshot test for the B16 S04 upcaster (CLAUDE.md §6)."""

from __future__ import annotations

from candleviewer.statechart.session_upcasters import (
    B16_FROM_HASH,
    B16_TO_HASH,
    upcast_session_v0_to_v1,
)
from candleviewer.statechart.upcasters import has_upcaster


def test_upcaster_registered_for_hash_transition() -> None:
    assert has_upcaster("session", B16_FROM_HASH, B16_TO_HASH)


def test_upcast_seeds_step_up_context_and_preserves_existing() -> None:
    old = {"session_id": "s1", "elevated_until_us": None}
    new = upcast_session_v0_to_v1(old)
    assert new == {
        "session_id": "s1",
        "elevated_until_us": None,
        "elevated_classes": {},
        "step_up_failures": 0,
        "readonly_until_us": None,
    }
    assert "elevated_classes" not in old
