"""Fixtures for the E08-Q03 ingestion chaos suite (no network, virtual clock)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from tests.chaos.ingestion._rig import Rig

#: The suite's fixed seed (AC: "two consecutive runs with the same seed ...").
SEED = 20261006


@pytest.fixture
async def rig() -> AsyncIterator[Rig]:
    r = Rig(seed=SEED)
    await r.start()
    try:
        yield r
    finally:
        await r.stop()
