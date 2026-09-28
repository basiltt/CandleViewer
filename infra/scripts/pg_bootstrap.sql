-- infra/scripts/pg_bootstrap.sql — E07-T02
--
-- Idempotent cluster/role bootstrap for the Postgres relational tier
-- (`docs/plan/21-database-schema.md` Sec.1.1). Creates the three roles the
-- rest of the schema assumes exist — `cv_owner` (DDL, runs migrations),
-- `cv_app` (DML only, no DDL — the runtime role every request handler
-- connects as), `cv_ro` (read-only, the only role the DuckDB `postgres`
-- attachment in Sec.5.5 may use) — plus the default-privilege grants that
-- make every *future* table automatically visible to `cv_app`/`cv_ro`
-- without a per-migration grant statement.
--
-- Run as a Postgres superuser (`psql -f infra/scripts/pg_bootstrap.sql`,
-- variables supplied via `-v owner_pw=... -v app_pw=... -v ro_pw=...` or
-- environment-substituted by the caller — never a value committed to this
-- file, C-12.2/SR-120..124). `\set` fallbacks below only cover local/dev
-- (`infra/compose/.env.example` CHANGE_ME placeholders); production values
-- are injected by the deploy pipeline's secret store, never this script.
--
-- Safe to re-run: every statement below is guarded so a second invocation
-- against an already-bootstrapped cluster is a no-op, not an error.

\set owner_pw `echo "${CV_PG_OWNER_PASSWORD:-CHANGE_ME}"`
\set app_pw `echo "${CV_PG_APP_PASSWORD:-CHANGE_ME}"`
\set ro_pw `echo "${CV_PG_RO_PASSWORD:-CHANGE_ME}"`

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_owner') THEN
    CREATE ROLE cv_owner LOGIN PASSWORD :'owner_pw';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN
    CREATE ROLE cv_app LOGIN PASSWORD :'app_pw';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_ro') THEN
    CREATE ROLE cv_ro LOGIN PASSWORD :'ro_pw';
  END IF;
END
$$;

SELECT 'CREATE DATABASE candleviewer OWNER cv_owner'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'candleviewer')
\gexec

\connect candleviewer

-- `cv_app` never receives CREATE/ALTER/DROP on this database (§9.1: "the app
-- role cv_app has no DDL privileges") — no GRANT of schema-level CREATE is
-- issued to it anywhere in this script, and it is asserted by
-- `services/api/tests/integration/*` (role privilege matrix, ticket AC 3).
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO cv_app, cv_ro;

ALTER DEFAULT PRIVILEGES FOR ROLE cv_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO cv_app;
ALTER DEFAULT PRIVILEGES FOR ROLE cv_owner IN SCHEMA public
  GRANT SELECT ON TABLES TO cv_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE cv_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO cv_app;

-- Audit tables get no UPDATE/DELETE grant for cv_app (C-5.7, applied once
-- `audit_log` exists — E09/E42's revision 0012 must re-run the equivalent
-- REVOKE for that specific table; nothing to revoke yet in this ticket's
-- scope since `audit_log` is out of scope here).
