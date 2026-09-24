# ADR-0010 — Authentication, RBAC, and admin inside the web app

- Status: **decided**
- Date: 2026-09-14
- Deciders: Security engineer, Architect, Owner, Frontend lead
- Consulted: `docs/research/22-architecture-options.md` §9, `docs/research/09-execution-risk-tools.md` §10, `docs/research/23-views-and-screens.md` views 15, 20, 21, `docs/research/24-owner-decisions.md` decision #6, planning brief "Locked decisions"
- Related: ADR-0009, `docs/plan/04-security-program.md`, `docs/plan/12-sitemap.md`

## Context and problem statement

CandleViewer serves one owner plus a few account managers and reviewers. Managers must be able to trade their assigned sub-accounts and must not be able to see anyone else's. The owner needs administration — users, roles, Bybit accounts, API keys, per-account profiles, feature flags, recorder policy, audit log, system health — and a kill-switch. The planning brief forbids a separate admin application: admin is RBAC-gated screens inside the same web app. Remote access is Tailscale-only. No retail product researched documents fine-grained RBAC for this use case, so the design is bespoke.

## Decision drivers

- Manager isolation is a money-and-trust boundary, not a UI preference.
- The frontend must never be trusted for scope, environment or risk caps (principle P8).
- One app, one deployment, one set of screens (planning brief).
- The backend contract must remain client-agnostic so a mobile client can be added later.
- The system is reachable only over a WireGuard mesh, but network isolation is not authentication.

## Considered options

1. **Server-side sessions (cookie) + mandatory TOTP + a central scope resolver; admin as RBAC-gated routes in the same SPA.**
2. **JWT access/refresh tokens in browser storage.**
3. **OIDC via an external identity provider** (Authentik/Keycloak).
4. **Tailscale identity as the sole authentication** (trust the mesh).

## Decision outcome

**Chosen: option 1.**

1. **Authentication** — password (Argon2id, per-user salt plus a pepper derived from the KEK) **and** mandatory TOTP (RFC 6238, 30 s step, ±1 window, single-use recovery codes). Lockout after 5 failures in 15 minutes, with an audit entry and an owner notification.
2. **Sessions** — opaque server-side sessions in Postgres; cookie is `HttpOnly`, `Secure`, `SameSite=Strict`, path-scoped. Absolute lifetime 12 h, idle timeout 60 min, rotation on any privilege change, revoke-all on password or TOTP change. No JWT in `localStorage` — an XSS bug must not yield a portable, unrevocable credential.
3. **CSRF** — `SameSite=Strict` plus a double-submit token on every state-changing request; the WS handshake validates `Origin`.
4. **Roles** — `Owner` (full administration, all accounts, global kill-switch), `Manager` (trade and view only their assigned accounts), `Viewer` (read-only over a granted scope, including the audit log and journal). Roles are coarse by design; the fine-grained dimension is the **account scope**.
5. **Central scope resolver** — a single `ScopeResolver` maps user → role → allowed account ids → allowed key ids. **Every** REST route and **every** WS subscription passes through it. There is exactly one implementation, so there is exactly one place isolation can be wrong, and it is covered by a contract test that asserts 403 for every cross-scope route and topic.
6. **Admin inside the app** — admin routes live under `/admin/*` in `apps/web`, gated by role at the router level *and* independently at every API endpoint. The client-side gate is a UX affordance only; the server gate is the security control.
7. **Environment as an authorisation dimension** — every trading request carries its environment and is rejected server-side on mismatch. Demo→Live switching requires typed confirmation, is never hotkey-driven, and is audited.
8. **Kill-switch** — Owner-only FREEZE per manager or globally, enforced in the OMS `Validator` before any adapter call, so it cannot be bypassed by a modified client or a stale session.
9. **Audit** — hash-chained, append-only (`INSERT`-only role; `UPDATE`/`DELETE` revoked): auth events, key events, order actions, rule firings, admin changes, environment switches, kill-switch activations. Owner and Viewer may read; nobody may mutate.
10. **Transport** — Tailscale is a network control, not an authentication control; it is defence in depth beneath the application session, never a substitute.

### Consequences

Positive:
- Sessions are revocable instantly and centrally — important when a manager relationship ends.
- One resolver means isolation is testable exhaustively rather than reviewed hopefully.
- One application to build, style, test and accessibility-audit, per the planning brief.
- Mandatory TOTP meaningfully raises the bar even if a password leaks.

Negative / risks:
- Server-side sessions require a database round-trip per request (mitigated by a short-lived in-process cache with explicit invalidation on revoke) and mean Postgres downtime blocks login — acceptable, since Postgres downtime already blocks order entry.
- Admin screens inside the trading app widen the SPA's blast radius if an XSS bug appears. Mitigated by a strict CSP, no `dangerouslySetInnerHTML` (lint-enforced), `HttpOnly` cookies, Electron context isolation, and a pen-test before Live enablement.
- Bespoke RBAC means no off-the-shelf audit of the model. Mitigated by the contract test suite and an explicit STRIDE threat model per epic.

### Why not the alternatives

- **JWT in browser storage**: not revocable without a server-side blocklist (at which point it is a session with extra steps), and directly XSS-exfiltratable.
- **External OIDC provider**: another stateful service to run, back up and secure on a single box for fewer than ten users; it also adds a hard dependency that can block login while positions are open.
- **Tailscale identity alone**: a single compromised or unlocked device would grant full trading authority with no second factor and no per-user scope inside the app. Rejected outright.

## Validation

- Contract tests: for every route and every WS topic, a Manager outside scope receives 403 and an audit entry, with no adapter call made.
- Session tests: absolute/idle expiry, rotation on privilege change, revoke-all on credential change, CSRF rejection, `Origin` validation on the WS handshake.
- DAST (OWASP ZAP) in CI against the authenticated surface; pen-test before Live enablement (R4).
