"""Unit tests for `tools/ci/migration_lint.py` (E03-T10).

Fixture migration files (destructive annotated, destructive unannotated,
additive, ambiguous batch operations) per the ticket's test plan.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.migration_lint import (
    check_destructive_annotations,
    check_if_not_exists,
    check_security_sensitive,
    main,
)

_ADDITIVE = '''
from alembic import op


def upgrade() -> None:
    op.add_column("orders", sa.Column("note", sa.Text(), nullable=True))
    op.create_index("ix_orders_note", "orders", ["note"])
'''

_DESTRUCTIVE_UNANNOTATED = '''
from alembic import op


def upgrade() -> None:
    op.drop_column("orders", "legacy_status")
'''

_DESTRUCTIVE_ANNOTATED = '''
from alembic import op


def upgrade() -> None:
    # cv:contract-phase: R2
    op.drop_column("orders", "legacy_status")
'''

_DESTRUCTIVE_FORBIDDEN_TABLE = '''
from alembic import op


def upgrade() -> None:
    # cv:contract-phase: R2
    op.drop_column("audit_log", "note")
'''

_NON_NULLABLE_ADD_NO_DEFAULT = '''
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column("orders", sa.Column("qty", sa.Numeric(), nullable=False))
'''

_NON_NULLABLE_ADD_WITH_DEFAULT = '''
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column(
        "orders", sa.Column("qty", sa.Numeric(), nullable=False, server_default="0")
    )
'''

_TYPE_NARROWING = '''
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.alter_column("orders", "qty", type_=sa.Integer())
'''

_IF_NOT_EXISTS_SQL = '''
from alembic import op


def upgrade() -> None:
    op.execute("CREATE TABLE IF NOT EXISTS widgets (id uuid primary key)")
'''

_SECURITY_SENSITIVE = '''
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("label", sa.Text(), nullable=True))
'''


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_additive_migration_has_no_findings(tmp_path: Path) -> None:
    path = _write(tmp_path, "0002_additive.py", _ADDITIVE)
    assert check_destructive_annotations([path]) == []
    assert check_if_not_exists([path]) == []


def test_destructive_without_annotation_is_flagged(tmp_path: Path) -> None:
    path = _write(tmp_path, "0003_destructive.py", _DESTRUCTIVE_UNANNOTATED)
    findings = check_destructive_annotations([path])
    assert len(findings) == 1
    assert findings[0].code == "CI-MIG-003"
    assert "cv:contract-phase" in findings[0].message


def test_destructive_with_annotation_passes(tmp_path: Path) -> None:
    path = _write(tmp_path, "0004_destructive_ok.py", _DESTRUCTIVE_ANNOTATED)
    assert check_destructive_annotations([path]) == []


def test_destructive_on_forbidden_audit_table_always_flagged(tmp_path: Path) -> None:
    path = _write(tmp_path, "0005_audit_drop.py", _DESTRUCTIVE_FORBIDDEN_TABLE)
    findings = check_destructive_annotations([path])
    assert len(findings) == 1
    assert findings[0].code == "CI-MIG-003"
    assert "append-only" in findings[0].message


def test_non_nullable_add_column_without_default_is_flagged(tmp_path: Path) -> None:
    path = _write(tmp_path, "0006_add_col.py", _NON_NULLABLE_ADD_NO_DEFAULT)
    findings = check_destructive_annotations([path])
    assert len(findings) == 1
    assert findings[0].code == "CI-MIG-003"


def test_non_nullable_add_column_with_server_default_passes(tmp_path: Path) -> None:
    path = _write(tmp_path, "0007_add_col_default.py", _NON_NULLABLE_ADD_WITH_DEFAULT)
    assert check_destructive_annotations([path]) == []


def test_type_narrowing_without_annotation_is_flagged(tmp_path: Path) -> None:
    path = _write(tmp_path, "0008_narrow.py", _TYPE_NARROWING)
    findings = check_destructive_annotations([path])
    assert len(findings) == 1
    assert findings[0].code == "CI-MIG-003"


def test_if_not_exists_is_flagged(tmp_path: Path) -> None:
    path = _write(tmp_path, "0009_if_not_exists.py", _IF_NOT_EXISTS_SQL)
    findings = check_if_not_exists([path])
    assert len(findings) == 1
    assert findings[0].code == "CI-MIG-005"


def test_security_sensitive_table_is_flagged_as_warning(tmp_path: Path) -> None:
    path = _write(tmp_path, "0010_api_keys.py", _SECURITY_SENSITIVE)
    findings = check_security_sensitive([path], sensitive_tables=frozenset({"api_keys"}))
    assert len(findings) == 1
    assert findings[0].code == "CI-MIG-006"


def test_security_sensitive_returns_empty_when_no_table_list_given(tmp_path: Path) -> None:
    path = _write(tmp_path, "0011_api_keys.py", _SECURITY_SENSITIVE)
    assert check_security_sensitive([path], sensitive_tables=frozenset()) == []


def test_main_exits_zero_on_clean_versions_dir(tmp_path: Path) -> None:
    versions = tmp_path / "versions"
    versions.mkdir()
    _write(versions, "0001_additive.py", _ADDITIVE)
    assert main(["--versions-dir", str(versions)]) == 0


def test_main_exits_one_on_violations(tmp_path: Path) -> None:
    versions = tmp_path / "versions"
    versions.mkdir()
    _write(versions, "0001_destructive.py", _DESTRUCTIVE_UNANNOTATED)
    assert main(["--versions-dir", str(versions)]) == 1


def test_main_exits_two_when_versions_dir_missing(tmp_path: Path) -> None:
    assert main(["--versions-dir", str(tmp_path / "nope")]) == 2


@pytest.mark.parametrize(
    "fixture",
    [_ADDITIVE, _DESTRUCTIVE_ANNOTATED],
)
def test_multiple_clean_fixtures_never_flagged(tmp_path: Path, fixture: str) -> None:
    path = _write(tmp_path, "x.py", fixture)
    assert check_if_not_exists([path]) == []
