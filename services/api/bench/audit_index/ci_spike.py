"""E42-K01: pure helpers for the CI audit query-plan measurement.

No database access here: SQL builders, percentile maths, EXPLAIN-JSON parsing and
the report writer. The integration test
(`tests/integration/audit/test_query_plan_spike.py`) drives them against the CI
Postgres. All data is synthetic (``user_NN``, RFC 5737 IPs, ``field_N``/``vNNN``).
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

# Budgets from SCR-135 / US-ADMIN-009 (ticket #888).
COMMON_P95_BUDGET_MS = 400.0
WORST_CASE_BUDGET_MS = 2000.0

USERS = 50
SPAN_DAYS = 365
START_TS = "2026-01-01T00:00:00Z"

# Index candidates; each is measured in isolation on top of the 0003 set ("a").
CANDIDATES: dict[str, tuple[tuple[str, str], ...]] = {
    "a_existing": (),
    "b_composite": (("ix_spk_actor_act_ts", "audit_log (actor_user_id, action, event_ts DESC)"),),
    "c_brin": (("ix_spk_ts_brin", "audit_log USING brin (event_ts)"),),
    "e_partial_sev": (
        ("ix_spk_hisev", "audit_log (event_ts DESC) WHERE severity IN ('error','critical')"),
    ),
    "f_recommended": (
        ("ix_spk_actor_act_ts", "audit_log (actor_user_id, action, event_ts DESC)"),
        ("ix_spk_hisev", "audit_log (event_ts DESC) WHERE severity IN ('error','critical')"),
    ),
}
TSV = (
    "to_tsvector('simple', coalesce(before_state::text,'') || ' ' || "
    "coalesce(after_state::text,''))"
)
GIN_NAME = "ix_spk_fts"
GIN_BODY = f"audit_log USING gin ({TSV})"
GIN_DDL = f"CREATE INDEX CONCURRENTLY {GIN_NAME} ON audit_log USING gin ({TSV})"
# The full recommended set (ADR-0025), measured together: f + the full-text GIN index.
RECOMMENDED_FULL: tuple[tuple[str, str], ...] = (*CANDIDATES["f_recommended"], (GIN_NAME, GIN_BODY))
CANDIDATES["g_f_gin"] = RECOMMENDED_FULL

_ACTOR = "'00000000-0000-4000-8000-000000000007'::uuid"
# SCR-135 filter-bar combinations ("common", 400 ms p95 budget).
FILTERS: dict[str, str] = {
    "range": "event_ts >= '2026-06-01' AND event_ts < '2026-07-01'",
    "actor": f"actor_user_id = {_ACTOR}",
    "action": "action = 'orders.submit'",
    "action_range": "action = 'admin.user_update' AND event_ts >= '2026-03-01'",
    "actor_action": f"actor_user_id = {_ACTOR} AND action = 'orders.cancel'",
    "actor_action_range": f"actor_user_id = {_ACTOR} AND action = 'orders.cancel'"
    " AND event_ts >= '2026-06-01'",
    "severity": "severity IN ('error','critical')",
    "severity_actor": "severity IN ('error','critical') AND actor_label = 'user_07'",
    "object": "object_kind = 'order' AND object_id = 'obj-12345'",
    "outcome_action": "outcome = 'denied' AND action = 'auth.login_failed'",
    "env_action": "env = 'live' AND action = 'orders.submit'",
}
# Full-text over a wide range ("worst case", 2 s budget); selective vs common token.
FULLTEXT: dict[str, str] = {
    "fulltext_selective": f"{TSV} @@ plainto_tsquery('simple', 'v424242')",
    "fulltext_common": f"{TSV} @@ plainto_tsquery('simple', 'field_1')",
}

ORDER_LIMIT = " ORDER BY event_ts DESC, id DESC LIMIT 50"


def seed_users_sql(users: int = USERS) -> str:
    """Synthetic users the FK on ``actor_user_id`` needs (ids ``...-0000000000NN``)."""
    return (
        "INSERT INTO users (id, email, username, password_hash, status) "  # noqa: S608
        "SELECT ('00000000-0000-4000-8000-' || lpad(g::text, 12, '0'))::uuid, "
        "'user_' || lpad(g::text, 2, '0') || '@example.invalid', "
        "'user_' || lpad(g::text, 2, '0'), '$argon2id$synthetic', 'active' "
        f"FROM generate_series(0, {users - 1}) g ON CONFLICT DO NOTHING"
    )


def generate_rows_sql(first: int, last: int, total: int, chained: bool) -> str:
    """Set-based INSERT ... SELECT of synthetic rows ``first..last`` (of ``total``).

    Mix mirrors ``generate.py``: action 34/18/8/12 % orders, auth, rules, admin;
    severity 95/3.5/1.2/0.3 %; outcome 93/3/4 %; env 20/70/10 %; 70 % carry state.
    ``chained=False`` writes placeholder unique hashes (bulk load with the chain
    trigger disabled); ``chained=True`` omits them so ``audit_chain()`` computes them.
    """
    hashes = "" if chained else "prev_hash, entry_hash, "
    hash_vals = "" if chained else "repeat('0', 64), encode(sha256(('s' || g)::bytea), 'hex'), "
    return (
        f"INSERT INTO audit_log (record_id, {hashes}actor_user_id, actor_label, actor_ip, "  # noqa: S608
        "session_id, action, object_kind, object_id, object_label, outcome, severity, "
        "before_state, after_state, request_id, env, event_ts) "
        f"SELECT gen_random_uuid(), {hash_vals}"
        "('00000000-0000-4000-8000-' || lpad(u::text, 12, '0'))::uuid, "
        "'user_' || lpad(u::text, 2, '0'), ('192.0.2.' || (1 + g % 254))::inet, "
        "gen_random_uuid(), act, split_part(act, '.', 1), 'obj-' || (1 + (r3 * 1e7)::int), "
        "'label ' || (g % 999), "
        "(CASE WHEN r2 < 0.93 THEN 'success' WHEN r2 < 0.96 THEN 'denied' "
        "ELSE 'failure' END)::audit_outcome, "
        "(CASE WHEN r1 < 0.95 THEN 'info' WHEN r1 < 0.985 THEN 'warning' "
        "WHEN r1 < 0.997 THEN 'error' ELSE 'critical' END)::severity, "
        "CASE WHEN r4 < 0.7 THEN st END, CASE WHEN r4 < 0.7 THEN st END, "
        "gen_random_uuid(), "
        "(CASE WHEN r5 < 0.2 THEN 'live' WHEN r5 < 0.9 THEN 'demo' "
        "ELSE 'testnet' END)::exchange_env, "
        f"'{START_TS}'::timestamptz + (g::float8 / {total}) * interval '{SPAN_DAYS} days' "
        "FROM (SELECT g, u, r1, r2, r3, r4, r5, "
        "CASE WHEN ra < 0.34 THEN 'orders.submit' WHEN ra < 0.52 THEN 'orders.cancel' "
        "WHEN ra < 0.60 THEN 'orders.amend' WHEN ra < 0.72 THEN 'orders.fill' "
        "WHEN ra < 0.79 THEN 'auth.login' WHEN ra < 0.85 THEN 'auth.refresh' "
        "WHEN ra < 0.88 THEN 'auth.logout' WHEN ra < 0.90 THEN 'auth.login_failed' "
        "WHEN ra < 0.93 THEN 'rules.arm' WHEN ra < 0.95 THEN 'rules.disarm' "
        "WHEN ra < 0.96 THEN 'api_key.rotate' WHEN ra < 0.97 THEN 'admin.user_update' "
        "WHEN ra < 0.975 THEN 'admin.role_update' ELSE 'admin.flag_set' END AS act, "
        "jsonb_build_object('field_0', 'v' || (r3 * 1e6)::int, 'field_1', 'v' || (r4 * 1e6)::int, "
        "'field_' || (2 + g % 6), 'v' || (g % 1000003)) AS st "
        f"FROM (SELECT g, (g * 7919) % {USERS} AS u, random() AS ra, random() AS r1, "
        "random() AS r2, random() AS r3, random() AS r4, random() AS r5 "
        f"FROM generate_series({first}::bigint, {last}::bigint) g) s0) s"
    )


def cursor_literal(depth_fraction: float = 0.9) -> str:
    """Keyset cursor ``depth_fraction`` deep in DESC order (timestamps are linear in g)."""
    from datetime import datetime, timedelta

    start = datetime.fromisoformat(START_TS.replace("Z", "+00:00"))
    ts = start + timedelta(days=SPAN_DAYS) * (1.0 - depth_fraction)
    return ts.isoformat()


def build_query(where: str, cursor: str | None = None, materialized: bool = False) -> str:
    cur = f" AND event_ts < '{cursor}'" if cursor else ""
    head = "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
    if materialized:
        return (
            f"{head}WITH m AS MATERIALIZED (SELECT id, event_ts FROM audit_log "  # noqa: S608
            f"WHERE {where}{cur}) SELECT id FROM m{ORDER_LIMIT}"
        )
    return f"{head}SELECT id FROM audit_log WHERE {where}{cur}{ORDER_LIMIT}"  # noqa: S608


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile (q in 0..100); with n < 100 samples p99 == max."""
    if not values:
        raise ValueError("no samples")
    s = sorted(values)
    k = max(1, math.ceil(q / 100.0 * len(s)))
    return s[k - 1]


def _walk(node: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    yield node
    for child in node.get("Plans", ()) or ():
        yield from _walk(child)


def parse_plan(explain_json: Any) -> dict[str, Any]:
    """Execution time, node types and index names from ``EXPLAIN (FORMAT JSON)`` output."""
    doc = json.loads(explain_json) if isinstance(explain_json, str) else explain_json
    top = doc[0]
    nodes = list(_walk(top["Plan"]))
    return {
        "exec_ms": float(top["Execution Time"]),
        "node_types": sorted({str(n["Node Type"]) for n in nodes}),
        "indexes": sorted({str(n["Index Name"]) for n in nodes if "Index Name" in n}),
        "shared_hit": int(top["Plan"].get("Shared Hit Blocks", 0)),
        "shared_read": int(top["Plan"].get("Shared Read Blocks", 0)),
    }


def summarise(samples: Sequence[float]) -> dict[str, float]:
    return {
        "p50_ms": round(percentile(samples, 50), 3),
        "p95_ms": round(percentile(samples, 95), 3),
        "p99_ms": round(percentile(samples, 99), 3),
        "max_ms": round(max(samples), 3),
        "n": float(len(samples)),
    }


def verdict(p95_ms: float, budget_ms: float) -> str:
    return "meets" if p95_ms <= budget_ms else "MISS"


def write_report(path: Path, report: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    return path
