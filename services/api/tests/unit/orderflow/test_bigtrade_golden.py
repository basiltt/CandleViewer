"""Golden tests on the recorded tape (E08-T05 corpus via `tests._corpus`; no network).

AC "Notional threshold flags exactly the right prints": flagged ids == an independent DuckDB
query over a Parquet file of the same window (`tmp_path` only). AC "Clustering is deterministic"
and the reviewers' replay-determinism ask: identical clusters and identical threshold/advisory
streams across different batch splits; the replay engine reproduces the live stream."""

from __future__ import annotations

import random
from decimal import Decimal
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from candleviewer.orderflow.bigtrade import BigTradeEngine
from candleviewer.orderflow.bigtrade_models import (
    BigTradeAdvisoryEvent,
    BigTradeConfig,
    BigTradeEvent,
    BigTradeOutput,
    BigTradeThresholdEvent,
    TradeClusterEvent,
)
from tests._corpus import TICKS
from tests.unit.orderflow._bigtrade_helpers import recorded_prints

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def _run(symbol: str, cfg: BigTradeConfig, seed: int | None) -> list[BigTradeOutput]:
    prints = recorded_prints(symbol)
    eng = BigTradeEngine(symbol, TICKS[symbol], cfg)
    if seed is None:
        return eng.process(prints) + eng.flush()
    rng = random.Random(seed)  # noqa: S311 - seeded, reproducible batch splits
    out: list[BigTradeOutput] = []
    i = 0
    while i < len(prints):
        n = rng.randint(1, 40)
        out += eng.process(prints[i : i + n])
        i += n
    return out + eng.flush()


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_golden_notional_flags_equal_duckdb_parquet_query(symbol: str, tmp_path: Path) -> None:
    prints = recorded_prints(symbol)
    threshold = sorted(p.notional for p in prints)[int(len(prints) * 0.9)]  # non-trivial cut
    path = tmp_path / "trades.parquet"
    pq.write_table(
        pa.table(
            {
                "trade_id": [p.trade_id for p in prints],
                "price": [str(p.price) for p in prints],
                "qty": [str(p.qty) for p in prints],
            }
        ),
        path,
    )
    rows = duckdb.execute(
        "SELECT trade_id FROM read_parquet(?) "
        "WHERE CAST(price AS DECIMAL(38,10)) * CAST(qty AS DECIMAL(38,10)) "
        ">= CAST(? AS DECIMAL(38,10))",
        [path.as_posix(), str(threshold)],
    ).fetchall()
    expected = {r[0] for r in rows}
    out = _run(symbol, BigTradeConfig(mode="notional", value=threshold), None)
    assert {e.trade_id for e in out if isinstance(e, BigTradeEvent)} == expected
    assert expected  # the cut is non-trivial


def _cluster_key(out: list[BigTradeOutput]) -> list[tuple[object, ...]]:
    return [
        (
            c.cluster_id,
            c.trade_id_count,
            c.trade_ids,
            c.total_qty,
            c.first_ts_event,
            c.first_ts_event // 60_000_000,
        )  # attributed 1 m bar
        for c in out
        if isinstance(c, TradeClusterEvent)
    ]


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_golden_clustering_identical_across_batch_splits(symbol: str) -> None:
    cfg = BigTradeConfig(value=Decimal("0"), cluster_window_ms=250, cluster_tolerance_ticks=1)
    base = _cluster_key(_run(symbol, cfg, None))
    assert base and any(int(str(k[1])) > 1 for k in base)  # the corpus does produce merges
    for seed in (1, 2, 3):
        assert _cluster_key(_run(symbol, cfg, seed)) == base


def _stream(out: list[BigTradeOutput]) -> list[str]:
    return [
        e.model_dump_json()
        for e in out
        if isinstance(e, BigTradeThresholdEvent | BigTradeAdvisoryEvent)
    ]


@pytest.mark.parametrize(
    "cfg",
    [
        BigTradeConfig(mode="percentile", value=Decimal("99"), percentile_window_ms=3_600_000),
        BigTradeConfig(mode="notional", value=Decimal("1000")),  # over-flags -> advisory
    ],
)
def test_golden_threshold_and_advisory_streams_identical_across_splits(
    cfg: BigTradeConfig,
) -> None:
    base = _stream(_run("BTCUSDT", cfg, None))
    assert base
    for seed in (11, 12):
        assert _stream(_run("BTCUSDT", cfg, seed)) == base


def test_golden_overflag_advisory_on_recorded_tape() -> None:
    out = _run("BTCUSDT", BigTradeConfig(mode="notional", value=Decimal("1000")), None)
    (adv,) = [e for e in out if isinstance(e, BigTradeAdvisoryEvent)]
    assert adv.flagged_fraction > Decimal("0.2") and adv.suggested_value > Decimal("1000")


def test_golden_replay_reproduces_recorded_threshold_stream() -> None:
    cfg = BigTradeConfig(mode="percentile", value=Decimal("99"))
    live = _run("BTCUSDT", cfg, None)
    recorded = [e for e in live if isinstance(e, BigTradeThresholdEvent | BigTradeAdvisoryEvent)]
    rep = BigTradeEngine("BTCUSDT", TICKS["BTCUSDT"], cfg, source="replay", recorded=recorded)
    rep.process(recorded_prints("BTCUSDT"))
    assert rep.replay_mismatches == 0


def test_golden_reconnect_duplicates_counted_once() -> None:
    prints = recorded_prints("ETHUSDT", kind="reconnect")
    assert len({p.trade_id for p in prints}) < len(prints)  # corpus carries duplicates
    eng = BigTradeEngine("ETHUSDT", TICKS["ETHUSDT"], BigTradeConfig(value=Decimal("0")))
    flagged = [e.trade_id for e in eng.process(prints) if isinstance(e, BigTradeEvent)]
    assert len(flagged) == len(set(flagged)) == len({p.trade_id for p in prints})
