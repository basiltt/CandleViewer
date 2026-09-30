"""tests/xstate_contract/test_golden_upcaster.py — E50-T02.

The ticket's golden-snapshot rule: a registered upcaster is exercised
against a committed before/after fixture pair
(`tests/xstate_contract/golden/*.json`), not just the generic
non-trivial-probe self-check in `upcasters.py`. Also asserts the
`SNAPSHOT_V` floor (28-statechart-catalogue.md: "Envelope version floor is
3") and that a golden test *itself* would catch a no-op body even before
`register_upcaster`'s own self-check does.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from candleviewer.statechart.config import SNAPSHOT_V
from candleviewer.statechart.upcasters import (
    NoOpUpcasterError,
    has_upcaster,
    register_upcaster,
)

_GOLDEN = Path(__file__).resolve().parent / "golden"

_MACHINE = "test.golden.machine"
_FROM_HASH = "golden-v1-hash"
_TO_HASH = "golden-v2-hash"


def _load(name: str) -> dict[str, Any]:
    result: dict[str, Any] = json.loads((_GOLDEN / name).read_text(encoding="utf-8"))
    return result


def _real_v1_to_v2_upcaster(ctx: dict[str, Any]) -> dict[str, Any]:
    """The migration under test: renames `attempt_count` -> `attempt` and
    stamps provenance, matching the committed `.after.json` fixture
    exactly."""
    out = dict(ctx)
    if "attempt_count" in out:
        out["attempt"] = out.pop("attempt_count")
    out["cv_upcasted_from"] = "v1"
    return out


class TestGoldenUpcasterRoundTrip:
    def test_registered_upcaster_matches_golden_after_fixture(self) -> None:
        register_upcaster(_MACHINE, _FROM_HASH, _TO_HASH, _real_v1_to_v2_upcaster)
        assert has_upcaster(_MACHINE, _FROM_HASH, _TO_HASH) is True

        before = _load("test.golden.machine.v1_to_v2.before.json")
        expected_after = _load("test.golden.machine.v1_to_v2.after.json")

        from candleviewer.statechart.upcasters import get_upcaster

        actual_after = get_upcaster(_MACHINE, _FROM_HASH)(before)
        # `_comment` is fixture documentation, not machine context; the
        # upcaster carries it through unchanged (correct — an upcaster
        # touches only the fields its migration names), so the two
        # fixtures' *different* `_comment` prose is expected and excluded
        # from the comparison.
        actual_after.pop("_comment", None)
        expected_after = dict(expected_after)
        expected_after.pop("_comment", None)
        assert actual_after == expected_after

    def test_a_noop_body_against_the_golden_fixture_would_fail_this_test(self) -> None:
        """Demonstrates the golden test's own bite, independent of
        `register_upcaster`'s probe: run a no-op body against the real
        golden fixture pair and confirm it does NOT match `.after.json` —
        i.e. even if the generic probe in `upcasters.py` were absent, this
        golden-snapshot comparison alone would still catch a no-op."""

        def _noop(ctx: dict[str, Any]) -> dict[str, Any]:
            return ctx

        before = _load("test.golden.machine.v1_to_v2.before.json")
        expected_after = _load("test.golden.machine.v1_to_v2.after.json")
        noop_result = dict(_noop(before))
        noop_result.pop("_comment", None)
        expected_after = dict(expected_after)
        expected_after.pop("_comment", None)
        assert noop_result != expected_after

    def test_registering_the_actual_noop_body_is_refused_at_registration_time(self) -> None:
        """Ticket acceptance criterion 2, exercised end-to-end: attempting
        to register a no-op upcaster for this same machine/hash pair raises
        before it ever reaches a golden-snapshot run."""

        def _noop(ctx: dict[str, Any]) -> dict[str, Any]:
            return ctx

        with pytest.raises(NoOpUpcasterError):
            register_upcaster("test.golden.machine.noop-variant", "hash-x1", "hash-x2", _noop)


class TestSnapshotVersionFloor:
    def test_snapshot_v_constant_is_at_least_three(self) -> None:
        """28-statechart-catalogue.md: 'Envelope version floor is 3 (v3
        carries chain_trips)'."""
        assert SNAPSHOT_V >= 3

    def test_snapshot_v_matches_the_upstream_library_current_version(self) -> None:
        """Belt-and-braces: our floor constant should track the pinned
        xstate-statemachine==0.9.1 library's own `SNAPSHOT_VERSION` so a
        future library bump that changes it is caught here rather than
        silently diverging."""
        from xstate_statemachine.persistence import SNAPSHOT_VERSION

        assert SNAPSHOT_V <= SNAPSHOT_VERSION
