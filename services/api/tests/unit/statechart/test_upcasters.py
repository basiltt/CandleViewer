"""Unit tests for `candleviewer.statechart.upcasters` (E50-T02).

Covers registration, lookup, the coverage predicate, and the mandatory
no-op self-check (ticket acceptance criterion 2).
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.statechart.upcasters import (
    NoOpUpcasterError,
    UpcasterKeyError,
    get_upcaster,
    has_upcaster,
    register_upcaster,
    registered_keys,
)


def _real_upcaster(ctx: dict[str, Any]) -> dict[str, Any]:
    """A non-trivial migration: adds a field, mirroring a real chart-shape
    change (e.g. a renamed/added context key after a chart edit)."""
    out = dict(ctx)
    out["cv_migrated"] = True
    return out


def _noop_upcaster(ctx: dict[str, Any]) -> dict[str, Any]:
    return ctx


class TestRegisterUpcaster:
    def test_register_then_lookup_round_trips(self) -> None:
        register_upcaster("test.upcast.A", "hash-a1", "hash-a2", _real_upcaster)
        assert has_upcaster("test.upcast.A", "hash-a1", "hash-a2") is True
        fn = get_upcaster("test.upcast.A", "hash-a1")
        assert fn({"x": 1}) == {"x": 1, "cv_migrated": True}
        assert ("test.upcast.A", "hash-a1") in registered_keys()

    def test_noop_upcaster_is_refused(self) -> None:
        """Ticket acceptance criterion 2: 'No-op upcaster refused'."""
        with pytest.raises(NoOpUpcasterError):
            register_upcaster("test.upcast.B", "hash-b1", "hash-b2", _noop_upcaster)
        assert has_upcaster("test.upcast.B", "hash-b1", "hash-b2") is False

    def test_duplicate_registration_for_same_source_hash_rejected(self) -> None:
        register_upcaster("test.upcast.C", "hash-c1", "hash-c2", _real_upcaster)
        with pytest.raises(UpcasterKeyError):
            register_upcaster("test.upcast.C", "hash-c1", "hash-c2", _real_upcaster)

    def test_has_upcaster_false_for_unregistered_pair(self) -> None:
        assert has_upcaster("test.upcast.nope", "x", "y") is False

    def test_has_upcaster_false_when_to_hash_does_not_match(self) -> None:
        register_upcaster("test.upcast.D", "hash-d1", "hash-d2", _real_upcaster)
        assert has_upcaster("test.upcast.D", "hash-d1", "some-other-hash") is False

    def test_get_upcaster_raises_on_unknown_pair(self) -> None:
        with pytest.raises(UpcasterKeyError):
            get_upcaster("test.upcast.nope", "z")

    def test_partial_upcaster_that_drops_probe_marker_is_not_flagged_noop(self) -> None:
        """A buggy-but-not-literally-identity upcaster (e.g. one that drops
        a field rather than adding one) is not a no-op and is accepted here
        — catching *that* class of bug is the golden-snapshot test's job
        per machine, not this generic self-check's."""

        def _drops_a_field(ctx: dict[str, Any]) -> dict[str, Any]:
            out = dict(ctx)
            out.pop("nested", None)
            return out

        register_upcaster("test.upcast.E", "hash-e1", "hash-e2", _drops_a_field)
        assert has_upcaster("test.upcast.E", "hash-e1", "hash-e2") is True
