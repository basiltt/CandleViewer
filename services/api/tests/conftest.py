"""Shared pytest fixtures for services/api.

Provides a placeholder `AppContext`-fake fixture per E02-T02's scope; the real
composition-root `AppContext` lands in E02-T05. No network, no filesystem
access outside `tmp_path` (Constitution C-13.5/C-13.7).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest


@dataclass(frozen=True)
class FakeAppContext:
    """Stand-in for the future composition-root `AppContext`.

    Real modules (bus, exchange, storage, ...) are wired in E02-T05; this
    fake exists only so downstream tickets' tests can depend on the fixture
    name without churn once the real context lands.
    """

    environment: str = "test"


@pytest.fixture
def app_context() -> Iterator[FakeAppContext]:
    yield FakeAppContext()
