"""Regression test (PR #1561 alembic-check fix): `candleviewer.db.models`
must mirror the DDL shape emitted by revision `0003_audit_log`'s hand-written
SQL — unique constraint names, the partial `ix_audit_sev` index and column
comments — or `alembic check` (CI-MIG-002) reports drift.

Mirrors `test_0001_models_match_sql.py`'s approach: grep the rendered SQL
string, then assert `db.models` declares the matching shape.
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


def test_audit_unique_constraint_names_match_postgres_default_naming() -> None:
    """0003's SQL uses inline `UNIQUE` on `record_id`/`entry_hash` and a
    table-level `UNIQUE (head_id)` on `audit_checkpoints`, which Postgres
    auto-names `<table>_<col>_key`. The model must use the same names.
    """
    expected = {
        "audit_log": {"audit_log_record_id_key", "audit_log_entry_hash_key"},
        "audit_checkpoints": {"audit_checkpoints_head_id_key"},
    }
    for table_name, expected_names in expected.items():
        table = models.metadata.tables[table_name]
        actual_names = {
            uc.name for uc in table.constraints if uc.__class__.__name__ == "UniqueConstraint"
        }
        missing = expected_names - actual_names
        assert not missing, f"{table_name} is missing unique constraints {missing}"


def test_ix_audit_sev_partial_index_matches_sql_predicate() -> None:
    """`ix_audit_sev` is a partial index in the SQL
    (`WHERE severity IN ('error','critical')`); the model's `Index` must
    declare the same `postgresql_where` predicate or autogenerate proposes
    to recreate it.
    """
    table = models.audit_log
    by_name = {ix.name: ix for ix in table.indexes}
    assert "ix_audit_sev" in by_name, "audit_log is missing index ix_audit_sev"
    ix = by_name["ix_audit_sev"]
    where_clause = ix.dialect_options["postgresql"]["where"]
    assert where_clause is not None
    assert "severity IN ('error', 'critical')" in str(
        where_clause.compile(compile_kwargs={"literal_binds": True})
    ) or "severity IN ('error','critical')" in str(
        where_clause.compile(compile_kwargs={"literal_binds": True})
    )


def test_audit_log_column_comments_match_sql() -> None:
    """0003's SQL has four `COMMENT ON COLUMN` statements; the model must
    carry the same `comment=` text or autogenerate reports drift.
    """
    expected = {
        "record_id": (
            "Writer-assigned idempotency key: WAL replay is ON CONFLICT (record_id) DO NOTHING"
        ),
        "actor_ip": "PII: purge on account erase / retention job",
        "before_state": (
            "Redacted diff source — SECRET-classified fields must never "
            "appear here (candleviewer.audit.redact)"
        ),
        "after_state": (
            "Redacted diff source — SECRET-classified fields must never "
            "appear here (candleviewer.audit.redact)"
        ),
    }
    for column_name, expected_comment in expected.items():
        column = models.audit_log.columns[column_name]
        assert column.comment == expected_comment, (
            f"audit_log.{column_name} comment {column.comment!r} does not match "
            f"the DDL's COMMENT ON COLUMN {expected_comment!r}"
        )


def test_rendered_sql_still_creates_the_named_constraints_and_comments() -> None:
    """Sanity check binding the assertions above to the actual migration SQL:
    if 0003 is ever edited before merge, this fails loudly instead of the
    model and the SQL silently diverging further.
    """
    sql = _render_sql()
    assert "record_id     uuid NOT NULL UNIQUE" in sql
    assert "entry_hash    sha256_hex NOT NULL UNIQUE" in sql
    assert "UNIQUE (head_id)" in sql
    assert "ix_audit_sev" in sql and "WHERE severity IN ('error','critical')" in sql
    assert "COMMENT ON COLUMN audit_log.record_id" in sql
    assert "COMMENT ON COLUMN audit_log.actor_ip" in sql
    assert "COMMENT ON COLUMN audit_log.before_state" in sql
    assert "COMMENT ON COLUMN audit_log.after_state" in sql
