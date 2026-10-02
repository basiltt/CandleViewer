"""E42-K01 spike: deterministic SYNTHETIC audit_log dataset generator.

Emits CSV (COPY-ready) with the production action mix: order actions dominate,
auth next, admin rare. All values are synthetic: usernames ``user_NN``, IPs from
the RFC 5737 documentation ranges, no production payloads (ticket Security notes).
Rows are written in ``event_ts`` order (append-only insert order). The hash-chain
columns are NOT generated: the load script lets the trigger compute them.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

ACTION_MIX: tuple[tuple[str, float], ...] = (
    ("orders.submit", 0.34),
    ("orders.cancel", 0.18),
    ("orders.amend", 0.08),
    ("orders.fill", 0.12),
    ("auth.login", 0.07),
    ("auth.refresh", 0.06),
    ("auth.logout", 0.03),
    ("auth.login_failed", 0.02),
    ("rules.arm", 0.03),
    ("rules.disarm", 0.02),
    ("api_key.rotate", 0.01),
    ("admin.user_update", 0.01),
    ("admin.role_update", 0.005),
    ("admin.flag_set", 0.005),
)
SEVERITIES = (("info", 0.95), ("warning", 0.035), ("error", 0.012), ("critical", 0.003))
OUTCOMES = (("success", 0.93), ("denied", 0.03), ("failure", 0.04))
KINDS = {
    "orders": "order",
    "auth": "session",
    "rules": "rule",
    "api_key": "api_key",
    "admin": "user",
}
COLUMNS = (
    "record_id",
    "actor_user_id",
    "actor_label",
    "actor_ip",
    "session_id",
    "action",
    "object_kind",
    "object_id",
    "object_label",
    "outcome",
    "severity",
    "reason",
    "before_state",
    "after_state",
    "request_id",
    "env",
    "event_ts",
)
ENVS = ("live", "demo", "testnet")


def _pick(rng: random.Random, table: tuple[tuple[str, float], ...]) -> str:
    return rng.choices([v for v, _ in table], [w for _, w in table])[0]


def _payload(rng: random.Random, action: str) -> str:
    """Synthetic JSON diff; size grows for admin actions (wide payloads for GIN)."""
    n = rng.randint(8, 40) if action.startswith("admin.") else rng.randint(2, 8)
    return json.dumps({f"field_{i}": f"v{rng.randint(0, 10**6)}" for i in range(n)})


def generate(
    rows: int, seed: int = 1, users: int = 50, start: datetime | None = None, span_days: int = 365
) -> Iterator[list[str]]:
    rng = random.Random(seed)  # noqa: S311 - synthetic data, not security
    t0 = start or datetime(2026, 1, 1, tzinfo=UTC)
    step = timedelta(days=span_days) / max(rows, 1)
    uids = [str(uuid.UUID(int=rng.getrandbits(128), version=4)) for _ in range(users)]
    for i in range(rows):
        action = _pick(rng, ACTION_MIX)
        domain = action.split(".")[0]
        u = rng.randrange(users)
        has_state = rng.random() < 0.7
        yield [
            str(uuid.UUID(int=rng.getrandbits(128), version=4)),
            uids[u],
            f"user_{u:02d}",
            f"192.0.2.{rng.randint(1, 254)}",
            str(uuid.UUID(int=rng.getrandbits(128), version=4)),
            action,
            KINDS[domain],
            f"obj-{rng.randint(1, 10**7)}",
            f"label {rng.randint(1, 999)}",
            _pick(rng, OUTCOMES),
            _pick(rng, SEVERITIES),
            "",
            _payload(rng, action) if has_state else "",
            _payload(rng, action) if has_state else "",
            str(uuid.UUID(int=rng.getrandbits(128), version=4)),
            _pick(rng, tuple((e, w) for e, w in zip(ENVS, (0.2, 0.7, 0.1), strict=True))),
            (t0 + step * i).isoformat(),
        ]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rows", type=int, default=10_000_000)
    p.add_argument("--seed", type=int, default=1)
    a = p.parse_args(argv)
    w = csv.writer(sys.stdout, lineterminator="\n")
    w.writerow(COLUMNS)
    for row in generate(a.rows, a.seed):
        w.writerow(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
