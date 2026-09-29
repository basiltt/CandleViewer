"""Regression test (mirrors `test_0003_models_match_sql.py`): `candleviewer.db.models`
must mirror the DDL shape emitted by revision `0004_instruments`'s hand-written
SQL — named check/unique constraints, the partial `instrument_versions`
index sort direction, and the two column comments — or `alembic check`
(CI-MIG-002) reports drift.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from candleviewer.db import models

_SERVICES_API_ROOT = Path(__file__).resolve().parents[3]


def _render_sql() -> str:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=_SERVICES_API_ROOT,
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_instruments_check_constraint_names_match_sql() -> None:
    """The DDL's bare check-constraint names (`inst_cat`, etc.) become
    `ck_instruments_<name>` under the shared naming convention (§9.3 rule 12);
    that renamed form is what `alembic check` compares against.
    """
    expected_bare = {"inst_cat", "inst_quote", "inst_ticks", "inst_qty_rng", "inst_version"}
    table = models.instruments
    actual = {ck.name for ck in table.constraints if ck.__class__.__name__ == "CheckConstraint"}
    missing = {f"ck_instruments_{name}" for name in expected_bare} - actual
    assert not missing, f"instruments is missing check constraints {missing}"


def test_instrument_versions_constraint_names_match_sql() -> None:
    table = models.instrument_versions
    checks = {ck.name for ck in table.constraints if ck.__class__.__name__ == "CheckConstraint"}
    assert "ck_instrument_versions_iv_version" in checks
    uniques = {uc.name for uc in table.constraints if uc.__class__.__name__ == "UniqueConstraint"}
    assert "iv_unique_version" in uniques


def test_instrument_versions_symbol_index_matches_sql_sort_direction() -> None:
    table = models.instrument_versions
    by_name = {ix.name: ix for ix in table.indexes}
    assert "ix_instrument_versions_symbol" in by_name


def test_instruments_and_instrument_versions_column_comments_match_sql() -> None:
    assert models.instruments.columns["raw"].comment == (
        "Full, unredacted instruments-info payload for this symbol, for "
        "audit and forward-compat fields."
    )
    assert models.instrument_versions.columns["changed_fields"].comment == (
        "Field names that differed from the immediately preceding version, "
        "for InstrumentUpdatedEvent.changed_fields."
    )


def test_rendered_sql_still_creates_the_named_constraints_and_comments() -> None:
    """Sanity check binding the assertions above to the actual migration SQL:
    if 0004 is ever edited before merge, this fails loudly instead of the
    model and the SQL silently diverging further."""
    sql = _render_sql()
    for needle in (
        "CONSTRAINT inst_cat",
        "CONSTRAINT inst_quote",
        "CONSTRAINT inst_ticks",
        "CONSTRAINT inst_qty_rng",
        "CONSTRAINT inst_version",
        "CONSTRAINT iv_version",
        "CONSTRAINT iv_unique_version",
        "CREATE INDEX ix_instrument_versions_symbol",
        "COMMENT ON COLUMN instruments.raw",
        "COMMENT ON COLUMN instrument_versions.changed_fields",
    ):
        assert needle in sql, needle
