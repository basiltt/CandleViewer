"""M10 relational-tier metadata package (E07-T02).

`candleviewer.db.models` is the SQLAlchemy 2.0 Core `MetaData` object that is
the autogenerate source of truth for the Postgres schema (§9.1/§9.3 rule 12,
`docs/plan/21-database-schema.md`). It intentionally does not replace the
hand-written SQL in `candleviewer/migrations/versions/0001_identity_rbac_sessions_mfa.py`
(owned by E09-T01) — it *mirrors* that revision's tables as Core `Table`
objects so `alembic check` has something to diff against, per this ticket's
"autogenerate-drift check" acceptance criterion.
"""

from __future__ import annotations

from candleviewer.db.models import NAMING_CONVENTION, metadata

__all__ = ["NAMING_CONVENTION", "metadata"]
