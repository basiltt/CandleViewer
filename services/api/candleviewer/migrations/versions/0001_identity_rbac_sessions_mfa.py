"""identity, RBAC, sessions and MFA tables (E09-T01)

Revision ID: 0001_identity_rbac_sessions_mfa
Revises:
Create Date: 2026-09-27

Creates, verbatim against `docs/plan/21-database-schema.md` Sec.3.1 and
Sec.10.1, the identity/RBAC/session/MFA schema: enums `user_status`,
`role_name`, `mfa_method_kind`; the `sha256_hex` domain; tables `users`,
`roles`, `permissions`, `role_permissions`, `user_roles`,
`user_account_access`, `sessions`, `sessions_rotation`, `mfa_methods`,
`mfa_challenges`, `recovery_codes`; every listed index and CHECK
constraint; the deferred owner-floor trigger `trg_owner_floor`; and the
seed rows for the three system roles and the RBAC permission vocabulary.

Out of scope (per the ticket): `audit_log` (E09-T02), `exchange_accounts` /
`api_keys` / `account_profiles` (E27). `user_account_access.exchange_account_id`
is therefore created WITHOUT a foreign key to `exchange_accounts` — E27's
migration must add
`ALTER TABLE user_account_access ADD CONSTRAINT
fk_user_account_access_exchange_account_id_exchange_accounts
FOREIGN KEY (exchange_account_id) REFERENCES exchange_accounts(id) ON DELETE CASCADE;`
once that table exists (expand/migrate/contract, `21-database-schema.md` Sec.9.3
rule 4). This deviation is called out in the PR body.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_identity_rbac_sessions_mfa"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)


_UPGRADE_SQL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TYPE user_status     AS ENUM ('invited','active','disabled','locked');
CREATE TYPE role_name       AS ENUM ('owner','manager','viewer');
CREATE TYPE mfa_method_kind AS ENUM ('totp','webauthn','recovery_code');

CREATE DOMAIN sha256_hex AS char(64) CHECK (VALUE ~ '^[0-9a-f]{64}$');

CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $BODY$
BEGIN NEW.updated_at := now(); RETURN NEW; END $BODY$;

CREATE TABLE users (
  id                   uuid PRIMARY KEY,
  email                citext NOT NULL,
  username             citext NOT NULL,
  display_name         text,
  password_hash        text NOT NULL,
  password_algo_params jsonb NOT NULL DEFAULT '{"m":65536,"t":3,"p":4}'::jsonb,
  password_changed_at  timestamptz NOT NULL DEFAULT now(),
  status               user_status NOT NULL DEFAULT 'invited',
  mfa_required         boolean NOT NULL DEFAULT true,
  failed_login_count   integer NOT NULL DEFAULT 0,
  locked_until         timestamptz,
  last_login_at        timestamptz,
  last_login_ip        inet,
  timezone             text NOT NULL DEFAULT 'UTC',
  locale               text NOT NULL DEFAULT 'en-GB',
  invited_by           uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  deleted_at           timestamptz,
  CONSTRAINT users_email_fmt   CHECK (position('@' in email) > 1),
  CONSTRAINT users_uname_len   CHECK (char_length(username) BETWEEN 3 AND 32),
  CONSTRAINT users_pwd_argon   CHECK (password_hash LIKE '$argon2id$%'),
  CONSTRAINT users_fail_nonneg CHECK (failed_login_count >= 0)
);
CREATE UNIQUE INDEX ux_users_email    ON users (email)    WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX ux_users_username ON users (username) WHERE deleted_at IS NULL;
CREATE INDEX ix_users_status ON users (status) WHERE deleted_at IS NULL;
CREATE TRIGGER trg_users_touch BEFORE UPDATE ON users
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
COMMENT ON COLUMN users.email IS 'PII: contact identifier; purge on account erase';
COMMENT ON COLUMN users.display_name IS 'PII: purge on account erase';
COMMENT ON COLUMN users.last_login_ip IS 'PII: purge on account erase';
COMMENT ON COLUMN users.password_hash IS 'SECRET: Argon2id digest; never logged, never returned by API';

CREATE TABLE roles (
  id          uuid PRIMARY KEY,
  name        role_name NOT NULL UNIQUE,
  description text NOT NULL DEFAULT '',
  is_system   boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_roles_touch BEFORE UPDATE ON roles
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE permissions (
  id           uuid PRIMARY KEY,
  code         text NOT NULL UNIQUE,
  domain       text NOT NULL,
  description  text NOT NULL DEFAULT '',
  is_dangerous boolean NOT NULL DEFAULT false,
  created_at   timestamptz NOT NULL DEFAULT now(),
  -- NOTE (deviation, see module docstring): 21-database-schema.md Sec.3.1.2's own
  -- example regex ('orders.submit.live', dot-separated) predates the colon-separated
  -- 'domain:action' vocabulary actually seeded from 22-api-openapi.yaml x-rbac.permissions
  -- (Sec.10.1 of the same document). The regex below matches the real, current vocabulary;
  -- flagged for a docs fix-forward in the PR rather than silently diverging from the seed.
  CONSTRAINT permissions_code_fmt CHECK (code ~ '^[a-z0-9_]+:[a-z0-9_]+$')
);

CREATE TABLE role_permissions (
  role_id       uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  permission_id uuid NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
  granted_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (role_id, permission_id)
);
CREATE INDEX ix_role_permissions_perm ON role_permissions (permission_id);

CREATE TABLE user_roles (
  user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id    uuid NOT NULL REFERENCES roles(id) ON DELETE RESTRICT,
  granted_by uuid REFERENCES users(id) ON DELETE SET NULL,
  granted_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz,
  PRIMARY KEY (user_id, role_id),
  CONSTRAINT user_roles_expiry CHECK (expires_at IS NULL OR expires_at > granted_at)
);
CREATE INDEX ix_user_roles_role ON user_roles (role_id);

CREATE TABLE user_account_access (
  user_id             uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  exchange_account_id uuid NOT NULL,
  can_trade           boolean NOT NULL DEFAULT false,
  can_view            boolean NOT NULL DEFAULT true,
  frozen              boolean NOT NULL DEFAULT false,
  frozen_at           timestamptz,
  frozen_by           uuid REFERENCES users(id) ON DELETE SET NULL,
  frozen_reason       text,
  max_daily_loss_usd  numeric(38,18),
  granted_by          uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, exchange_account_id),
  CONSTRAINT uaa_frozen_consistency CHECK (frozen = false OR frozen_at IS NOT NULL),
  CONSTRAINT uaa_trade_implies_view CHECK (can_trade = false OR can_view = true),
  CONSTRAINT uaa_loss_positive      CHECK (max_daily_loss_usd IS NULL OR max_daily_loss_usd > 0)
);
CREATE INDEX ix_uaa_account ON user_account_access (exchange_account_id) WHERE can_trade;
CREATE INDEX ix_uaa_frozen  ON user_account_access (exchange_account_id) WHERE frozen;
CREATE TRIGGER trg_uaa_touch BEFORE UPDATE ON user_account_access
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
COMMENT ON TABLE user_account_access IS
  'exchange_account_id has no FK yet: exchange_accounts is created by E27; '
  'that migration adds fk_user_account_access_exchange_account_id_exchange_accounts.';

CREATE TABLE sessions (
  id                 uuid PRIMARY KEY,
  user_id            uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  refresh_token_hash sha256_hex NOT NULL UNIQUE,
  access_token_jti   uuid,
  issued_at          timestamptz NOT NULL DEFAULT now(),
  last_seen_at       timestamptz NOT NULL DEFAULT now(),
  expires_at         timestamptz NOT NULL,
  revoked_at         timestamptz,
  revoked_reason     text,
  ip                 inet,
  user_agent         text,
  device_label       text,
  is_electron        boolean NOT NULL DEFAULT false,
  mfa_satisfied_at   timestamptz,
  tailscale_node     text,
  CONSTRAINT sessions_expiry CHECK (expires_at > issued_at)
);
CREATE INDEX ix_sessions_user_live ON sessions (user_id) WHERE revoked_at IS NULL;
CREATE INDEX ix_sessions_expiry    ON sessions (expires_at) WHERE revoked_at IS NULL;
COMMENT ON COLUMN sessions.ip IS 'PII: purge on account erase / retention job';
COMMENT ON COLUMN sessions.user_agent IS 'PII: purge on account erase / retention job';
COMMENT ON COLUMN sessions.tailscale_node IS 'PII-adjacent: node identity from Tailscale header';
COMMENT ON COLUMN sessions.refresh_token_hash IS 'SECRET: SHA-256 of the raw refresh token; raw token never stored';

CREATE TABLE sessions_rotation (
  prev_session_id uuid PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
  next_session_id uuid NOT NULL UNIQUE REFERENCES sessions(id) ON DELETE CASCADE,
  rotated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE mfa_methods (
  id             uuid PRIMARY KEY,
  user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind           mfa_method_kind NOT NULL,
  label          text NOT NULL DEFAULT '',
  secret_enc     bytea,
  secret_key_ref text,
  credential_id  bytea,
  public_key     bytea,
  sign_count     bigint NOT NULL DEFAULT 0,
  aaguid         uuid,
  transports     text[],
  confirmed_at   timestamptz,
  last_used_at   timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  revoked_at     timestamptz,
  CONSTRAINT mfa_totp_shape CHECK (kind <> 'totp' OR secret_enc IS NOT NULL),
  CONSTRAINT mfa_wa_shape   CHECK (kind <> 'webauthn' OR (credential_id IS NOT NULL AND public_key IS NOT NULL))
);
CREATE UNIQUE INDEX ux_mfa_webauthn_cred ON mfa_methods (credential_id) WHERE credential_id IS NOT NULL;
CREATE INDEX ix_mfa_user_active ON mfa_methods (user_id) WHERE revoked_at IS NULL;
CREATE TRIGGER trg_mfa_methods_touch BEFORE UPDATE ON mfa_methods
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
COMMENT ON COLUMN mfa_methods.secret_enc IS 'SECRET: envelope-encrypted TOTP seed; plaintext only in services/api/secrets/';

CREATE TABLE mfa_challenges (
  id           uuid PRIMARY KEY,
  user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_id   uuid REFERENCES sessions(id) ON DELETE CASCADE,
  kind         mfa_method_kind NOT NULL,
  nonce        bytea NOT NULL,
  purpose      text NOT NULL DEFAULT 'login',
  attempts     smallint NOT NULL DEFAULT 0,
  satisfied_at timestamptz,
  expires_at   timestamptz NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT mfa_ch_attempts CHECK (attempts BETWEEN 0 AND 10),
  CONSTRAINT mfa_ch_purpose  CHECK (purpose IN ('login','step_up','enroll'))
);
CREATE INDEX ix_mfa_ch_user_open ON mfa_challenges (user_id, expires_at) WHERE satisfied_at IS NULL;
COMMENT ON COLUMN mfa_challenges.nonce IS 'SECRET: anti-replay challenge nonce';

CREATE TABLE recovery_codes (
  id         uuid PRIMARY KEY,
  user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code_hash  sha256_hex NOT NULL,
  used_at    timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, code_hash)
);
CREATE INDEX ix_recovery_unused ON recovery_codes (user_id) WHERE used_at IS NULL;
COMMENT ON COLUMN recovery_codes.code_hash IS 'SECRET: SHA-256 of the one-time recovery code';

-- Owner-floor invariant (21-database-schema.md Sec.3.1.2): at least one active
-- user must hold role 'owner'. DEFERRABLE INITIALLY DEFERRED so a single
-- transaction may remove-then-re-add an owner role; only the end-of-transaction
-- state is checked. Raises SQLSTATE 23514 (check_violation) on violation.
CREATE FUNCTION trg_owner_floor_fn() RETURNS trigger LANGUAGE plpgsql AS $BODY$
DECLARE
  owner_count integer;
BEGIN
  SELECT count(*) INTO owner_count
  FROM user_roles ur
  JOIN roles r ON r.id = ur.role_id
  JOIN users u ON u.id = ur.user_id
  WHERE r.name = 'owner'
    AND u.deleted_at IS NULL
    AND u.status = 'active'
    AND (ur.expires_at IS NULL OR ur.expires_at > now());
  IF owner_count = 0 THEN
    RAISE EXCEPTION 'owner floor violated: at least one active owner is required'
      USING ERRCODE = '23514';
  END IF;
  RETURN NULL;
END $BODY$;

CREATE CONSTRAINT TRIGGER trg_owner_floor_user_roles
  AFTER INSERT OR UPDATE OR DELETE ON user_roles
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION trg_owner_floor_fn();

CREATE CONSTRAINT TRIGGER trg_owner_floor_users
  AFTER UPDATE OR DELETE ON users
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION trg_owner_floor_fn();

-- Seed: system roles, RBAC permission vocabulary, role_permissions
-- (21-database-schema.md Sec.10.1, generated from 22-api-openapi.yaml x-rbac.permissions;
-- checked in as candleviewer/auth/rbac_seed.json, the single-source fixture E09-T03's
-- generator/drift-check will regenerate and verify).
INSERT INTO roles (id, name, description, is_system) VALUES
  (gen_random_uuid(), 'owner', 'Full control incl. live trading, keys, users, retention', true),
  (gen_random_uuid(), 'manager', 'Trades assigned accounts; no key/user administration', true),
  (gen_random_uuid(), 'viewer', 'Read-only across permitted accounts', true);

INSERT INTO permissions (id, code, domain, description, is_dangerous) VALUES
  (gen_random_uuid(), 'users:read', 'admin', '', false),
  (gen_random_uuid(), 'users:write', 'admin', '', true),
  (gen_random_uuid(), 'accounts:read', 'accounts', '', false),
  (gen_random_uuid(), 'accounts:write', 'accounts', '', true),
  (gen_random_uuid(), 'keys:read', 'accounts', '', false),
  (gen_random_uuid(), 'keys:manage', 'accounts', '', true),
  (gen_random_uuid(), 'instruments:read', 'instruments', '', false),
  (gen_random_uuid(), 'instruments:write', 'instruments', '', true),
  (gen_random_uuid(), 'marketdata:read', 'marketdata', '', false),
  (gen_random_uuid(), 'recording:read', 'recording', '', false),
  (gen_random_uuid(), 'recording:write', 'recording', '', true),
  (gen_random_uuid(), 'replay:read', 'replay', '', false),
  (gen_random_uuid(), 'replay:write', 'replay', '', false),
  (gen_random_uuid(), 'orders:read', 'trading', '', false),
  (gen_random_uuid(), 'orders:write', 'trading', '', true),
  (gen_random_uuid(), 'positions:read', 'trading', '', false),
  (gen_random_uuid(), 'positions:write', 'trading', '', true),
  (gen_random_uuid(), 'executions:read', 'trading', '', false),
  (gen_random_uuid(), 'killswitch:write', 'trading', '', true),
  (gen_random_uuid(), 'rules:read', 'rules', '', false),
  (gen_random_uuid(), 'rules:write', 'rules', '', true),
  (gen_random_uuid(), 'alerts:read', 'alerts', '', false),
  (gen_random_uuid(), 'alerts:write', 'alerts', '', false),
  (gen_random_uuid(), 'journal:read', 'journal', '', false),
  (gen_random_uuid(), 'journal:write', 'journal', '', false),
  (gen_random_uuid(), 'workspaces:read', 'workspaces', '', false),
  (gen_random_uuid(), 'workspaces:write', 'workspaces', '', false),
  (gen_random_uuid(), 'settings:read', 'settings', '', false),
  (gen_random_uuid(), 'settings:write', 'settings', '', false),
  (gen_random_uuid(), 'admin:read', 'admin', '', false),
  (gen_random_uuid(), 'audit:read', 'admin', '', false),
  (gen_random_uuid(), 'audit:export', 'admin', '', true),
  (gen_random_uuid(), 'flags:read', 'admin', '', false),
  (gen_random_uuid(), 'flags:write', 'admin', '', true),
  (gen_random_uuid(), 'backups:read', 'admin', '', false),
  (gen_random_uuid(), 'backups:write', 'admin', '', true);

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p WHERE r.name = 'owner';

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p WHERE r.name = 'manager' AND p.code IN ('marketdata:read', 'instruments:read', 'recording:read', 'replay:read', 'replay:write', 'orders:read', 'orders:write', 'positions:read', 'positions:write', 'executions:read', 'rules:read', 'rules:write', 'alerts:read', 'alerts:write', 'journal:read', 'journal:write', 'accounts:read', 'workspaces:read', 'workspaces:write', 'settings:read', 'settings:write');

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p WHERE r.name = 'viewer' AND p.code IN ('marketdata:read', 'instruments:read', 'recording:read', 'replay:read', 'replay:write', 'orders:read', 'positions:read', 'executions:read', 'rules:read', 'alerts:read', 'alerts:write', 'journal:read', 'accounts:read', 'workspaces:read', 'workspaces:write', 'settings:read', 'settings:write');
"""

_DOWNGRADE_SQL = """
DROP TRIGGER IF EXISTS trg_owner_floor_users ON users;
DROP TRIGGER IF EXISTS trg_owner_floor_user_roles ON user_roles;
DROP FUNCTION IF EXISTS trg_owner_floor_fn();

DROP TABLE IF EXISTS recovery_codes;
DROP TABLE IF EXISTS mfa_challenges;
DROP TABLE IF EXISTS mfa_methods;
DROP TABLE IF EXISTS sessions_rotation;
DROP TABLE IF EXISTS sessions;
DROP TABLE IF EXISTS user_account_access;
DROP TABLE IF EXISTS user_roles;
DROP TABLE IF EXISTS role_permissions;
DROP TABLE IF EXISTS permissions;
DROP TABLE IF EXISTS roles;
DROP TABLE IF EXISTS users;

DROP FUNCTION IF EXISTS set_updated_at();

DROP DOMAIN IF EXISTS sha256_hex;

DROP TYPE IF EXISTS mfa_method_kind;
DROP TYPE IF EXISTS role_name;
DROP TYPE IF EXISTS user_status;
"""
