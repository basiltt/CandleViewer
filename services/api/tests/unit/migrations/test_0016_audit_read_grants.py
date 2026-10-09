"""`0016_audit_read_grants` (#2083): offline render, grant direction, reversible downgrade."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_REV = "0016_audit_read_grants"


def _alembic_sql(*args: str) -> str:
    result = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args, "--sql"],
        cwd=_ROOT,
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _norm(sql: str) -> str:
    return " ".join(sql.split())


def test_upgrade_moves_audit_read_from_viewer_to_manager() -> None:
    sql = _norm(_alembic_sql("upgrade", f"0015_rules_arm_live_permission:{_REV}"))
    revoke = sql.index(
        "DELETE FROM role_permissions WHERE role_id IN (SELECT id FROM roles WHERE name = 'viewer')"
    )
    grant = sql.index("WHERE r.name = 'manager' AND p.code = 'audit:read' ON CONFLICT DO NOTHING")
    assert revoke < grant
    assert "name = 'manager') AND" not in sql


def test_downgrade_restores_viewer_grant_and_revokes_manager() -> None:
    sql = _norm(_alembic_sql("downgrade", f"{_REV}:0015_rules_arm_live_permission"))
    assert "SELECT id FROM roles WHERE name = 'manager') AND permission_id IN" in sql
    assert "WHERE r.name = 'viewer' AND p.code = 'audit:read' ON CONFLICT DO NOTHING" in sql
