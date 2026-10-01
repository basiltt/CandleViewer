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
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import (
    ARRAY,
    BYTEA,
    CITEXT,
    DOMAIN,
    ENUM,
    INET,
    JSONB,
    TIMESTAMP,
    UUID,
)

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

exchange_env = ENUM(
    "live", "demo", "testnet", name="exchange_env", metadata=metadata, create_type=False
)
audit_outcome = ENUM(
    "success", "failure", "denied", name="audit_outcome", metadata=metadata, create_type=False
)
severity = ENUM(
    "debug",
    "info",
    "warning",
    "error",
    "critical",
    name="severity",
    metadata=metadata,
    create_type=False,
)


#: The `sha256_hex` DOMAIN (`CREATE DOMAIN sha256_hex AS char(64) CHECK (...)`,
#: revision 0001) is modelled as a first-class `postgresql.DOMAIN` so
#: `compare_type=True` diffs against the actual domain name/definition instead
#: of a same-shaped-but-different `String(64)` (which `alembic check` reports
#: as drift: DOMAIN vs. plain `character(64)`). `create_type=False` because the
#: domain is created by the hand-written SQL in revision 0001, not by
#: autogenerate/create_all.
_sha256_hex = DOMAIN(
    "sha256_hex",
    Text(),
    check="VALUE ~ '^[0-9a-f]{64}$'",
    create_type=False,
)

users = Table(
    "users",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "email",
        CITEXT,
        nullable=False,
        comment="PII: contact identifier; purge on account erase",
    ),
    Column("username", CITEXT, nullable=False),
    Column("display_name", Text, comment="PII: purge on account erase"),
    Column(
        "password_hash",
        Text,
        nullable=False,
        comment="SECRET: Argon2id digest; never logged, never returned by API",
    ),
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
    Column("last_login_ip", INET, comment="PII: purge on account erase"),
    Column("timezone", Text, nullable=False, server_default=text("'UTC'")),
    Column("locale", Text, nullable=False, server_default=text("'en-GB'")),
    Column("invited_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("deleted_at", TIMESTAMP(timezone=True)),
    CheckConstraint("position('@' in email) > 1", name="users_email_fmt"),
    CheckConstraint("char_length(username) BETWEEN 3 AND 32", name="users_uname_len"),
    CheckConstraint("password_hash LIKE '$argon2id$%'", name="users_pwd_argon"),
    CheckConstraint("failed_login_count >= 0", name="users_fail_nonneg"),
    Index("ux_users_email", "email", unique=True, postgresql_where=text("deleted_at IS NULL")),
    Index(
        "ux_users_username", "username", unique=True, postgresql_where=text("deleted_at IS NULL")
    ),
    Index("ix_users_status", "status", postgresql_where=text("deleted_at IS NULL")),
)

roles = Table(
    "roles",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("name", role_name, nullable=False),
    Column("description", Text, nullable=False, server_default=text("''")),
    Column("is_system", Boolean, nullable=False, server_default=text("true")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("name", name="roles_name_key"),
)

permissions = Table(
    "permissions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("code", Text, nullable=False),
    Column("domain", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=text("''")),
    Column("is_dangerous", Boolean, nullable=False, server_default=text("false")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("code ~ '^[a-z0-9_]+:[a-z0-9_]+$'", name="permissions_code_fmt"),
    UniqueConstraint("code", name="permissions_code_key"),
)

role_permissions = Table(
    "role_permissions",
    metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
    Column("granted_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Index("ix_role_permissions_perm", "permission_id"),
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
    Index("ix_user_roles_role", "role_id"),
)

user_invites = Table(
    "user_invites",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("role", role_name, nullable=False),
    Column(
        "token_hash",
        Text,
        nullable=False,
        comment="SECRET-DERIVED: sha256 hex of the one-time invite token",
    ),
    Column("invited_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("expires_at", TIMESTAMP(timezone=True), nullable=False),
    Column("consumed_at", TIMESTAMP(timezone=True)),
    Column(
        "pending_password_hash",
        Text,
        comment="SECRET: Argon2id digest held until TOTP enrolment completes",
    ),
    Column("revoked_at", TIMESTAMP(timezone=True)),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("char_length(token_hash) = 64", name="user_invites_hash_fmt"),
    CheckConstraint("expires_at > created_at", name="user_invites_expiry"),
    Index("ux_user_invites_token_hash", "token_hash", unique=True),
    Index("ix_user_invites_user", "user_id"),
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
    Column("frozen_reason", Text),
    Column("max_daily_loss_usd", Numeric(38, 18)),
    Column("granted_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("frozen = false OR frozen_at IS NOT NULL", name="uaa_frozen_consistency"),
    CheckConstraint("can_trade = false OR can_view = true", name="uaa_trade_implies_view"),
    CheckConstraint(
        "max_daily_loss_usd IS NULL OR max_daily_loss_usd > 0", name="uaa_loss_positive"
    ),
    Index("ix_uaa_account", "exchange_account_id", postgresql_where=text("can_trade")),
    Index("ix_uaa_frozen", "exchange_account_id", postgresql_where=text("frozen")),
    comment=(
        "exchange_account_id has no FK yet: exchange_accounts is created by E27; "
        "that migration adds fk_user_account_access_exchange_account_id_exchange_accounts."
    ),
)

sessions = Table(
    "sessions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column(
        "refresh_token_hash",
        _sha256_hex,
        nullable=False,
        comment="SECRET: SHA-256 of the raw refresh token; raw token never stored",
    ),
    Column("access_token_jti", UUID(as_uuid=True)),
    Column("issued_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("last_seen_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("expires_at", TIMESTAMP(timezone=True), nullable=False),
    Column("revoked_at", TIMESTAMP(timezone=True)),
    Column("revoked_reason", Text),
    Column("ip", INET, comment="PII: purge on account erase / retention job"),
    Column("user_agent", Text, comment="PII: purge on account erase / retention job"),
    Column("device_label", Text),
    Column("is_electron", Boolean, nullable=False, server_default=text("false")),
    Column("mfa_satisfied_at", TIMESTAMP(timezone=True)),
    Column(
        "tailscale_node",
        Text,
        comment="PII-adjacent: node identity from Tailscale header",
    ),
    Column(
        "idle_timeout_s",
        Integer,
        nullable=False,
        server_default=text("900"),
        comment=(
            "Per-session idle-lock timeout in seconds (5-60 min, default 15); "
            "the idle deadline is last_seen_at + this."
        ),
    ),
    Column(
        "step_up_elevations",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment=(
            'Step-up elevation per action class: {"<action_class>": '
            '"<expiry ISO-8601 UTC>"} (E09-S04).'
        ),
    ),
    Column(
        "step_up_failures",
        SmallInteger,
        nullable=False,
        server_default=text("0"),
        comment="Consecutive invalid step-up codes; 3 triggers the read-only downgrade (E09-S04).",
    ),
    Column(
        "readonly_until",
        TIMESTAMP(timezone=True),
        comment=(
            "Read-only downgrade expiry after 3 failed step-up codes (E09-S04); NULL = writable."
        ),
    ),
    CheckConstraint("expires_at > issued_at", name="sessions_expiry"),
    CheckConstraint("idle_timeout_s BETWEEN 300 AND 3600", name="sessions_idle_timeout_range"),
    CheckConstraint("step_up_failures BETWEEN 0 AND 3", name="sessions_step_up_failures_range"),
    UniqueConstraint("refresh_token_hash", name="sessions_refresh_token_hash_key"),
    Index("ix_sessions_user_live", "user_id", postgresql_where=text("revoked_at IS NULL")),
    Index("ix_sessions_expiry", "expires_at", postgresql_where=text("revoked_at IS NULL")),
)

sessions_rotation = Table(
    "sessions_rotation",
    metadata,
    Column("prev_session_id", ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "next_session_id",
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("rotated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("next_session_id", name="sessions_rotation_next_session_id_key"),
)

mfa_methods = Table(
    "mfa_methods",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("kind", mfa_method_kind, nullable=False),
    Column("label", Text, nullable=False, server_default=text("''")),
    Column(
        "secret_enc",
        BYTEA,
        comment="SECRET: envelope-encrypted TOTP seed; plaintext only in services/api/secrets/",
    ),
    Column("secret_key_ref", Text),
    Column("credential_id", BYTEA),
    Column("public_key", BYTEA),
    Column("sign_count", BigInteger, nullable=False, server_default=text("0")),
    Column("aaguid", UUID(as_uuid=True)),
    Column("transports", ARRAY(Text)),
    Column("confirmed_at", TIMESTAMP(timezone=True)),
    Column("last_used_at", TIMESTAMP(timezone=True)),
    Column(
        "last_accepted_time_step",
        BigInteger,
        comment=(
            "Highest RFC 6238 time-step accepted so far for this method; a step <= this\n"
            '   value is a replay and must be rejected (ticket E09-S02 "Reused code is\n'
            '   rejected"). NULL means no code has ever been accepted.'
        ),
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("revoked_at", TIMESTAMP(timezone=True)),
    CheckConstraint("kind <> 'totp' OR secret_enc IS NOT NULL", name="mfa_totp_shape"),
    CheckConstraint(
        "kind <> 'webauthn' OR (credential_id IS NOT NULL AND public_key IS NOT NULL)",
        name="mfa_wa_shape",
    ),
    Index(
        "ux_mfa_webauthn_cred",
        "credential_id",
        unique=True,
        postgresql_where=text("credential_id IS NOT NULL"),
    ),
    Index("ix_mfa_user_active", "user_id", postgresql_where=text("revoked_at IS NULL")),
)

mfa_challenges = Table(
    "mfa_challenges",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("session_id", ForeignKey("sessions.id", ondelete="CASCADE")),
    Column("kind", mfa_method_kind, nullable=False),
    Column("nonce", BYTEA, nullable=False, comment="SECRET: anti-replay challenge nonce"),
    Column("purpose", Text, nullable=False, server_default=text("'login'")),
    Column("attempts", SmallInteger, nullable=False, server_default=text("0")),
    Column("satisfied_at", TIMESTAMP(timezone=True)),
    Column("expires_at", TIMESTAMP(timezone=True), nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("attempts BETWEEN 0 AND 10", name="mfa_ch_attempts"),
    CheckConstraint("purpose IN ('login','step_up','enroll')", name="mfa_ch_purpose"),
    Index(
        "ix_mfa_ch_user_open",
        "user_id",
        "expires_at",
        postgresql_where=text("satisfied_at IS NULL"),
    ),
)

recovery_codes = Table(
    "recovery_codes",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column(
        "code_hash",
        _sha256_hex,
        nullable=False,
        comment="SECRET: SHA-256 of the one-time recovery code",
    ),
    Column("used_at", TIMESTAMP(timezone=True)),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("user_id", "code_hash", name="recovery_codes_user_id_code_hash_key"),
    Index("ix_recovery_unused", "user_id", postgresql_where=text("used_at IS NULL")),
)

#: `audit_log` / `audit_checkpoints` (E09-T02, revision 0003_audit_log).
#: `prev_hash`/`entry_hash` are populated by the `audit_chain()` trigger, never
#: by the app (`server_default` intentionally omitted — a bare `bigserial`-style
#: PK plus trigger-computed columns has no default SQLAlchemy can express, so
#: they are simply `nullable=False` here to match the trigger's guarantee).
audit_log = Table(
    "audit_log",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column(
        "record_id",
        UUID(as_uuid=True),
        nullable=False,
        comment=(
            "Writer-assigned idempotency key: WAL replay is ON CONFLICT (record_id) DO NOTHING"
        ),
    ),
    Column("prev_hash", _sha256_hex, nullable=False),
    Column("entry_hash", _sha256_hex, nullable=False),
    Column("actor_user_id", ForeignKey("users.id", ondelete="SET NULL")),
    Column("actor_label", Text, nullable=False),
    Column("actor_ip", INET, comment="PII: purge on account erase / retention job"),
    Column("session_id", UUID(as_uuid=True)),
    Column("action", Text, nullable=False),
    Column("object_kind", Text),
    Column("object_id", Text),
    Column("object_label", Text),
    Column("outcome", audit_outcome, nullable=False, server_default=text("'success'")),
    Column("severity", severity, nullable=False, server_default=text("'info'")),
    Column("reason", Text),
    Column(
        "before_state",
        JSONB,
        comment=(
            "Redacted diff source — SECRET-classified fields must never appear "
            "here (candleviewer.audit.redact)"
        ),
    ),
    Column(
        "after_state",
        JSONB,
        comment=(
            "Redacted diff source — SECRET-classified fields must never appear "
            "here (candleviewer.audit.redact)"
        ),
    ),
    Column("request_id", UUID(as_uuid=True)),
    Column("env", exchange_env),
    Column("event_ts", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("action ~ '^[a-z0-9_]+([.][a-z0-9_]+){1,3}$'", name="au_action_fmt"),
    UniqueConstraint("record_id", name="audit_log_record_id_key"),
    UniqueConstraint("entry_hash", name="audit_log_entry_hash_key"),
    Index("ix_audit_time", text("event_ts DESC")),
    Index("ix_audit_actor", "actor_user_id", text("event_ts DESC")),
    Index("ix_audit_action", "action", text("event_ts DESC")),
    Index("ix_audit_object", "object_kind", "object_id", text("event_ts DESC")),
    Index(
        "ix_audit_sev",
        "severity",
        text("event_ts DESC"),
        postgresql_where=text("severity IN ('error','critical')"),
    ),
)

audit_checkpoints = Table(
    "audit_checkpoints",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("head_id", BigInteger, nullable=False),
    Column("head_hash", _sha256_hex, nullable=False),
    Column("row_count", BigInteger, nullable=False),
    Column("signed_by", Text, nullable=False, server_default=text("'cv-audit-key-v1'")),
    Column("signature", BYTEA),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("head_id", name="audit_checkpoints_head_id_key"),
)

#: `instruments` / `instrument_versions` (E08-S01, revision 0004_instruments).
#: `symbol_code` and `exchange_code` are DDL-level DOMAIN/ENUM constructs
#: created by 0004 itself (no earlier revision scoped them — see that
#: revision's module docstring); modelled the same way `_sha256_hex` models
#: the `sha256_hex` domain above, with `create_type=False` for both.
symbol_code = DOMAIN(
    "symbol_code",
    Text(),
    check="VALUE ~ '^[A-Z0-9]{4,20}$'",
    create_type=False,
)
# nosemgrep: cv-adapter-isolation -- DB schema mirror of the 0004_instruments
# DDL's `exchange_code` enum (E08-S01): this is the storage-layer value
# domain, not adapter logic; C-1.3 scopes this whole product to that single
# exchange, so the enum member is a schema fact, not leaked adapter vocab.
exchange_code = ENUM(
    "bybit",  # nosemgrep: cv-adapter-isolation
    name="exchange_code",
    metadata=metadata,
    create_type=False,
)

instruments = Table(
    "instruments",
    metadata,
    Column("symbol", symbol_code, primary_key=True),
    # nosemgrep: cv-adapter-isolation -- see exchange_code above.
    Column("exchange", exchange_code, nullable=False, server_default=text("'bybit'")),
    Column("category", Text, nullable=False, server_default=text("'linear'")),
    Column("base_coin", Text, nullable=False),
    Column("quote_coin", Text, nullable=False, server_default=text("'USDT'")),
    Column("settle_coin", Text, nullable=False, server_default=text("'USDT'")),
    Column("status", Text, nullable=False),
    Column("tick_size", Numeric(38, 18), nullable=False),
    Column("qty_step", Numeric(38, 18), nullable=False),
    Column("min_order_qty", Numeric(38, 18), nullable=False),
    Column("max_order_qty", Numeric(38, 18), nullable=False),
    Column("min_notional_value", Numeric(38, 18)),
    Column("max_leverage", Numeric(10, 2), nullable=False),
    Column("leverage_step", Numeric(10, 2), nullable=False, server_default=text("0.01")),
    Column("price_scale", SmallInteger, nullable=False, server_default=text("2")),
    Column("funding_interval_min", Integer, nullable=False, server_default=text("480")),
    Column("launch_ts", TIMESTAMP(timezone=True)),
    Column("delivery_ts", TIMESTAMP(timezone=True)),
    Column("metadata_version", Integer, nullable=False, server_default=text("1")),
    Column(
        "raw",
        JSONB,
        nullable=False,
        comment=(
            "Full, unredacted instruments-info payload for this symbol, for "
            "audit and forward-compat fields."
        ),
    ),
    Column("refreshed_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("stale_since", TIMESTAMP(timezone=True)),
    CheckConstraint("category = 'linear'", name="inst_cat"),
    CheckConstraint("quote_coin = 'USDT'", name="inst_quote"),
    CheckConstraint("tick_size > 0 AND qty_step > 0", name="inst_ticks"),
    CheckConstraint("max_order_qty >= min_order_qty", name="inst_qty_rng"),
    CheckConstraint("metadata_version >= 1", name="inst_version"),
    Index("ix_instruments_status", "status"),
)

instrument_versions = Table(
    "instrument_versions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column(
        "symbol",
        symbol_code,
        ForeignKey("instruments.symbol", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("metadata_version", Integer, nullable=False),
    Column("tick_size", Numeric(38, 18), nullable=False),
    Column("qty_step", Numeric(38, 18), nullable=False),
    Column("min_order_qty", Numeric(38, 18), nullable=False),
    Column("max_order_qty", Numeric(38, 18), nullable=False),
    Column("min_notional_value", Numeric(38, 18)),
    Column("max_leverage", Numeric(10, 2), nullable=False),
    Column("leverage_step", Numeric(10, 2), nullable=False),
    Column("price_scale", SmallInteger, nullable=False),
    Column("funding_interval_min", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column(
        "changed_fields",
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'"),
        comment=(
            "Field names that differed from the immediately preceding version, "
            "for InstrumentUpdatedEvent.changed_fields."
        ),
    ),
    Column(
        "raw",
        JSONB,
        nullable=False,
    ),
    Column("recorded_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("metadata_version >= 1", name="iv_version"),
    UniqueConstraint("symbol", "metadata_version", name="iv_unique_version"),
    Index("ix_instrument_versions_symbol", "symbol", text("metadata_version DESC")),
)

#: `system_events` (E04-T04, revision 0008_system_events).
system_events = Table(
    "system_events",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("component", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("severity", severity, nullable=False, server_default=text("'info'")),
    Column("symbol", symbol_code),
    Column("exchange_account_id", UUID(as_uuid=True)),
    Column("message", Text, nullable=False),
    Column("details", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("ret_code", Text),
    Column("correlation_id", UUID(as_uuid=True)),
    Column("resolved_at", TIMESTAMP(timezone=True)),
    Column("resolved_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("event_ts", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "component IN ('ingestion','book_engine','bars','orderflow','oms','rules','recorder',"
        "'replay','api','ws','db','exchange','auth','backup')",
        name="se_component",
    ),
    Index("ix_se_time", text("event_ts DESC")),
    Index(
        "ix_se_sev_open",
        "severity",
        text("event_ts DESC"),
        postgresql_where=text("resolved_at IS NULL"),
    ),
    Index("ix_se_component", "component", text("event_ts DESC")),
    Index(
        "ix_se_symbol",
        "symbol",
        text("event_ts DESC"),
        postgresql_where=text("symbol IS NOT NULL"),
    ),
)
