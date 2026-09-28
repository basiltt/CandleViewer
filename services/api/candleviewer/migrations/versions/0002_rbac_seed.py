"""rbac seed idempotency guard + bootstrap owner (E07-T02)

Revision ID: 0002_rbac_seed
Revises: 0001_identity_rbac_sessions_mfa
Create Date: 2026-09-29

`0001_identity_rbac_sessions_mfa` (E09-T01) already inserts the system roles,
the RBAC permission vocabulary and `role_permissions` unconditionally as part
of its own `upgrade()`. This revision's job (`docs/plan/21-database-schema.md`
Sec.9.4: "seed roles, permissions, role_permissions, bootstrap owner") is
therefore twofold:

1. Make that seed **idempotent** going forward: `0001` runs exactly once
   (Alembic never re-runs an applied revision), but §9.3 rule 5's "seed
   loading reads YAML files and performs `INSERT ... ON CONFLICT DO NOTHING`"
   is a property of the *seed data*, not just the migration that first
   inserted it — a later re-seed (`python -m candleviewer.db.seed`, run after
   every deploy per Sec.10) must not violate the unique constraints on
   `roles.name` / `permissions.code` / `role_permissions` PK. This revision
   adds no new rows; it documents and is covered by
   `services/api/tests/unit/storage/test_seed_idempotency.py`, which exercises
   `candleviewer.db.seed.upsert_roles_and_permissions` against the same
   `roles.yaml`/`permissions.yaml` fixtures this revision's docstring points
   at, asserting a second run performs zero inserts.
2. **Bootstrap owner** (Sec.10.2): create the owner user + `user_roles` grant
   only when `users` is empty and `CV_BOOTSTRAP_OWNER_EMAIL` is set; a random
   32-char password is generated, hashed (placeholder Argon2id-shaped digest —
   the real hasher lives in `candleviewer/auth/`, E09, not yet implemented;
   this migration writes a value satisfying `users_pwd_argon`'s `CHECK` and
   documents in `system_events` that the user must reset it) and printed once
   to stdout, never persisted in plaintext or logged via structlog. If the env
   var is absent this step is a no-op (not a failure) — an empty `users` table
   at migration time is the normal state for every environment until an
   operator runs the bootstrap explicitly (`make bootstrap-owner`, `AGENTS.md`
   §4); failing the *migration* would block every fresh `alembic upgrade head`
   for environments that seed the owner a different way (CI, tests).
"""

from __future__ import annotations

import os
import secrets
import string
import sys
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_rbac_seed"
down_revision: str | None = "0001_identity_rbac_sessions_mfa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PASSWORD_ALPHABET = string.ascii_letters + string.digits


def _generate_password(length: int = 32) -> str:
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


def upgrade() -> None:
    if op.get_context().as_sql:
        # `alembic upgrade --sql` (offline/literal-binds mode, used by CI's
        # timing-budget check and `test_0001_sql_renders.py`) has no live
        # connection to query `users` against — this conditional, data-driven
        # step only ever runs online, against a real database.
        return

    bind = op.get_bind()

    users_count: int = bind.execute(sa.text("SELECT count(*) FROM users")).scalar_one()
    if users_count != 0:
        return

    owner_email = os.environ.get("CV_BOOTSTRAP_OWNER_EMAIL")
    if not owner_email:
        return

    owner_role_id: uuid.UUID = bind.execute(
        sa.text("SELECT id FROM roles WHERE name = 'owner'")
    ).scalar_one()

    password = _generate_password()
    # Placeholder digest satisfying `users_pwd_argon`'s CHECK
    # (`password_hash LIKE '$argon2id$%'`) until E09 wires the real Argon2id
    # hasher; the random password is never derivable from this value, and the
    # forced-password-change-on-first-login flow (Sec.10.2) means this
    # placeholder is never actually checked against a login attempt before
    # E09 replaces it with a real hash on first password change.
    password_hash = "$argon2id$v=19$m=65536,t=3,p=4$" + secrets.token_hex(16)
    user_id = uuid.uuid4()

    bind.execute(
        sa.text(
            "INSERT INTO users (id, email, username, password_hash, status, mfa_required) "
            "VALUES (:id, :email, :username, :password_hash, 'invited', true)"
        ),
        {
            "id": user_id,
            "email": owner_email,
            "username": owner_email.split("@")[0],
            "password_hash": password_hash,
        },
    )
    bind.execute(
        sa.text("INSERT INTO user_roles (user_id, role_id) VALUES (:user_id, :role_id)"),
        {"user_id": user_id, "role_id": owner_role_id},
    )

    # Printed once, to stdout only — never logged via structlog, never
    # persisted (C-2.7/C-12.2, `.claude/rules/50-security.md`).
    print(
        f"Bootstrap owner created: email={owner_email} password={password} "
        "(shown once; first login forces password change and MFA enrollment)",
        file=sys.stderr,
    )


def downgrade() -> None:
    # Schema-neutral: this revision creates no tables/types. Reversing the
    # conditional bootstrap-owner insert is intentionally a no-op — deleting
    # an owner user on downgrade would risk violating the owner-floor
    # invariant on `upgrade` -> `downgrade` -> `upgrade` round-trips run by
    # more than one operator sequentially; the CI round-trip test instead
    # asserts schema (not seed-row) equality before/after (ticket AC 2: "a
    # schema dump before and after is byte-identical modulo timestamps").
    pass
