---
description: Security rules - keys never logged, envelope-encryption module boundary, server-side RBAC, audit every order action, secrets scanning.
---
# Security

Source: `CONSTITUTION.md` C-2.7 to C-2.9, C-2.12, C-3.2, C-3.3, §12 (C-12.1 to C-12.13);
`docs/plan/04-security-program.md`; ADR-0009 (secrets), ADR-0010 (auth/RBAC); `SECURITY.md`.

## Keys and secrets (C-2.7, C-12.2)
- Exchange API keys are **envelope-encrypted at rest** (DEK per key, wrapped by KEK). Plaintext exists
  only in memory inside `services/api/secrets/`, for the duration of signing.
- Only the modules allowed by C-3.2 import `secrets`. Nothing else ever sees plaintext or the DEK.
- **Never log, print, return, serialise, snapshot or put into an exception message**: API keys/secrets,
  signatures, session tokens, passwords, KEK/DEK. Redaction filter is mandatory on every logger (C-12.6).
- API responses expose only key metadata (label, masked id, permissions, env).
- No secrets in code, tests, fixtures, `.env` committed, CI logs or screenshots. Use `.env.example`.
- Keys with withdrawal permission are rejected (C-2.8).

## AuthN / AuthZ (C-12.4, C-2.12)
- Roles: Owner, Manager (scoped to assigned accounts), plus those defined in C-12.4.
- **RBAC enforced server-side** on every route and WS subscription; the UI hiding a button is not security.
- Every endpoint test includes a forbidden-role case and a cross-account (IDOR) case.
- Risk caps, sizing, per-account profiles resolved server-side only (C-12.5).

## Audit (C-2.9, C-3.3, C-12.8)
- Every order action (submit, amend, cancel, fill, fan-out expansion, rule-engine action, risk override,
  admin change, key add/remove) writes an audit record: actor, role, account, action, before/after, traceId.
- Audit is append-only, hash-chained, retained indefinitely; no `UPDATE`/`DELETE` grants (C-5.7).

## Network and app hardening (C-12.9, C-12.10)
- Backend binds `127.0.0.1` / WSL-internal only; remote via Tailscale.
- Strict CSP (no `unsafe-eval` / `unsafe-inline`); Electron: `contextIsolation`, no `nodeIntegration`,
  sandboxed renderer, minimal typed preload.
- Validate every input with pydantic (`extra="forbid"`); parameterised SQL only (Semgrep raw-SQL rule).

## Scanning (CONSTITUTION §9 #10-#13)
- Before pushing: `gitleaks protect --staged --redact`. CI: Gitleaks, trufflehog, CodeQL, Semgrep, Bandit,
  pip-audit, npm audit, Trivy. Zero high/critical; exceptions must be approved and expiring (C-12.3).
- New dependency: licence allowlist (§9 #14), maintained, pinned; note it in the PR.

## Process
- Each epic has a STRIDE threat model (C-12.1); tickets touching auth, secrets, OMS, fan-out need
  the `security-reviewer` agent pass and a human CODEOWNER review.
- Vulnerabilities: follow `SECURITY.md`; never open a public issue (C-12.13).
