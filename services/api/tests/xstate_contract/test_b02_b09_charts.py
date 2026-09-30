"""tests/xstate_contract/test_b02_b09_charts.py — E50-S01 contract skeletons.

Gherkin "Every B2-B9 chart loads under the factory": for each chart,
`registry.validate` + `factory.build` succeed and `machine_hash` matches the
committed `machine_hashes.lock`. Runs under `-W error::RuntimeWarning` in CI
(a dropped action coroutine would surface as a RuntimeWarning, CV-C67).
"""

from __future__ import annotations

import importlib

import pytest
from xstate_statemachine import SimulatedClock

from candleviewer.statechart import build
from candleviewer.statechart.bindings import load_binding_maps
from candleviewer.statechart.lock import DEFAULT_LOCK_PATH, load_lock
from candleviewer.statechart.registry import Registry, validate

B02_B09: tuple[tuple[int, str], ...] = (
    (2, "trade_group"),
    (3, "leg"),
    (4, "oco"),
    (5, "iceberg"),
    (6, "twap"),
    (7, "chase"),
    (9, "rule_instance"),
)

_MANDATORY_ROOT = {
    "strictConfig": True,
    "strictTargets": True,
    "strict": True,
    "onUnhandled": "defer",
    "actionErrorPolicy": "rollback",
    "maxIterations": 500,
}


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry()


@pytest.mark.parametrize(("num", "key"), B02_B09)
def test_chart_has_mandatory_root_block(registry: Registry, num: int, key: str) -> None:
    chart = registry.get(key)
    for name, value in _MANDATORY_ROOT.items():
        assert chart[name] == value, f"B{num} {key}: {name}"
    assert chart["guardErrorPolicy"] in {"raise", "continue"}
    validate(chart)


@pytest.mark.parametrize(("num", "key"), B02_B09)
def test_chart_hash_matches_lock(registry: Registry, num: int, key: str) -> None:
    locked = load_lock(DEFAULT_LOCK_PATH)
    assert registry.hash(key) == locked[key]["hash"]


@pytest.mark.parametrize(("num", "key"), B02_B09)
def test_bindings_cover_every_chart_name(num: int, key: str) -> None:
    importlib.import_module(f"candleviewer.statechart.bindings.b{num:02d}_{key}")
    maps = load_binding_maps(key)  # asserts CV-C67 coroutine shape
    assert maps.actions or maps.guards or maps.services


@pytest.mark.parametrize(("num", "key"), B02_B09)
async def test_chart_builds_under_factory(registry: Registry, num: int, key: str) -> None:
    importlib.import_module(f"candleviewer.statechart.bindings.b{num:02d}_{key}")
    result = await build(key, clock=SimulatedClock(), lane="order", registry=registry)
    try:
        assert result.machine_hash == load_lock(DEFAULT_LOCK_PATH)[key]["hash"]
    finally:
        await result.interpreter.stop()
