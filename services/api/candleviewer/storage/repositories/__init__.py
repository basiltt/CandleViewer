"""Repository Protocols for the storage module (M10).

Re-exports the public Protocols; row dataclasses are imported from
`candleviewer.storage.repositories.rows` directly by callers that need them
(kept out of this `__all__` to keep the top-level namespace to Protocols +
models, matching `storage/__init__.py`'s "Public interface only" contract).
"""

from __future__ import annotations

from candleviewer.storage.repositories.cold import ColdTierRepository
from candleviewer.storage.repositories.market_data import MarketDataRepository
from candleviewer.storage.repositories.relational import RelationalRepository, UnitOfWork
from candleviewer.storage.repositories.retention import RetentionRepository

__all__ = [
    "ColdTierRepository",
    "MarketDataRepository",
    "RelationalRepository",
    "UnitOfWork",
    "RetentionRepository",
]
