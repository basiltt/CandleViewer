"""QuestDB hot-tier client (E07-T03): DDL runner, ILP writer, PGWire reader,
and the `MarketDataRepository` implementation over them.

Public surface: `run_migrations`, `assert_no_schema_drift` (`runner.py`),
`IlpWriter` (`ilp_writer.py`), `QuestDbReader` + query builders
(`reader.py`), `QuestDbMarketDataRepository` (`repository.py`).
"""

from __future__ import annotations

from candleviewer.storage.questdb.ilp_writer import IlpWriter, TableSchema, serialize_ilp_line
from candleviewer.storage.questdb.reader import QuestDbReader
from candleviewer.storage.questdb.repository import QuestDbMarketDataRepository
from candleviewer.storage.questdb.runner import assert_no_schema_drift, run_migrations

__all__ = [
    "IlpWriter",
    "QuestDbMarketDataRepository",
    "QuestDbReader",
    "TableSchema",
    "assert_no_schema_drift",
    "run_migrations",
    "serialize_ilp_line",
]
