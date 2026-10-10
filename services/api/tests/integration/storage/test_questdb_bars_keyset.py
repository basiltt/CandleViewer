"""#2017: `/market/bars` keyset paging over same-ts non-time bars on a real QuestDB.

Kept out of `test_questdb_hot_tier.py` so this PR does not touch (and the pre-commit
formatter does not re-wrap) that module's pragma lines.
"""

from __future__ import annotations

import pytest

from candleviewer.storage.questdb.runner import run_migrations
from tests.integration.storage.test_questdb_hot_tier import (
    _PGWIRE_PASSWORD,
    _PGWIRE_USER,
    DDL_DIR,
    _AsyncpgExecutor,
    _connect,
    questdb_container,
    wait_for_row_count,
)

__all__ = ["questdb_container"]  # fixture re-export for this module

pytestmark = pytest.mark.integration


@pytest.mark.integration
@pytest.mark.asyncio
async def test_same_ts_renko_bricks_page_by_key_on_real_questdb(
    questdb_container: tuple[str, int, int],
) -> None:
    """#2017: three same-ts bricks (index 0..2) paged with limit=1 through `BarReader` (the
    `/market/bars` read path) and the expanded keyset predicate -> [0], [1], [2], then done."""
    from candleviewer.bars.models import BarSpec
    from candleviewer.bars.reader import BarReader, row_key
    from candleviewer.bars.rows import bar_param_for
    from candleviewer.storage.questdb.wiring import QuestDbRowSink

    host, pg_port, ilp_port = questdb_container
    conn = await _connect(host, pg_port)
    sink = QuestDbRowSink(f"{host}:{ilp_port}", f"{host}:{pg_port}", _PGWIRE_USER, _PGWIRE_PASSWORD)
    spec = BarSpec(kind="renko", range_ticks=20)
    ts = 1_700_000_000_000_000
    try:
        await run_migrations(_AsyncpgExecutor(conn), DDL_DIR)
        base: dict[str, object] = {
            "symbol": "BTCUSDT", "bar_param": bar_param_for(spec), "ts": ts, "open": 1.0,
            "high": 2.0, "low": 0.5, "close": 1.5, "volume": 3.0, "is_closed": True,
            "generation": 0,
        }  # fmt: skip
        # Same shape as #2126's passing write: no `source`/`row_checksum` (a pre-0003 legacy
        # row, trusted by the reader). `source` is a SYMBOL column but `_BAR_TAG_COLUMNS` omits
        # it, so the ILP writer emits it as an unquoted field and QuestDB drops the line.
        rows = [{**base, "index": i} for i in (2, 0, 1)]
        await sink.write_rows("bars_renko", rows, "ts")
        await sink.stop()
        await wait_for_row_count(conn, "bars_renko", 3)
        wal = await conn.fetchrow("SELECT * FROM wal_tables() WHERE name = 'bars_renko'")
        assert wal is not None and not wal["suspended"], f"bars_renko WAL suspended: {wal}"
        assert int(wal["sequencerTxn"]) > 0, f"no ILP commit reached bars_renko: {dict(wal)}"

        class _Conn:
            async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
                return [dict(r) for r in await conn.fetch(sql, *params)]

        async def _noop(*_: object) -> None: ...

        reader, key, pages = BarReader(_Conn(), _noop), None, []
        for _ in range(5):
            page = await reader.read_bars("BTCUSDT", spec, ts - 1, ts + 1, 2, at_key=key)
            nxt = page.next_key
            pages.append([r["index"] for r in page.rows if nxt is None or row_key(r) < nxt])
            if (key := nxt) is None:
                break
        assert pages == [[0], [1], [2]]
    finally:
        await conn.close()
