"""Test-only fixture-user seeder (QA #1658; lets ZAP/E2E log in).

Env-driven: CV_SEED_USERNAME, CV_SEED_PASSWORD, CV_PG_DSN. Refuses to run in
live/demo (C-2.11): only `CV_ENVIRONMENT=testnet` is accepted. Never prints
the password. Parameterised SQL only.

TEST-ONLY: seeds an owner with mfa_required=false so ZAP/E2E can log in without
TOTP. Never use outside testnet fixtures; `check_environment` rejects live/demo
(covered by test_seeder_refuses_outside_testnet).
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from candleviewer.auth.hashing import Hasher
from candleviewer.settings import Environment

_INSERT = sa.text("""
    INSERT INTO users (id, email, username, password_hash, status, mfa_required)
    VALUES (CAST(:id AS uuid), :email, :username, :h, 'active', false)
    ON CONFLICT DO NOTHING
    """)
_ROLE = sa.text("""
    INSERT INTO user_roles (user_id, role_id)
    SELECT u.id, r.id FROM users u, roles r
    WHERE u.username = :username AND r.name = 'owner' ON CONFLICT DO NOTHING
    """)


def check_environment(env: str) -> None:
    if env != Environment.TESTNET.value:
        raise SystemExit(f"refusing to seed a fixture user in environment {env!r} (C-2.11)")


async def seed(dsn: str, username: str, password: str, pepper: str = "") -> None:
    password_hash = await Hasher(pepper=pepper).hash(password)
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                _INSERT,
                {
                    "id": str(uuid.uuid4()),
                    "email": f"{username}@fixture.invalid",
                    "username": username,
                    "h": password_hash,
                },
            )
            await conn.execute(_ROLE, {"username": username})
    finally:
        await engine.dispose()


def main() -> int:
    check_environment(os.environ.get("CV_ENVIRONMENT", "demo"))
    asyncio.run(
        seed(
            os.environ["CV_PG_DSN"],
            os.environ["CV_SEED_USERNAME"],
            os.environ["CV_SEED_PASSWORD"],
            os.environ.get("CV_AUTH_PEPPER", ""),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
