"""Fixtures for the storage chaos suite (E07-Q04); helpers live in `_harness`."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from candleviewer.storage.cold import exporter as exporter_mod
from tests.chaos.storage._harness import Crash, Rig, chaos_table
from tests.unit.storage.cold._helpers import FakeHotSource


@pytest.fixture
def test_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CV_ENV", "test")
    try:
        yield
    finally:
        exporter_mod._TEST_HOOKS.clear()


@pytest.fixture
def arm_crash(test_env: None) -> Callable[[str], None]:
    def arm(point: str) -> None:
        def boom() -> None:
            raise Crash(point)

        exporter_mod._TEST_HOOKS[point] = boom

    return arm


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path / "cold", FakeHotSource(chaos_table(40)))
