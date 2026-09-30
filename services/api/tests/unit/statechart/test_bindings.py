"""Unit tests for `candleviewer.statechart.bindings` (E50-T59).

No `xstate_statemachine` import here (CV-LINT-IMPORT) — the loader
returns plain dicts, so these tests exercise CV-C18/CV-C67 without needing
the runtime at all.
"""

from __future__ import annotations

import pytest

from candleviewer.statechart.bindings import (
    BindingLoadError,
    load_binding_maps,
    register_binding_module,
)

_GOOD = "tests.unit.statechart.bindings_fixtures.good_module"
_BAD_ACTION = "tests.unit.statechart.bindings_fixtures.bad_sync_action_module"
_BAD_GUARD = "tests.unit.statechart.bindings_fixtures.bad_async_guard_module"


def test_load_binding_maps_returns_registered_callables() -> None:
    register_binding_module("test.good", _GOOD)
    maps = load_binding_maps("test.good")
    assert "noop" in maps.actions
    assert "always_true" in maps.guards
    assert "svc" in maps.services


def test_load_binding_maps_unknown_key_raises() -> None:
    with pytest.raises(BindingLoadError):
        load_binding_maps("test.does-not-exist")


def test_load_binding_maps_rejects_sync_action() -> None:
    register_binding_module("test.bad-action", _BAD_ACTION)
    with pytest.raises(BindingLoadError, match="CV-C67"):
        load_binding_maps("test.bad-action")


def test_load_binding_maps_rejects_async_guard() -> None:
    register_binding_module("test.bad-guard", _BAD_GUARD)
    with pytest.raises(BindingLoadError, match="async def"):
        load_binding_maps("test.bad-guard")


def test_load_binding_maps_returns_fresh_dict_copies() -> None:
    register_binding_module("test.good2", _GOOD)
    first = load_binding_maps("test.good2")
    second = load_binding_maps("test.good2")
    assert first.actions is not second.actions
    assert first.actions == second.actions
