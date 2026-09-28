"""SQLAlchemy 2.0 Core `MetaData` — the autogenerate source of truth (§9.3
rule 12, `docs/plan/21-database-schema.md`).

Mirrors, as Core `Table` objects, the schema created by the hand-written SQL
in `candleviewer/migrations/versions/0001_identity_rbac_sessions_mfa.py`
(E09-T01) plus this ticket's `0002_rbac_seed` (bootstrap-owner seed only —
no new tables). Kept in lock-step by the `alembic check` CI gate (autogenerate
drift): a column added here without a matching revision, or vice versa, fails
that check. This module is deliberately Core-`Table`-based, not declarative
ORM classes — the ticket's deliverable is "SQLAlchemy 2.0 `MetaData`", and a
Core `Table` list is the smallest artefact that satisfies `alembic check`
without introducing an ORM mapping layer no code in this ticket's scope uses.

Enum types, the `sha256_hex` domain, and the two trigger functions
(`set_updated_at`, `trg_owner_floor_fn`) are DDL constructs Alembic/SQLAlchemy
Core cannot autogenerate-compare structurally the same way it does tables and
columns; they are asserted present by `services/api/tests/unit/migrations/`
instead (drift there would show as a failing hand-authored assertion, not a
silent `alembic check` false-negative).
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Table,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, BYTEA, CITEXT, ENUM, INET, JSONB, TIMESTAMP, UUID

#: §9.3 rule 12 — verbatim from `docs/plan/21-database-schema.md`.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "ux_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)

user_status = ENUM(
    "invited",
    "active",
    "disabled",
    "locked",
    name="user_status",
    metadata=metadata,
    create_type=False,
)
role_name = ENUM(
    "owner", "manager", "viewer", name="role_name", metadata=metadata, create_type=False
)
mfa_method_kind = ENUM(
    "totp",
    "webauthn",
    "recovery_code",
    name="mfa_method_kind",
    metadata=metadata,
    create_type=False,
)

#: The `sha256_hex` domain (`CREATE DOMAIN sha256_hex AS char(64) CHECK (...)`,
#: revision 0001) has no first-class SQLAlchemy Core type; a fixed-length
#: `String(64)` reflects the same on-wire shape for autogenerate comparison
#: purposes (`compare_type=True` diffs the underlying column type, not the
#: domain name, so this does not itself cause a drift failure).
_sha256_hex = String(64)

users = Table(
    "users",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("email", CITEXT, nullable=False),
    Column("username", CITEXT, nullable=False),
    Column("display_name", String),
    Column("password_hash", String, nullable=False),
    Column(
        "password_algo_params",
        JSONB,
        nullable=False,
        server_default=text('\'{"m":65536,"t":3,"p":4}\'::jsonb'),
    ),
    Column(
        "password_changed_at",
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    Column("status", user_status, nullable=False, server_default=text("'invited'")),
    Column("mfa_required", Boolean, nullable=False, server_default=text("true")),
    Column("failed_login_count", Integer, nullable=False, server_default=text("0")),
    Column("locked_until", TIMESTAMP(timezone=True)),
    Column("last_login_at", TIMESTAMP(timezone=True)),
    Column("last_login_ip", INET),
    Column("timezone", String, nullable=False, server_default=text("'UTC'")),
    Column("locale", String, nullable=False, server_default=text("'en-GB'")),
    Column("invited_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("deleted_at", TIMESTAMP(timezone=True)),
    CheckConstraint("position('@' in email) > 1", name="users_email_fmt"),
    CheckConstraint("char_length(username) BETWEEN 3 AND 32", name="users_uname_len"),
    CheckConstraint("password_hash LIKE '$argon2id$%'", name="users_pwd_argon"),
    CheckConstraint("failed_login_count >= 0", name="users_fail_nonneg"),
)

roles = Table(
    "roles",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("name", role_name, nullable=False, unique=True),
    Column("description", String, nullable=False, server_default=text("''")),
    Column("is_system", Boolean, nullable=False, server_default=text("true")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)

permissions = Table(
    "permissions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("code", String, nullable=False, unique=True),
    Column("domain", String, nullable=False),
    Column("description", String, nullable=False, server_default=text("''")),
    Column("is_dangerous", Boolean, nullable=False, server_default=text("false")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("code ~ '^[a-z0-9_]+:[a-z0-9_]+$'", name="permissions_code_fmt"),
)

role_permissions = Table(
    "role_permissions",
    metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
    Column("granted_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)

user_roles = Table(
    "user_roles",
    metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True),
    Column("granted_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("granted_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("expires_at", TIMESTAMP(timezone=True)),
    CheckConstraint("expires_at IS NULL OR expires_at > granted_at", name="user_roles_expiry"),
)

user_account_access = Table(
    "user_account_access",
    metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("exchange_account_id", UUID(as_uuid=True), primary_key=True),
    Column("can_trade", Boolean, nullable=False, server_default=text("false")),
    Column("can_view", Boolean, nullable=False, server_default=text("true")),
    Column("frozen", Boolean, nullable=False, server_default=text("false")),
    Column("frozen_at", TIMESTAMP(timezone=True)),
    Column("frozen_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("frozen_reason", String),
    Column("max_daily_loss_usd", Numeric(38, 18)),
    Column("granted_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("frozen = false OR frozen_at IS NOT NULL", name="uaa_frozen_consistency"),
    CheckConstraint("can_trade = false OR can_view = true", name="uaa_trade_implies_view"),
    CheckConstraint(
        "max_daily_loss_usd IS NULL OR max_daily_loss_usd > 0", name="uaa_loss_positive"
    ),
)

sessions = Table(
    "sessions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("refresh_token_hash", _sha256_hex, nullable=False, unique=True),
    Column("access_token_jti", UUID(as_uuid=True)),
    Column("issued_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("last_seen_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("expires_at", TIMESTAMP(timezone=True), nullable=False),
    Column("revoked_at", TIMESTAMP(timezone=True)),
    Column("revoked_reason", String),
    Column("ip", INET),
    Column("user_agent", String),
    Column("device_label", String),
    Column("is_electron", Boolean, nullable=False, server_default=text("false")),
    Column("mfa_satisfied_at", TIMESTAMP(timezone=True)),
    Column("tailscale_node", String),
    CheckConstraint("expires_at > issued_at", name="sessions_expiry"),
)

sessions_rotation = Table(
    "sessions_rotation",
    metadata,
    Column("prev_session_id", ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "next_session_id",
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column("rotated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)

mfa_methods = Table(
    "mfa_methods",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("kind", mfa_method_kind, nullable=False),
    Column("label", String, nullable=False, server_default=text("''")),
    Column("secret_enc", BYTEA),
    Column("secret_key_ref", String),
    Column("credential_id", BYTEA),
    Column("public_key", BYTEA),
    Column("sign_count", BigInteger, nullable=False, server_default=text("0")),
    Column("aaguid", UUID(as_uuid=True)),
    Column("transports", ARRAY(String)),
    Column("confirmed_at", TIMESTAMP(timezone=True)),
    Column("last_used_at", TIMESTAMP(timezone=True)),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("revoked_at", TIMESTAMP(timezone=True)),
    CheckConstraint("kind <> 'totp' OR secret_enc IS NOT NULL", name="mfa_totp_shape"),
    CheckConstraint(
        "kind <> 'webauthn' OR (credential_id IS NOT NULL AND public_key IS NOT NULL)",
        name="mfa_wa_shape",
    ),
)

mfa_challenges = Table(
    "mfa_challenges",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("session_id", ForeignKey("sessions.id", ondelete="CASCADE")),
    Column("kind", mfa_method_kind, nullable=False),
    Column("nonce", BYTEA, nullable=False),
    Column("purpose", String, nullable=False, server_default=text("'login'")),
    Column("attempts", SmallInteger, nullable=False, server_default=text("0")),
    Column("satisfied_at", TIMESTAMP(timezone=True)),
    Column("expires_at", TIMESTAMP(timezone=True), nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("attempts BETWEEN 0 AND 10", name="mfa_ch_attempts"),
    CheckConstraint("purpose IN ('login','step_up','enroll')", name="mfa_ch_purpose"),
)

recovery_codes = Table(
    "recovery_codes",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("code_hash", _sha256_hex, nullable=False),
    Column("used_at", TIMESTAMP(timezone=True)),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("user_id", "code_hash"),
)
