"""E42-K01 spike measurement: audit_log query plans and index strategy at scale.

Runs only in the CI `audit-query-plan` job (``CV_AUDIT_SPIKE=1``; Docker +
testcontainers Postgres 16). Loads ``CV_AUDIT_SPIKE_ROWS`` (default 10 M)
synthetic rows set-based, then for each index candidate measures the SCR-135
filter combinations with ``EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`` (page 1
and a cursor 90 % deep), write overhead of 10k-row insert batches, and the
``CREATE INDEX CONCURRENTLY`` cost of the full-text GIN candidate while a
writer keeps inserting. Result: ``build/reports/audit-query-plan.json``.

It records numbers; it asserts only that the measurement itself completed.
Synthetic data only (``user_NN``, RFC 5737 IPs); no network beyond loopback.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql

from bench.audit_index import ci_spike as cs

pytestmark = [
    pytest.mark.integration,
    pytest.mark.perf,
    pytest.mark.skipif(
        os.environ.get("CV_AUDIT_SPIKE") != "1", reason="E42-K01 spike: CI audit-query-plan job"
    ),
]

_ROOT = Path(__file__).resolve().parents[3]
REPORT = _ROOT / "build" / "reports" / "audit-query-plan.json"
ROWS = int(os.environ.get("CV_AUDIT_SPIKE_ROWS", "10000000"))
CHUNK = 1_000_000
RUNS = 20
SLOW_RUNS = 3
WRITE_BATCHES = 20
BATCH_ROWS = 10_000
BIG_BATCH_ROWS = 100_000
BIG_BATCHES = 1
# Per-INSERT sample sizes: the full 100k for the recommended set (ticket AC), 20k for the rest
# so the job fits its time budget. Neither the ticket nor 06-performance-and-load-standard.md
# states an audit write rate; pace at PACE_PER_S inserts/s (a stress superset of the expected
# tens/s of state-changing requests). If an INSERT outlasts the interval the next runs
# back-to-back, so p99 is service time, not queueing.
SINGLE_FULL = 100_000
SINGLE_OTHER = 20_000
PACE_PER_S = 500
EXISTING_IX = (
    "CREATE INDEX ix_audit_time ON audit_log (event_ts DESC)",
    "CREATE INDEX ix_audit_actor ON audit_log (actor_user_id, event_ts DESC)",
    "CREATE INDEX ix_audit_action ON audit_log (action, event_ts DESC)",
    "CREATE INDEX ix_audit_object ON audit_log (object_kind, object_id, event_ts DESC)",
    "CREATE INDEX ix_audit_sev ON audit_log (severity, event_ts DESC)"
    " WHERE severity IN ('error','critical')",
)
PG_ARGS = (
    "postgres -c shared_buffers=2GB -c maintenance_work_mem=1GB -c work_mem=64MB"
    " -c max_wal_size=4GB -c checkpoint_timeout=30min -c effective_cache_size=8GB"
)


_CONTAINER: list[Any] = []


@pytest.fixture(scope="module")
def dsn() -> Iterator[str]:
    from testcontainers.postgres import PostgresContainer

    pg = PostgresContainer("postgres:16-alpine").with_command(PG_ARGS)
    _CONTAINER.append(pg)
    pg.with_kwargs(shm_size="2g")
    with pg as container:
        url = container.get_connection_url()
        subprocess.run(  # fixed argv, literal alembic subcommand, no shell
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={
                **os.environ,
                "CV_PG_DSN": url.replace("postgresql+psycopg2", "postgresql+psycopg"),
            },
            check=True,
        )
        yield url.replace("postgresql+psycopg2", "postgresql")


def _conn(dsn: str) -> psycopg.Connection[Any]:
    return psycopg.connect(dsn, autocommit=True)


def _timed(conn: psycopg.Connection[Any], sql: str) -> float:
    t = time.perf_counter()
    conn.execute(sql)
    return round(time.perf_counter() - t, 3)


def _load(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    """Bulk load with the chain trigger and secondary indexes off (restored after)."""
    conn.execute(cs.seed_users_sql())
    for name in ("ix_audit_time", "ix_audit_actor", "ix_audit_action", "ix_audit_object"):
        conn.execute(sql.SQL("DROP INDEX {}").format(sql.Identifier(name)))
    conn.execute("DROP INDEX ix_audit_sev")
    conn.execute("ALTER TABLE audit_log DISABLE TRIGGER trg_audit_chain")
    t0 = time.perf_counter()
    for first in range(0, ROWS, CHUNK):
        last = min(first + CHUNK, ROWS) - 1
        conn.execute(cs.generate_rows_sql(first, last, ROWS, chained=False))
    load_s = time.perf_counter() - t0
    index_s = {ddl.split()[2]: _timed(conn, ddl) for ddl in EXISTING_IX}
    conn.execute("ALTER TABLE audit_log ENABLE TRIGGER trg_audit_chain")
    vacuum_s = _timed(conn, "VACUUM (ANALYZE) audit_log")
    size = conn.execute(
        "SELECT pg_relation_size('audit_log'), pg_indexes_size('audit_log'), count(*)"
        " FROM audit_log"
    ).fetchone()
    assert size is not None
    return {
        "rows": int(size[2]),
        "load_s": round(load_s, 1),
        "existing_index_build_s": index_s,
        "vacuum_analyze_s": vacuum_s,
        "heap_bytes": int(size[0]),
        "index_bytes": int(size[1]),
    }


def _explain(conn: psycopg.Connection[Any], sql: str) -> dict[str, Any]:
    row = conn.execute(sql).fetchone()
    assert row is not None
    return cs.parse_plan(row[0])


def _measure(
    conn: psycopg.Connection[Any], where: str, cursor: str | None, runs: int, mat: bool = False
) -> dict[str, Any]:
    sql = cs.build_query(where, cursor, materialized=mat)
    first = _explain(conn, sql)  # warm-up; its time is kept as the cold-ish sample
    if first["exec_ms"] > 1000:  # seconds-long plans: fewer samples keep the job bounded
        runs = min(runs, SLOW_RUNS)
    plans = [_explain(conn, sql) for _ in range(runs)]
    out: dict[str, Any] = cs.summarise([p["exec_ms"] for p in plans])
    out.update(first_run_ms=first["exec_ms"], node_types=plans[-1]["node_types"])
    out["indexes"] = plans[-1]["indexes"]
    return out


def _queries(conn: psycopg.Connection[Any], deep: str) -> dict[str, Any]:
    res: dict[str, Any] = {}
    for name, where in cs.FILTERS.items():
        for label, cur in ((name, None), (f"{name}@90%", deep)):
            r = _measure(conn, where, cur, RUNS)
            r["verdict"] = cs.verdict(r["p95_ms"], cs.COMMON_P95_BUDGET_MS)
            res[label] = r
    return res


def _write_batches(
    conn: psycopg.Connection[Any], rows: int = BATCH_ROWS, batches: int = WRITE_BATCHES
) -> dict[str, float]:
    """`rows`-row INSERT ... SELECT through the real chain trigger; rolled back each time."""
    lat: list[float] = []
    for i in range(batches):
        base = ROWS + 10_000_000 + i * rows
        with conn.transaction(force_rollback=True):
            t = time.perf_counter()
            conn.execute(cs.generate_rows_sql(base, base + rows - 1, ROWS, chained=True))
            lat.append((time.perf_counter() - t) * 1000)
    return cs.summarise(lat)


def _write_single(conn: psycopg.Connection[Any], n: int) -> dict[str, float]:
    """Per-INSERT latency: `n` single-row transactions through the real chain trigger.

    Each INSERT takes the advisory lock and computes the hash. Paced at PACE_PER_S, each
    INSERT timed individually; p50/p95/p99 come from all `n` samples. Rolled back so the
    table is unchanged; a commit adds an fsync identical for every set.
    """
    lat: list[float] = []
    interval = 1.0 / PACE_PER_S
    nxt = time.perf_counter()
    for i in range(n):
        base = ROWS + 30_000_000 + i
        sql = cs.generate_rows_sql(base, base, ROWS, chained=True)
        with conn.transaction(force_rollback=True):
            t = time.perf_counter()
            conn.execute(sql)
            lat.append((time.perf_counter() - t) * 1000)
        nxt += interval
        if (delay := nxt - time.perf_counter()) > 0:
            time.sleep(delay)
        else:
            nxt = time.perf_counter()
    out = cs.summarise(lat)
    out["paced_per_s"] = float(PACE_PER_S)
    return out


COLD_KEYS = ("range", "actor_action", "severity_actor", "object", "env_action")


def _cold(report: dict[str, Any]) -> dict[str, Any]:
    """Cold-cache first-run latency: restart Postgres (empties shared_buffers).

    Measured on the recommended set f + GIN. The container restart does not drop the
    host OS page cache, so this is "cold shared_buffers", not a cold disk; documented.
    """
    pg = _CONTAINER[0]
    out: dict[str, Any] = {
        "scope": "shared_buffers cold after container restart; OS cache not dropped"
    }
    ddl = [(n, b) for n, b in cs.CANDIDATES["f_recommended"]]
    with _conn(pg.get_connection_url().replace("postgresql+psycopg2", "postgresql")) as c:
        for n, body in ddl:
            c.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON ").format(sql.Identifier(n))
                + sql.SQL(body)  # type: ignore[arg-type]  # static DDL tuples defined in this module
            )
        c.execute("CHECKPOINT")
    pg.get_wrapped_container().restart()
    time.sleep(10)  # wait for postgres to accept connections after restart (infra wait)
    new = pg.get_connection_url().replace("postgresql+psycopg2", "postgresql")
    deep = cs.cursor_literal(0.9)
    with _conn(new) as c:
        for key in COLD_KEYS:
            plan = _explain(c, cs.build_query(cs.FILTERS[key], None))
            out[key] = {"cold_first_ms": plan["exec_ms"], "indexes": plan["indexes"]}
        plan = _explain(c, cs.build_query(cs.FILTERS["severity_actor"], deep))
        out["severity_actor@90%"] = {"cold_first_ms": plan["exec_ms"]}
        for key in COLD_KEYS:
            plan = _explain(c, cs.build_query(cs.FILTERS[key], None))
            out[key]["warm_second_ms"] = plan["exec_ms"]
    return out


def _gin_concurrently(dsn: str) -> dict[str, Any]:
    """Build the GIN index CONCURRENTLY while a second session keeps inserting.

    Records build time, size, and single-row insert latency during the build
    (proves writes are not blocked: CONCURRENTLY takes SHARE UPDATE EXCLUSIVE).
    """
    stop = threading.Event()
    during: list[float] = []

    def writer() -> None:
        with _conn(dsn) as w:
            i = 0
            while not stop.is_set():
                base = ROWS + 20_000_000 + i
                with w.transaction(force_rollback=True):
                    t = time.perf_counter()
                    w.execute(cs.generate_rows_sql(base, base, ROWS, chained=True))
                    during.append((time.perf_counter() - t) * 1000)
                i += 1
                time.sleep(0.05)  # pacing a background writer, not a test wait

    th = threading.Thread(target=writer, daemon=True)
    with _conn(dsn) as conn:
        th.start()
        build_s = _timed(conn, cs.GIN_DDL)
        stop.set()
        th.join(timeout=60)
        row = conn.execute(
            "SELECT pg_relation_size(%s::regclass), indisvalid FROM pg_index "
            "WHERE indexrelid = %s::regclass",
            (cs.GIN_NAME, cs.GIN_NAME),
        ).fetchone()
        assert row is not None
    return {
        "build_concurrently_s": build_s,
        "index_bytes": int(row[0]),
        "valid": bool(row[1]),
        "inserts_during_build": cs.summarise(during) if during else {},
    }


def _fulltext(conn: psycopg.Connection[Any], with_gin: bool) -> dict[str, Any]:
    """Full text: naive form (1 run, statement_timeout 60 s) and MATERIALIZED-CTE form."""
    res: dict[str, Any] = {}
    month = "event_ts >= '2026-06-01' AND event_ts < '2026-07-01'"
    for name, where in cs.FULLTEXT.items():
        for label, w, mat in (
            (f"{name}_wide_cte", where, True),
            (f"{name}_30d_cte", f"{where} AND {month}", True),
            (f"{name}_wide_naive", where, False),
        ):
            conn.execute("SET statement_timeout = '60s'")
            try:
                r = _measure(conn, w, None, SLOW_RUNS, mat=mat)
                r["verdict"] = cs.verdict(r["p95_ms"], cs.WORST_CASE_BUDGET_MS)
            except psycopg.errors.QueryCanceled:
                r = {"timeout_s": 60, "verdict": "MISS"}
            finally:
                conn.execute("RESET statement_timeout")
            res[label + ("_gin" if with_gin else "")] = r
    return res


def test_audit_query_plan_spike(dsn: str) -> None:
    started = time.perf_counter()
    deep = cs.cursor_literal(0.9)
    report: dict[str, Any] = {
        "ticket": "E42-K01 (#888)",
        "rows_target": ROWS,
        "runs_per_query": RUNS,
        "slow_query_runs": SLOW_RUNS,
        "budgets_ms": {"common_p95": cs.COMMON_P95_BUDGET_MS, "worst": cs.WORST_CASE_BUDGET_MS},
        "github_run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "runner": {"os": os.environ.get("RUNNER_OS", ""), "cpus": os.cpu_count()},
        "pg_args": PG_ARGS,
        "candidates": {k: [d for _, d in v] for k, v in cs.CANDIDATES.items()},
    }
    with _conn(dsn) as conn:
        version = conn.execute("SHOW server_version").fetchone()
        report["server_version"] = version[0] if version else ""
        report["load"] = _load(conn)
        cs.write_report(REPORT, report)  # partial report survives a later timeout
        report["queries"], report["write_10k_batch"], report["index_build_s"] = {}, {}, {}
        report["write_100k_batch"], report["write_single_row"] = {}, {}
        for cand, ixs in cs.CANDIDATES.items():
            report["index_build_s"][cand] = {
                n: _timed(conn, f"CREATE INDEX {n} ON {body}") for n, body in ixs
            }
            conn.execute("ANALYZE audit_log")
            report["queries"][cand] = _queries(conn, deep)
            report["write_10k_batch"][cand] = _write_batches(conn)
            report["write_100k_batch"][cand] = _write_batches(conn, BIG_BATCH_ROWS, BIG_BATCHES)
            report["write_single_row"][cand] = _write_single(
                conn, SINGLE_FULL if cand == "g_f_gin" else SINGLE_OTHER
            )
            for n, _ in ixs:
                conn.execute(sql.SQL("DROP INDEX {}").format(sql.Identifier(n)))
            cs.write_report(REPORT, report)
        report["fulltext"] = _fulltext(conn, with_gin=False)
        cs.write_report(REPORT, report)
    report["gin"] = _gin_concurrently(dsn)
    with _conn(dsn) as conn:
        conn.execute("ANALYZE audit_log")
        report["fulltext"].update(_fulltext(conn, with_gin=True))
        report["write_10k_batch"]["d_gin"] = _write_batches(conn)
        report["write_100k_batch"]["d_gin"] = _write_batches(conn, BIG_BATCH_ROWS, BIG_BATCHES)
        report["write_single_row"]["d_gin"] = _write_single(conn, SINGLE_OTHER)
    report["cold_cache"] = _cold(report)
    report["total_s"] = round(time.perf_counter() - started, 1)
    cs.write_report(REPORT, report)
    assert report["load"]["rows"] == ROWS
    assert report["gin"]["valid"] is True
