"""QuestDB migration 0004 (#2016, parent #2014): bars_* are keyed by (generation, index), not ts."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from candleviewer.bars.activity_builders import VolumeBarBuilder
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import BarReader
from candleviewer.bars.rows import bar_row, row_checksum
from candleviewer.bars.writer import BarWriter
from candleviewer.storage.questdb.ddl import parse_ddl_dir
from tests.unit.bars._trades import SYM, trade

ROOT = Path(__file__).resolve().parents[5]
SPEC = BarSpec(kind="volume", volume_threshold=Decimal("1500"))
KEY = ("ts", "symbol", "bar_param", "generation", "index")


class _DedupStore:
    """In-memory QuestDB stand-in: UPSERT on the table's DEDUP key, last write wins."""

    def __init__(self) -> None:
        self.rows: dict[tuple[object, ...], dict[str, object]] = {}

    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_key: str) -> None:
        for r in rows:
            self.rows[tuple(r[k] for k in KEY)] = r  # NULL index is a valid key part

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        assert 'ORDER BY ts, "index"' in sql

        def order(r: dict[str, object]) -> tuple[int, int]:
            # QuestDB sorts NULL first in ASC; `ORDER BY ts, "index"`.
            idx = r["index"]
            return (int(str(r["ts"])), -1 if idx is None else int(str(idx)))

        return sorted(self.rows.values(), key=order)


async def _sched(*_: object) -> None:
    return None


def _closed_bars() -> list[Bar]:
    builder = VolumeBarBuilder(SPEC, SYM)
    updates = builder.on_trade(trade(1_700_000_000_000_000, qty="5000"))
    return [u.bar for u in updates if u.bar.closed]


@pytest.mark.asyncio
async def test_three_volume_bars_from_one_print_survive_write_read_round_trip() -> None:
    bars = _closed_bars()
    assert len(bars) == 3 and len({b.open_time for b in bars}) == 1  # same ts, BI-1 setup
    store = _DedupStore()
    writer = BarWriter(store, batch_rows=1)
    await writer.start()
    await writer.submit(bars, SPEC)
    assert await writer.stop() == 0
    assert len(store.rows) == 3  # (ts, symbol, bar_param) alone would have collapsed to 1
    page = await BarReader(store, _sched).read_bars(SYM, SPEC, 0, 2**60, 10)
    assert [r["index"] for r in page.rows] == [b.index for b in bars]
    assert all(r["generation"] == 0 for r in page.rows)
    assert sum(Decimal(repr(r["volume"])) for r in page.rows) == Decimal("4500")  # BI-1
    assert not page.integrity_degraded


def test_generation_and_index_are_in_the_row_and_the_checksum() -> None:
    b = _closed_bars()[0]
    base = bar_row(b, SPEC)
    other = bar_row(b, SPEC, generation=1)
    assert base["index"] == b.index and base["generation"] == 0
    assert other["row_checksum"] != base["row_checksum"] == row_checksum(base)


def test_ddl_dir_recreates_all_six_bars_tables_keyed_by_generation_and_index() -> None:
    tables = {t.name: t for t in parse_ddl_dir(ROOT / "backend/db/questdb")}
    for kind in ("time", "tick", "volume", "range", "renko", "delta"):
        t = tables[f"bars_{kind}"]
        assert t.dedup_keys == KEY and t.source_file == "0004_bars_key_by_index.sql"
        assert t.partition_by == "MONTH" and t.ts_col == "ts"
        assert {"generation", "index", "source", "row_checksum"} <= set(t.columns)


def test_read_query_quotes_every_reserved_bare_identifier() -> None:
    """Docker-free guard for the #2016 class of bug: a reserved word used bare is rejected by a
    real QuestDB but accepted by every in-memory fake."""
    import re

    from candleviewer.bars.reader import build_range_query
    from candleviewer.storage.sql_identifiers import QUESTDB_RESERVED, column_identifier

    assert column_identifier("index") == '"index"' and column_identifier("ts") == "ts"
    sql, _ = build_range_query("volume", SYM, "vol:1500", 0, 10, None, 5)
    order = sql.split("ORDER BY", 1)[1].split("LIMIT", 1)[0]
    where = sql.split("WHERE", 1)[1].split("ORDER BY", 1)[0]
    bare = re.findall(r"(?<!\")\b([A-Za-z_]\w*)\b(?!\")", order)
    bare += re.findall(r"\b(\w+)\s*(?:=|>=|<)\s*\$", where)
    assert bare and not [w for w in bare if w.lower() in QUESTDB_RESERVED], bare
    assert '"index"' in order


def test_ddl_quotes_every_reserved_column_name() -> None:
    from candleviewer.storage.sql_identifiers import QUESTDB_RESERVED

    files = sorted((ROOT / "backend/db/questdb").glob("*.sql"))
    assert len(files) >= 4
    for f in files:
        text = f.read_text("utf-8")
        code = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
        for name in QUESTDB_RESERVED:
            pat = rf"^\s+{name}\s+(?:TIMESTAMP|SYMBOL|DOUBLE|LONG|INT|BOOLEAN)\b"
            assert not re.search(pat, code, re.M | re.I), (f.name, name)


def _row(b: Bar, **kw: object) -> dict[str, object]:
    row = {**bar_row(b, SPEC), **kw}
    row["row_checksum"] = row_checksum(row)  # keep the row trustworthy for the reader
    return row


async def _page(store: _DedupStore, limit: int) -> list[dict[str, object]]:
    return (await BarReader(store, _sched).read_bars(SYM, SPEC, 0, 2**60, limit)).rows


@pytest.mark.asyncio
async def test_null_index_kline_rows_do_not_hide_older_tape_rows_from_page_one() -> None:
    """(a) NULL-index kline rows sort first under (generation, index, ts) and fill page 1."""
    b = _closed_bars()[0]
    store = _DedupStore()
    store.rows[("tape",)] = _row(b, ts=1_000, index=0)
    for i in range(3):
        store.rows[("kline", i)] = _row(b, ts=2_000 + i, index=None)
    page = await _page(store, 2)
    assert [r["ts"] for r in page][:2] == [1_000, 2_000]  # older tape row first (limit+1 rows)


@pytest.mark.asyncio
async def test_builder_cold_start_index_reset_keeps_ts_order_across_pages() -> None:
    """(b) index restarts at 0 with generation unchanged: ts must still lead the order."""
    b = _closed_bars()[0]
    store = _DedupStore()
    store.rows[("old", 0)] = _row(b, ts=1_000, index=5)
    store.rows[("old", 1)] = _row(b, ts=1_100, index=6)
    store.rows[("new", 0)] = _row(b, ts=2_000, index=0)  # cold start: index back to 0
    page = await _page(store, 3)
    assert [r["ts"] for r in page] == [1_000, 1_100, 2_000]


def test_range_query_bind_count_matches_placeholders() -> None:
    """Docker-free guard: QuestDB rejects a param/placeholder mismatch (asyncpg InterfaceError)."""
    from candleviewer.bars.reader import build_range_query

    for after in (None, 7):
        sql, params = build_range_query("volume", SYM, "vol:1500", 0, 10, after, 5)
        assert sorted(set(re.findall(r"\$(\d+)", sql))) == [str(i + 1) for i in range(len(params))]
        assert sql.endswith("LIMIT 5")
