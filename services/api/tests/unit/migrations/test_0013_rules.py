"""`0013_rules`: models mirror the SQL, trigger/downgrade render, persistence rules (E35-T02)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from candleviewer.db import models
from candleviewer.storage.repositories.rules_sqlalchemy import persist_reason
from candleviewer.storage.retention.schedule import RetentionSchedule

_ROOT = Path(__file__).resolve().parents[3]


def _render(*args: str) -> str:
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", *args, "--sql"],
        cwd=_ROOT,
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _checks(table: object) -> set[str]:
    return {
        str(c.name)
        for c in table.constraints  # type: ignore[attr-defined]
        if c.__class__.__name__ == "CheckConstraint"
    }


def test_rules_check_constraint_names_match_sql() -> None:
    assert _checks(models.rules) == {
        f"ck_rules_{n}"
        for n in (
            "rule_editor",
            "rule_interval",
            "rule_cooldown",
            "rule_prio",
            "rule_scope_acct",
            "rule_scope_sym",
            "rule_armed_shape",
            "rule_fires_pos",
        )
    }
    assert _checks(models.rule_versions) == {
        f"ck_rule_versions_{n}" for n in ("rv_version_pos", "rv_ir_obj")
    }
    assert _checks(models.rule_runs) == {f"ck_rule_runs_{n}" for n in ("rr_trigger", "rr_duration")}
    assert _checks(models.rule_events) == {"ck_rule_events_re_kind"}


def test_rules_index_names_match_sql() -> None:
    names = {
        ix.name
        for t in (models.rules, models.rule_versions, models.rule_runs, models.rule_events)
        for ix in t.indexes
    }
    assert names == {
        "ux_rules_name",
        "ix_rules_active",
        "ix_rules_symbol",
        "ix_rules_account",
        "ix_rv_rule",
        "ix_rr_rule_time",
        "ix_rr_matched",
        "ix_rr_errors",
        "ix_rr_group",
        "ix_re_run",
        "ix_re_time",
    }


def test_upgrade_sql_creates_everything_including_append_only_trigger() -> None:
    sql = _render("upgrade", "0012_onboarding_dismissals:0013_rules")
    for table in ("rules", "rule_versions", "rule_runs", "rule_events"):
        assert f"CREATE TABLE {table}" in sql
    for enum in ("rule_scope", "rule_mode", "rule_run_status"):
        assert f"CREATE TYPE {enum} AS ENUM" in sql
    assert "UNIQUE (rule_id, version)" in sql and "UNIQUE (rule_id, ir_hash)" in sql
    assert "rules_active_version_fk" in sql and "ON DELETE RESTRICT" in sql
    assert "CREATE TRIGGER trg_re_append BEFORE UPDATE OR DELETE ON rule_events" in sql


def test_downgrade_sql_drops_tables_enums_and_trigger_function() -> None:
    sql = _render("downgrade", "0013_rules:0012_onboarding_dismissals")
    for obj in (
        "TABLE IF EXISTS rule_events",
        "FUNCTION IF EXISTS rule_events_forbid_mutation()",
        "TABLE IF EXISTS rule_runs",
        "TABLE IF EXISTS rule_versions",
        "TABLE IF EXISTS rules",
        "TYPE IF EXISTS rule_scope",
        "TYPE IF EXISTS rule_mode",
        "TYPE IF EXISTS rule_run_status",
    ):
        assert f"DROP {obj}" in sql


def test_persist_reason_writes_only_matched_error_or_simulate_record_all() -> None:
    def r(**k: object) -> str | None:
        base: dict[str, object] = {
            "matched": False,
            "status": "ok",
            "mode": "armed",
            "record_all": False,
        }
        return persist_reason(**{**base, **k})  # type: ignore[arg-type]

    assert r() is None
    assert r(matched=True) == "matched"
    assert r(status="error") == "error"
    assert r(mode="simulate", record_all=True) == "record_all"
    assert r(mode="armed", record_all=True) is None
    assert r(mode="simulate") is None


def test_rule_runs_prune_job_registered_only_when_retention_enabled() -> None:
    assert RetentionSchedule.from_env({}).rule_jobs() == {}
    on = RetentionSchedule.from_env({"CV_RETENTION_ENABLED": "true"}).rule_jobs()
    assert on == {"rule_runs_prune": "0 3 * * *"}


def test_rule_events_trigger_has_no_owner_or_guc_bypass() -> None:
    sql = _render("upgrade", "0012_onboarding_dismissals:0013_rules")
    assert "cv.rule_retention" not in sql and "session_user" not in sql
    assert "trg_rr_evidence BEFORE DELETE ON rule_runs" in sql


def test_rule_prune_task_runs_only_when_enabled() -> None:
    import asyncio

    from candleviewer.storage.retention.rule_prune import RulePruneTask

    class Repo:
        calls = 0

        async def prune_unmatched(self) -> object:
            Repo.calls += 1
            if Repo.calls == 1:
                raise RuntimeError("boom")  # failure must not kill the loop
            return None

    async def go(enabled: bool) -> int:
        Repo.calls = 0
        env = {"CV_RETENTION_ENABLED": "true" if enabled else "false"}
        ev = asyncio.Event()

        async def sleep(_: float) -> None:
            if Repo.calls >= 2:
                ev.set()
            await asyncio.sleep(0)

        t = RulePruneTask(Repo(), RetentionSchedule.from_env(env), sleep=sleep)
        t.start()
        if enabled:
            await asyncio.wait_for(ev.wait(), 2)
        await asyncio.sleep(0)
        await t.stop()
        return Repo.calls

    assert asyncio.run(go(False)) == 0
    assert asyncio.run(go(True)) >= 2
