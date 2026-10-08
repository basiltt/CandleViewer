"""Cold-tier kline reader: Parquet read-through, bounded scan, path safety, timeout (#2048)."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.market import MarketDataPrincipal, make_market_router
from candleviewer.ingestion.kline_coverage import Range
from candleviewer.ingestion.kline_read import KlineReadService
from candleviewer.storage.cold import kline_reader as kr
from candleviewer.storage.cold.kline_reader import (
    ColdKlineReadTimeout,
    ColdKlineRow,
    ParquetKlineReader,
    months_between,
)
from candleviewer.storage.cold.layout import DatasetNotRegistered, DatasetRegistry
from candleviewer.storage.cold.manifest import ManifestEntry, ManifestStore, sha256_of
from candleviewer.storage.models import StreamKind

MIN = 60_000_000
H = 60 * MIN


def _us(y: int, m: int, d: int = 1) -> int:
    return int(datetime(y, m, d, tzinfo=UTC).timestamp() * 1_000_000)


def _write(root: Path, ym: str, tss: list[int], symbol: str = "BTCUSDT", iv: str = "60") -> None:
    paths = DatasetRegistry(root).resolve_partition(
        StreamKind.KLINES, partition_values={"symbol": symbol, "interval": iv, "ym": ym}
    )
    paths.partition_dir.mkdir(parents=True, exist_ok=True)
    n = len(tss)
    table = pa.table(
        {
            "ts": pa.array(tss, type=pa.timestamp("us", tz="UTC")),
            "open": [100.5] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1.0] * n,
            "turnover": [100.0] * n,
            "confirmed": [True] * n,
            "source": ["ws"] * n,
        }
    )
    f = paths.partition_dir / "part-0000.parquet"
    pq.write_table(table, f)
    ManifestStore(paths.manifests_dir).append_reconciled(
        paths.partition_dir,
        paths.root,
        ManifestEntry(
            file=f.name,
            sha256=sha256_of(f),
            row_count=n,
            source_table="klines",
            export_run_id="r",
            exported_at_us=0,
        ),
    )


class _Hot:
    def __init__(self, rows: list[ColdKlineRow] | None = None) -> None:
        self.rows = rows or []

    async def read_klines(
        self, sym: str, interval: str, rng: Range, tier: str = "auto", limit: int | None = None
    ) -> list[ColdKlineRow]:
        return [r for r in self.rows if rng.start_us <= r.ts_us < rng.end_us]


def _svc(cold: ParquetKlineReader, boundary: int, hot: _Hot | None = None) -> KlineReadService:
    return KlineReadService(hot or _Hot(), cold=cold, hot_boundary_us=lambda: boundary)


async def test_cold_only_window_served_from_parquet(tmp_path: Path) -> None:
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0 + i * H for i in range(5)])
    svc = _svc(ParquetKlineReader(DatasetRegistry(tmp_path)), _us(2026, 6))
    res = await svc.read("BTCUSDT", "60", Range(t0, t0 + 10 * H), limit=3)
    assert [r.ts_us for r in res.rows] == [t0 + 2 * H, t0 + 3 * H, t0 + 4 * H]
    assert res.sources == ["parquet"]
    assert res.rows[0].open == "100.5"


async def test_hot_wins_overlap(tmp_path: Path) -> None:
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0, t0 + H])
    hot_row = ColdKlineRow(t0 + H, "1", "1", "1", "1", "1", "1", True, "ws")
    svc = _svc(ParquetKlineReader(DatasetRegistry(tmp_path)), t0 + H, _Hot([hot_row]))
    res = await svc.read("BTCUSDT", "60", Range(t0, t0 + 3 * H))
    by_ts = {r.ts_us: r for r in res.rows}
    assert by_ts[t0 + H].open == "1"  # hot value, not the cold twin (100.5)
    assert sorted(res.sources) == ["parquet", "questdb"]
    assert len(res.rows) == 2


async def test_parquet_not_claimed_without_cold_rows(tmp_path: Path) -> None:
    _write(tmp_path, "2026-03", [_us(2026, 3)])
    svc = _svc(ParquetKlineReader(DatasetRegistry(tmp_path)), _us(2026, 9))
    res = await svc.read("BTCUSDT", "60", Range(_us(2026, 5), _us(2026, 5, 2)))
    assert res.sources == []


def test_months_between_prunes_to_window() -> None:
    assert months_between(_us(2026, 1, 31), _us(2026, 3, 2)) == ["2026-01", "2026-02", "2026-03"]
    assert months_between(_us(2026, 3), _us(2026, 4)) == ["2026-03"]
    assert months_between(5, 5) == []


async def test_only_matching_partitions_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for ym in ("2026-02", "2026-03", "2026-04"):
        _write(tmp_path, ym, [_us(int(ym[:4]), int(ym[5:]))])
    reg = DatasetRegistry(tmp_path)
    seen: list[str] = []
    orig = reg.resolve_partition

    def spy(stream: StreamKind, *, partition_values: dict[str, str]) -> Any:
        seen.append(partition_values["ym"])
        return orig(stream, partition_values=partition_values)

    monkeypatch.setattr(reg, "resolve_partition", spy)
    rows = await ParquetKlineReader(reg)("BTCUSDT", "60", Range(_us(2026, 3), _us(2026, 3, 20)))
    assert seen == ["2026-03"]
    assert len(rows) == 1


@pytest.mark.parametrize(
    ("sym", "iv"), [("../x", "60"), ("BTCUSDT", "../60"), ("BTC/USDT", "60"), ("..", "60")]
)
async def test_hostile_components_rejected_before_filesystem(
    tmp_path: Path, sym: str, iv: str
) -> None:
    reader = ParquetKlineReader(DatasetRegistry(tmp_path))
    with pytest.raises(DatasetNotRegistered):
        await reader(sym, iv, Range(_us(2026, 3), _us(2026, 4)))


def _client(svc: KlineReadService) -> TestClient:
    class _Resolver:
        def resolve(self, request: object) -> MarketDataPrincipal:
            return MarketDataPrincipal(user_id="u", permissions=frozenset({"marketdata:read"}))

    class _Cache:
        async def read_klines(self, *a: object, **k: object) -> list[object]:
            return []

    app = FastAPI()
    app.include_router(
        make_market_router(
            lambda: _Cache(),  # type: ignore[arg-type,return-value]
            principal_resolver=_Resolver(),
            read_service_provider=lambda: svc,
            symbol_listed=lambda s: s == "BTCUSDT",
        )
    )
    return TestClient(app, client=("127.0.0.1", 50000))


def test_route_traversal_symbol_422_with_no_path_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reg = DatasetRegistry(tmp_path)
    calls: list[str] = []

    def spy(*a: object, **k: object) -> None:
        calls.append("path")

    monkeypatch.setattr(reg, "resolve_partition", spy)
    svc = _svc(ParquetKlineReader(reg), 10**18)
    r = _client(svc).get(
        "/market/klines",
        params={
            "symbol": "../x",
            "interval": "60",
            "from": "2026-03-01T00:00:00Z",
            "to": "2026-03-02T00:00:00Z",
        },
    )
    assert r.status_code == 422
    assert calls == []


async def test_duckdb_timeout_is_typed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    t0 = _us(2026, 3)
    _write(tmp_path, "2026-03", [t0])
    release = threading.Event()

    def slow(*a: object, **k: object) -> list[object]:
        release.wait(2)
        return []

    monkeypatch.setattr(kr, "_read_rows", slow)
    reader = ParquetKlineReader(DatasetRegistry(tmp_path), timeout_s=0.05)
    try:
        with pytest.raises(ColdKlineReadTimeout):
            await reader("BTCUSDT", "60", Range(t0, t0 + MIN))
    finally:
        release.set()


def test_route_maps_cold_timeout_to_503(tmp_path: Path) -> None:
    class _Boom:
        async def __call__(self, *a: object) -> list[ColdKlineRow]:
            raise ColdKlineReadTimeout("slow")

    svc = KlineReadService(_Hot(), cold=_Boom(), hot_boundary_us=lambda: 10**18)
    r = _client(svc).get(
        "/market/klines",
        params={
            "symbol": "BTCUSDT",
            "interval": "60",
            "from": "2026-03-01T00:00:00Z",
            "to": "2026-03-01T01:00:00Z",
        },
    )
    assert r.status_code == 503
