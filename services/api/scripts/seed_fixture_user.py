"""Test-only fixture-user seeder (QA #1658; lets ZAP/E2E log in).

Env-driven: CV_SEED_USERNAME, CV_SEED_PASSWORD, CV_PG_DSN. Refuses to run in
live/demo (C-2.11): only `CV_ENVIRONMENT=testnet` is accepted. Never prints
the password. Parameterised SQL only.

The seeded owner has `mfa_required=true` by default (C-12: TOTP for every
user). `--allow-no-mfa` seeds it with `mfa_required=false`; that opt-in is a
registered, expiring exception (04-security-program.md Sec.16.2, EX-01) and
is refused outside testnet. Every seed writes `users.create` + `roles.grant`
audit rows in the same transaction (C-2.9).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from candleviewer.auth.hashing import Hasher
from candleviewer.settings import Environment

ACTOR_LABEL = "seed_fixture_user"

_INSERT = sa.text("""
    INSERT INTO users (id, email, username, password_hash, status, mfa_required)
    VALUES (CAST(:id AS uuid), :email, :username, :h, 'active', :mfa_required)
    ON CONFLICT DO NOTHING
    RETURNING id::text
    """)
_ROLE = sa.text("""
    INSERT INTO user_roles (user_id, role_id)
    SELECT u.id, r.id FROM users u, roles r
    WHERE u.username = :username AND r.name = 'owner' ON CONFLICT DO NOTHING
    """)
_AUDIT = sa.text("""
    INSERT INTO audit_log
        (record_id, actor_label, action, object_kind, object_id, outcome, severity,
         reason, after_state, event_ts)
    VALUES
        (CAST(:record_id AS uuid), :actor_label, :action, 'user', :object_id, 'success',
         'warning', :reason, CAST(:after_state AS jsonb), :event_ts)
    """)
_ADVISORY_LOCK = sa.text("SELECT pg_advisory_xact_lock(hashtext('audit_log'))")


def check_environment(env: str, *, allow_no_mfa: bool = False) -> None:
    """Refuse anything but testnet (C-2.11). `allow_no_mfa` is only ever
    meaningful on testnet, so it adds no extra path, only a second reason."""
    if env != Environment.TESTNET.value:
        what = "an MFA-less fixture owner" if allow_no_mfa else "a fixture user"
        raise SystemExit(f"refusing to seed {what} in environment {env!r} (C-2.11)")


async def _audit(
    conn: AsyncConnection, action: str, user_id: str, after: dict[str, object]
) -> None:
    await conn.execute(_ADVISORY_LOCK)
    await conn.execute(
        _AUDIT,
        {
            "record_id": str(uuid.uuid4()),
            "actor_label": ACTOR_LABEL,
            "action": action,
            "object_id": user_id,
            "reason": "test fixture seed (QA #1658)",
            "after_state": json.dumps(after, sort_keys=True),
            "event_ts": datetime.now(UTC),
        },
    )


async def seed(
    dsn: str, username: str, password: str, pepper: str = "", *, allow_no_mfa: bool = False
) -> str | None:
    """Seed one owner; returns the new user id, or None if it already existed."""
    password_hash = await Hasher(pepper=pepper).hash(password)
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            row = (
                await conn.execute(
                    _INSERT,
                    {
                        "id": str(uuid.uuid4()),
                        "email": f"{username}@fixture.invalid",
                        "username": username,
                        "h": password_hash,
                        "mfa_required": not allow_no_mfa,
                    },
                )
            ).first()
            if row is None:
                return None
            user_id = str(row[0])
            await conn.execute(_ROLE, {"username": username})
            await _audit(
                conn,
                "users.create",
                user_id,
                {"username": username, "mfa_required": not allow_no_mfa},
            )
            await _audit(conn, "roles.grant", user_id, {"role": "owner"})
            return user_id
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-no-mfa",
        action="store_true",
        help="seed with mfa_required=false (testnet only; exception EX-01)",
    )
    args = parser.parse_args(argv)
    check_environment(os.environ.get("CV_ENVIRONMENT", "demo"), allow_no_mfa=args.allow_no_mfa)
    asyncio.run(
        seed(
            os.environ["CV_PG_DSN"],
            os.environ["CV_SEED_USERNAME"],
            os.environ["CV_SEED_PASSWORD"],
            os.environ.get("CV_AUTH_PEPPER", ""),
            allow_no_mfa=args.allow_no_mfa,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
