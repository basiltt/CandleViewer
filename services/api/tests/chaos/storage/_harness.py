"""Shared harness for the storage chaos suite (E07-Q04, C-13.6).

Every scenario follows arrange -> inject -> assert(data) -> assert(signals)
-> assert(health) -> recover -> assert(recovery) with cleanup in `finally`.
Crash points use the exporter's test-only hooks, which are inert unless
`CV_ENV=test`.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa

from candleviewer.storage.cold.exporter import ColdExporter
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.manifest import ManifestEntry, ManifestStore
from tests.unit.storage.cold._helpers import (
    DAY_START_US,
    FakeHotSource,
    RecordingSink,
    fixed_clock,
)

PART = Path("trades") / "symbol=BTCUSDT" / "dt=2026-10-17"


def chaos_table(n: int) -> pa.Table:
    """Trades with a `trade_id` so the natural key (ts, symbol, trade_id) is complete."""
    return pa.table(
        {
            "ts": pa.array([DAY_START_US + i for i in range(n)], type=pa.int64()),
            "symbol": pa.array(["BTCUSDT"] * n, type=pa.string()),
            "trade_id": pa.array([f"t{i}" for i in range(n)], type=pa.string()),
            "price": pa.array([65000.0] * n, type=pa.float64()),
            "size": pa.array([0.01] * n, type=pa.float64()),
            "notional": pa.array([650.0] * n, type=pa.float64()),
            "side": pa.array(["Buy"] * n, type=pa.string()),
        }
    )


class Crash(BaseException):
    """SIGKILL stand-in: a BaseException no handler under test may swallow."""


class Rig:
    def __init__(self, root: Path, source: FakeHotSource) -> None:
        self.root, self.source = root, source
        self.sink = RecordingSink()
        self.registry = DatasetRegistry(root)

    def exporter(self) -> ColdExporter:
        return ColdExporter(self.registry, self.source, clock=fixed_clock, events=self.sink)

    def entries(self) -> list[ManifestEntry]:
        return ManifestStore(self.root / "_manifests").read(self.root / PART, self.root)

    def codes(self) -> list[tuple[str, str]]:
        return [(s, c) for s, c, _ in self.sink.events]
