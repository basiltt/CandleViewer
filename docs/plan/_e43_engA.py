# -*- coding: utf-8 -*-
"""E43 engineering tickets part A: T01-T06 pre-test hardening."""
import json, io, os

T = []
def t(**k):
    k.setdefault("phase", "P4 Backtesting & Scripting")
    k.setdefault("milestone", "R4 Live enablement")
    T.append({kk: k[kk] for kk in ["key","kind","title","labels","component","phase","sprint",
        "priority","perspective","risk","estimate","parent","blocked_by","milestone","body"]})

DOD = """## Definition of Done
- [ ] Acceptance criteria verified by an automated test or a recorded procedure.
- [ ] Coverage threshold met for touched packages (>= 85% backend/engine, >= 80% frontend; M2/M18/M19 >= 90%).
- [ ] `docs/plan/04-security-program.md` SR traceability and `docs/plan/03-testing-strategy.md` SR-150 table updated.
- [ ] SAST/SCA/secrets scans clean or triaged with a section 16.2 exception carrying an expiry.
- [ ] Security engineer review comment posted (mandatory for `area/auth-rbac`).
- [ ] QA sign-off comment with pass/fail per scenario.
- [ ] Demo or before/after evidence recorded (or "non-demoable infra-adjacent" with Architect concurrence).
- [ ] PR(s) merged via the merge queue with 2 approvals incl. a code-owner; required checks green.
"""

t(key="E43-T01", kind="Task",
  title="Tighten and CI-enforce the Content Security Policy across web and Electron",
  labels=["type/chore","area/auth-rbac","priority/p0","security","perf"],
  component="web", sprint="Sprint 20", priority="P0 Critical", perspective="Security",
  risk="None", estimate=3, parent="E43", blocked_by=["E43-X01","E43-X05"],
  body="""## Context
SR-112 (`docs/plan/04-security-program.md` section 6.11) specifies the exact CSP that packaged builds must enforce, via response headers **and** a `<meta>` fallback:

```
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
connect-src 'self' https://<tailnet-host> wss://<tailnet-host>;
img-src 'self' data: blob:; worker-src 'self' blob:;
object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'
```

with **no `unsafe-eval`** - explicitly, "the WebGL engine and rule editors MUST NOT require it". By R4 the app has accumulated a WebGL chart engine with an OffscreenCanvas worker (blob worker URLs), a node-graph rule editor, a design system that may want inline styles, and an Electron shell. Every one of those is a plausible source of a loosened directive that nobody re-tightened. SR-119 adds a hard constraint: **no Bybit host may appear in any CSP directive or in renderer-bundled code**, because all exchange traffic must originate from the backend so that credentials, the per-UID rate tracker and the environment capability record have exactly one chokepoint.

This ticket brings the actual policy back to the specified policy, proves it, and makes drift a build failure (SR-114).

## Scope / Deliverables
- Audit the CSP actually emitted by: the FastAPI gateway response headers (`services/api/candleviewer/api/`), the Vite-built `apps/web` HTML `<meta>` fallback, and the Electron packaged build (`apps/desktop/src/main/`). Record the current policy per surface, diff it against SR-112, and close every gap.
- Remove any `unsafe-eval`/`unsafe-inline` on `script-src`. If the rule node-graph editor or any dependency requires dynamic evaluation, it is changed or replaced - **not** exempted (SR-127 forbids `new Function`/`eval` on untrusted strings; `cv-eval-in-rule-engine` Semgrep rule forbids dynamic execution in the rule-engine package).
- Convert `style-src 'unsafe-inline'` to a nonce-based policy if the design system permits; if inline styles are genuinely required, record the justification inline in code and in the ticket, keeping `'unsafe-inline'` scoped to `style-src` only.
- Parameterise `connect-src` on the configured tailnet host from settings (M1) - never a wildcard, never origin reflection.
- Add `report-uri`/`report-to` wired to a backend collector endpoint that logs violations as structured events (no PII, no URLs containing tokens), so violations are observable rather than silent.
- **New CI check `csp-assertion`**: a test that parses the emitted headers and the packaged `<meta>` in a production build and fails on any deviation from the SR-112 directive set, on any `unsafe-eval`, and on the appearance of any Bybit host (`api.bybit.com`, `api-demo.bybit.com`, `api.bytick.com`, regional domains, `stream*.bybit.com`) anywhere in the policy or in renderer-bundled code (SR-119). Registered as a required status check on `main`.
- Update `docs/plan/04-security-program.md` section 12.3 required-check list with `csp-assertion`.

## Out of scope
- Electron `BrowserWindow`/preload/navigation hardening - **E43-T02**.
- The ZAP scan that will re-verify the policy externally - **E43-T08**.
- Any change to what the backend itself connects to.

## Acceptance criteria
```gherkin
Scenario: Production build matches the specified policy exactly
  Given a production build of the web app and the packaged Electron app
  When the csp-assertion check parses the emitted CSP from response headers and the meta fallback
  Then every directive matches SR-112 and no additional source expression is present

Scenario: No dynamic evaluation anywhere
  Given the production bundle
  When the app is exercised through chart rendering, the footprint view, the DOM ladder, the form rule editor and the node-graph rule editor
  Then no CSP violation of script-src is reported and no code path requires unsafe-eval

Scenario: Bybit hosts cannot reach the renderer
  Given a developer adds api.bybit.com to connect-src or imports a Bybit SDK into renderer code
  When CI runs
  Then the csp-assertion check fails and the merge is blocked

Scenario: Violations are observable
  Given a CSP violation occurs at runtime
  Then a structured violation event is logged with the directive and the blocked resource type
  And the event contains no session token, no URL query string and no user-identifying payload
```

## Technical notes / design
- Emit the header from a single middleware so there is exactly one source of truth; the `<meta>` fallback is generated from the same constant at build time to prevent divergence.
- `worker-src 'self' blob:` is required by the chart engine's OffscreenCanvas worker (`packages/chart-engine/src/worker/`); keep `blob:` scoped to `worker-src` and `img-src`, never `script-src`.
- Nonce approach for styles (if adopted): the gateway generates a per-response nonce, injected into the HTML shell; the Electron packaged build cannot use per-response nonces for a `file://`-style origin, so it uses hashes or retains scoped `'unsafe-inline'` with a recorded justification.
- Violation collector endpoint: `POST /api/v1/csp-report` accepting the standard report body, rate-limited per session, storing nothing beyond the directive, the blocked-URI scheme/host and a counter. Error codes follow the gateway's standard envelope.
- Config keys: `security.csp.tailnet_host`, `security.csp.report_enabled`, `security.csp.style_nonce_enabled`.

## Test plan
- **Unit**: policy-construction function produces the exact directive string for each environment; nonce generation is CSPRNG and per-response.
- **Contract**: `csp-assertion` parses and compares header + meta in a production build; includes a negative fixture with `unsafe-eval` and one with a Bybit host, both of which must fail the check.
- **Integration**: the gateway returns the header on the HTML shell and on error pages.
- **E2E (Playwright, web + Electron)**: navigate every major route, exercise chart/footprint/DOM/rule editors, assert zero `securitypolicyviolation` events; assert `frame-ancestors 'none'` by attempting to frame the app.
- **Perf**: chart-engine benchmark re-run to prove no frame-time regression from nonce injection or worker source changes.
- Coverage target: >= 85% on the policy module.

## Security notes
Threats (`04-security-program.md` section 5.7, 5.9): stored/reflected/DOM XSS escalating to session theft or order submission; clickjacking of the order ticket; exfiltration of data to an attacker-controlled host via a loose `connect-src`; renderer-side credential handling (SR-119). Controls: the exact SR-112 policy, `object-src 'none'`, `frame-ancestors 'none'`, `base-uri 'none'`, `form-action 'none'`, plus a build-time assertion so the control cannot silently rot. Data classification: session tokens and order-submission capability are at stake. Security review label required.

## Accessibility notes
A nonce-based `style-src` must not break the design system's focus-visible or high-contrast styling - E43-Q05's axe-core audit runs against the tightened build to confirm no a11y-relevant style is dropped.

## Performance notes
Budget from `docs/plan/06-performance-and-load-standard.md`: no measurable change to chart-engine frame time; header emission adds << 1 ms per response. Record before/after benchmark numbers on the ticket.

## Observability
Metric `cv_csp_violations_total{directive,blocked_type}`; a rate above a configured threshold raises a warning alert (a sudden spike is a likely XSS attempt or a broken deploy). Structured log event `security.csp_violation`.

""" + DOD + """
## Dependencies
- **E43-X01** STRIDE refresh - identifies which directives matter most for the current surface.
- **E43-X05** SAST/DAST rule pack - supplies the Semgrep rules (`cv-electron-unsafe-webprefs`, `cv-eval-in-rule-engine`) that back this control in code review.

## Branch
`feat/e43-security-csp`. PR size guidance: split into (1) policy constant + middleware + report endpoint, (2) removal of eval/inline dependencies, (3) CI assertion - each <= 400 LOC.

## References
- `docs/plan/04-security-program.md` SR-112, SR-114, SR-116, SR-119, SR-127, sections 12.1, 12.3.
- `docs/plan/20-architecture.md` section 2.1 (C1, C2, C3), section 2.2 boundary B4.
- `docs/plan/26-chart-engine-design.md` (worker/OffscreenCanvas usage).
- ADR-0011 Electron vs Tauri; ADR-0013 CI pipeline.""")

t(key="E43-T02", kind="Task",
  title="Electron shell hardening and fuse audit with a build-time assertion gate",
  labels=["type/chore","area/auth-rbac","priority/p0","security"],
  component="infra", sprint="Sprint 20", priority="P0 Critical", perspective="Security",
  risk="R8 Browser/GPU compat", estimate=5, parent="E43", blocked_by=["E43-X01"],
  body="""## Context
The Electron shell is the most privileged client surface in the product: it holds the OS-keychain bridge for the KEK and it is the process a renderer-side compromise would try to escape into. `docs/plan/04-security-program.md` section 6.11 lists ten requirements (SR-110..SR-119) and section 5.9 models the shell as threat area 9. By R4 the shell has been carrying features since R0 (GPU flags, window/workspace persistence, deep links, updater scaffolding) and each addition is an opportunity for a hardening flag to have been relaxed "temporarily".

This ticket audits the shell against every SR in section 6.11 and makes each one a build-time assertion, so that the R4 pen-test finds a shell that is already at spec (SR-114: *"A build-time assertion test MUST fail the release if any hardening flag, CSP directive or debugging setting deviates from this section in a production build"*).

## Scope / Deliverables
- **Window/WebContents audit (SR-110)**: assert on every `BrowserWindow`/`WebContents` creation path: `contextIsolation: true`, `nodeIntegration: false`, `nodeIntegrationInWorker: false`, `nodeIntegrationInSubFrames: false`, `sandbox: true`, `webSecurity: true`, `allowRunningInsecureContent: false`, `experimentalFeatures: false`, `enableRemoteModule` absent.
- **Electron fuses**: enable and verify the packaged-build fuses - `runAsNode` off, `enableNodeOptionsEnvironmentVariable` off, `enableNodeCliInspectArguments` off, `enableEmbeddedAsarIntegrityValidation` on, `onlyLoadAppFromAsar` on, `loadBrowserProcessSpecificV8Snapshot` as appropriate. Fuse state is read back from the packaged binary in the assertion test.
- **Preload bridge audit (SR-111)**: the preload exposes a fixed, typed, allowlisted API via `contextBridge`; remove any generic `invoke(channel, ...)` or `ipcRenderer` passthrough; both sides validate arguments against a schema; unknown channels are dropped **and logged**. Enumerate the final channel list in `docs/plan/20-architecture.md` section 2.1 C3.
- **Navigation constraint (SR-113)**: `will-navigate` and `setWindowOpenHandler` deny anything outside the app origin; external URLs go through `shell.openExternal` only after a scheme+host allowlist check.
- **Custom protocol handler (SR-117)**: accepts navigation intents only, strictly parsed; **must not** trigger any trading action without in-app confirmation.
- **Production debugging surface (SR-116)**: DevTools disabled, remote debugging port disabled, developer menu removed, source maps not shipped.
- **Integrity (SR-118)**: startup verifies ASAR integrity / code signature and aborts launch with a clear message on mismatch.
- **Updater (SR-115)**: confirm auto-update remains **disabled** until signing is operational; if enabled, it must verify signatures, refuse downgrades and fetch over HTTPS from a pinned host. Record the decision.
- **Keychain bridge (SR-119)**: assert the main process passes only an **opaque handle** to the backend and never key material to the renderer, and holds/proxies no API credentials.
- **CI check `electron-hardening`** (already a required check per section 12.3) extended to cover every item above, running against the *packaged* artefact, not the source.

## Out of scope
- CSP content itself (E43-T01 owns the directive set; this ticket only asserts it is present in the packaged build).
- Tauri evaluation - settled in ADR-0011.
- Code-signing certificate procurement (DevSecOps/E44-adjacent operational task); this ticket records whether signing is operational and gates the updater on it.

## Acceptance criteria
```gherkin
Scenario: Packaged build is at spec
  Given a production packaged Electron artefact
  When the electron-hardening check inspects webPreferences, fuses, the preload surface, navigation handlers and debugging settings
  Then every SR-110 to SR-119 item matches the specification and the check passes

Scenario: A relaxed flag fails the build
  Given a developer sets sandbox false on any BrowserWindow
  When CI builds the packaged artefact
  Then the electron-hardening check fails and names the offending window and flag

Scenario: Unknown IPC channel is dropped and logged
  Given renderer code invokes an IPC channel that is not on the allowlist
  Then the main process drops the message, returns an error to the caller and writes a structured log event
  And no handler is executed

Scenario: Navigation cannot escape the app origin
  Given a link or script attempts to navigate the window to an external origin or to open a new window
  Then navigation is denied and, if the scheme and host are on the external allowlist, the URL opens in the OS browser instead

Scenario: Tampered artefact refuses to launch
  Given the ASAR archive is modified after packaging
  When the application starts
  Then launch aborts with a clear integrity message and the failure is logged
```

## Technical notes / design
- Implement the assertion as a Node test that (a) statically parses `apps/desktop/src/main/**` for window-creation options, (b) reads fuse bytes from the packaged binary via `@electron/fuses` inspection, (c) extracts the preload bundle and asserts the exported `contextBridge` surface is a literal allowlist, (d) inspects packaged resources for source maps and devtools extensions.
- IPC schema validation: shared typed schemas (zod or equivalent) in `apps/desktop/src/preload/`, imported by both the preload and the main handler so drift is a type error.
- Deep-link parser: reject any URL whose path is not in the navigation-intent allowlist; never map a deep link onto an OMS command (SR-117).
- Config keys: `desktop.updater.enabled` (default `false`), `desktop.devtools.enabled` (false in production builds, non-overridable by env in packaged builds).
- Error codes: `E_IPC_UNKNOWN_CHANNEL`, `E_IPC_SCHEMA`, `E_NAV_DENIED`, `E_INTEGRITY_MISMATCH`.

## Test plan
- **Unit**: IPC schema validators (valid, malformed, extra-field, wrong-type); navigation allowlist decisions; deep-link parser incl. hostile inputs (`javascript:`, `file:`, path traversal, encoded schemes).
- **CI/assertion**: `electron-hardening` against the packaged artefact, with negative fixtures for each flag.
- **E2E (Playwright + Electron)**: attempt `window.open`, attempt external navigation, attempt to reach `require`/`process` from the renderer, attempt an unknown IPC channel, attempt to open DevTools; all must fail closed.
- **Drill**: tamper with the ASAR and confirm the launch abort (SR-118).
- Coverage target: >= 85% on preload/main hardening modules.

## Security notes
Threats (`04-security-program.md` section 5.9): preload bridge abuse, navigation escape, protocol-handler abuse, ASAR/integrity tampering, update-channel abuse - all explicitly in the pen-test scope (section 13.2 item 8). Data classification: the KEK handle is the crown-jewel adjacency here (asset A-16); a renderer escape that reaches the keychain bridge is a total compromise. Controls: context isolation + sandbox + literal IPC allowlist + opaque handle only + integrity verification. Security review mandatory.

## Accessibility notes
N/A - no UI surface changes. (Disabling the developer menu must not remove OS-level accessibility affordances; verified during E43-Q05.)

## Performance notes
`sandbox: true` and disabled `experimentalFeatures` must not regress the chart-engine FPS budget in `docs/plan/06-performance-and-load-standard.md`; re-run the engine benchmark in the packaged shell and record before/after. GPU flags required for WebGL2 performance must be preserved - any flag removed for hardening reasons is re-benchmarked.

## Observability
Structured log events `desktop.ipc_denied {channel}`, `desktop.navigation_denied {target_scheme}`, `desktop.integrity_check {result}`; metric `cv_desktop_ipc_denied_total{channel}`. A nonzero denial rate in normal operation is itself a signal.

""" + DOD + """
## Dependencies
- **E43-X01** STRIDE refresh (shell threat area re-scored against the shipped feature set).
- Consumed by **E43-T07** (SBOM/signing) and **E43-X02** (pen-test scope item 8).

## Branch
`feat/e43-security-electron-fuses`. PR size guidance: (1) webPreferences + fuses, (2) preload allowlist + schemas, (3) navigation/protocol/integrity, (4) CI assertion.

## References
- `docs/plan/04-security-program.md` section 6.11 SR-110..SR-119, section 5.9, section 12.1, section 13.2 item 8, section 14.7.
- `docs/plan/20-architecture.md` section 2.1 container C3, section 2.2 boundary B4.
- ADR-0011 Electron vs Tauri; ADR-0009 secrets and key management.""")

t(key="E43-T03", kind="Task",
  title="Session fixation, cookie and CSRF review across REST and WebSocket",
  labels=["type/chore","area/auth-rbac","priority/p0","security"],
  component="auth", sprint="Sprint 20", priority="P0 Critical", perspective="Security",
  risk="None", estimate=5, parent="E43", blocked_by=["E43-X01","E09"],
  body="""## Context
Session handling and CSRF are pen-test scope items 1, 3 and 6 (`docs/plan/04-security-program.md` section 13.2). The requirements were written in E09 and implemented at R0; by R4 the app has added step-up authentication, environment switching, admin mutations and a WebSocket layer that authorises subscriptions - each of which is a place a session could be adopted, fixed or replayed.

The binding requirements are SR-012 (opaque 256-bit tokens, `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/`, host-only; server-side session records; **no JWT** for browser sessions), SR-013 (**rotation on login, TOTP completion, step-up, password change, role change**, old identifiers invalidated immediately), SR-019 (session listing and revocation by the user and the Owner), SR-024 (idle 8 h, absolute 7 days; "remember this device" must not bypass TOTP; trading capability requires authentication within 12 h), SR-041 (double-submit CSRF token bound to the session and rotated with it, `SameSite` being an additional rather than sole control), SR-042 (`Origin`/`Sec-Fetch-Site` validation on state-changing requests and on the **WS handshake**; CORS as an explicit allowlist with credentials, never `*`, never reflection) and SR-129 (no sensitive state in `localStorage`/`sessionStorage`/IndexedDB/service-worker cache).

Note the deliberate divergence to resolve: `docs/plan/20-architecture.md` section 3.10 records `SessionManager` as "absolute 12 h / idle 60 min" while SR-024 specifies idle 8 h / absolute 7 days with a 12 h freshness requirement for trading capability. This ticket must reconcile the two in favour of the security program and update the architecture doc, or record an ADR if the tighter architecture value is retained.

## Scope / Deliverables
- Audit and correct cookie attributes on every `Set-Cookie` path (login, TOTP completion, step-up, rotation, logout) against SR-012.
- Audit and correct **rotation** coverage against SR-013: prove a *new* opaque identifier is issued and the old one immediately invalidated at each of the five trigger points; back it with the `sessions_rotation` table (`docs/plan/21-database-schema.md`).
- Reconcile the session-lifetime discrepancy and implement one authoritative model; implement the 12 h freshness requirement for trading capability as an explicit check on the order path, returning a distinguishable error the UI can turn into a re-auth prompt.
- CSRF: double-submit cookie + `X-CSRF-Token` header on every state-changing HTTP method, token bound to the session and rotated with it; reject on absent/invalid/mismatched. Ensure no state-changing operation is reachable via `GET`.
- `Origin`/`Sec-Fetch-Site` validation on state-changing requests **and on the WS handshake**, against an explicit allowlist (localhost app port, tailnet hostname, Electron app origin). CORS explicit allowlist with `credentials: true`; a test asserts no wildcard and no reflection (backed by the `cv-cors-wildcard` Semgrep rule).
- Session listing and revocation (SR-019): user-visible active sessions and Owner-visible all-user sessions, each with created/last-seen/IP/user-agent; revoke-one and revoke-all; every revocation audited.
- Frontend storage audit (SR-129): assert no session token or secret is written to `localStorage`, `sessionStorage`, IndexedDB or a service-worker cache; a Playwright test enumerates storage after login and asserts only non-sensitive preference keys exist.
- Logout must invalidate server-side, not merely clear the cookie.

## Out of scope
- Password hashing, TOTP algorithm and enrolment (E09, re-verified not re-built).
- Rate limiting and lockout - **E43-T04**.
- RBAC route coverage - **E43-T09**.

## Acceptance criteria
```gherkin
Scenario: Session identifier rotates at every privilege transition
  Given an authenticated session
  When the user completes TOTP, completes step-up, changes their password, or has their role changed
  Then a new opaque session identifier is issued
  And the previous identifier is rejected on the very next request
  And a sessions_rotation row records the trigger

Scenario: A fixed session cannot be adopted
  Given an attacker sets a session cookie value of their choosing before the victim logs in
  When the victim authenticates
  Then the issued identifier differs from the attacker-supplied value
  And the attacker-supplied value is never accepted

Scenario: State change without a CSRF token is refused
  Given a valid session cookie
  When a state-changing request arrives without the X-CSRF-Token header, or with a token not bound to that session
  Then the request is rejected with 403 and an audit event is written
  And no state is mutated

Scenario: Cross-origin WebSocket handshake is refused
  Given a WS handshake carrying an Origin that is not on the allowlist
  Then the handshake is rejected before any subscription is authorised

Scenario: Stale session cannot trade
  Given a session last authenticated more than 12 hours ago
  When an order-placement request is made
  Then the request is refused with a distinguishable re-authentication error
  And read-only routes continue to work until the idle timeout

Scenario: No sensitive state in browser storage
  Given a fully authenticated session with an open chart and a saved layout
  When browser storage is enumerated
  Then no entry contains a session token, CSRF token, API secret or TOTP material
```

## Technical notes / design
- Sessions are server-side rows in `sessions` (`docs/plan/21-database-schema.md`) keyed by an opaque 256-bit CSPRNG token; the cookie carries the token only. Rotation writes to `sessions_rotation` with `{old_id, new_id, trigger, at}`.
- CSRF token: 256-bit CSPRNG, stored on the session row, mirrored into a non-`HttpOnly` cookie for the double-submit comparison; rotated with the session so a rotation invalidates a captured token.
- Order-path freshness check sits in the OMS request dependency chain (M14 boundary) but is implemented as an auth dependency in M18 so it is declared once.
- Error codes: `E_CSRF_MISSING`, `E_CSRF_MISMATCH`, `E_ORIGIN_DENIED`, `E_SESSION_EXPIRED`, `E_REAUTH_REQUIRED`, `E_STEPUP_REQUIRED`.
- Config keys: `auth.session.idle_seconds`, `auth.session.absolute_seconds`, `auth.session.trading_freshness_seconds`, `auth.origins.allowlist`.

## Test plan
- **Unit**: cookie-attribute builder; token generation entropy; rotation trigger table; CSRF comparison incl. timing-safe equality; origin allowlist matcher (exact host, port, scheme; no suffix matching).
- **Contract**: every state-changing OpenAPI operation declares CSRF requirement; a test enumerates operations and asserts no state-changing `GET`.
- **Integration**: fixation attempt; replay of a rotated identifier; CSRF absent/invalid/cross-session; wrong `Origin` on REST and on the WS handshake; expired idle and absolute sessions; the SR-152 negative set.
- **E2E (Playwright web + Electron)**: login -> TOTP -> step-up rotation chain observed from the client; revoke-all from another session terminates the first within one request; storage enumeration assertion.
- Coverage target: >= 90% on M18 session/CSRF modules.

## Security notes
Threats (`04-security-program.md` section 5.6): session fixation, session hijack, CSRF-driven order submission, step-up bypass, WS origin bypass. Asset classification: session tokens are secrets; a hijacked session equals order-submission capability. Controls as listed above, each mapped to an SR. Security review mandatory; the abuse cases in E43-X04 target this ticket's surface directly.

## Accessibility notes
The re-authentication prompt triggered by `E_REAUTH_REQUIRED` must be an accessible dialog (focus trap, labelled, focus restored) and must not silently discard the user's in-progress order ticket input - verified by E43-Q05.

## Performance notes
Session lookup and CSRF comparison are on every request: budget <= 2 ms p95 added latency (`docs/plan/06-performance-and-load-standard.md` API budgets). Session rows are indexed; the lookup must not become an N+1 against `user_account_access`.

## Observability
Metrics `cv_auth_session_rotations_total{trigger}`, `cv_auth_csrf_rejections_total{reason}`, `cv_auth_origin_rejections_total`, `cv_auth_reauth_required_total`. Audit events `auth.session.revoked`, `auth.stepup.granted|denied`, `security.csrf_rejected`. Alert on a CSRF/origin rejection spike.

""" + DOD + """
## Dependencies
- **E09** Auth, sessions, 2FA & RBAC - the implementation being audited and corrected.
- **E43-X01** STRIDE refresh - re-scores the session/CSRF threat area against the R4 surface.

## Branch
`feat/e43-security-session-csrf`. PR size guidance: (1) cookie + rotation, (2) CSRF + origin/CORS, (3) session listing/revocation + storage audit.

## References
- `docs/plan/04-security-program.md` SR-012, SR-013, SR-019, SR-024, SR-025, SR-041, SR-042, SR-129; sections 5.6, 13.2 items 1/2/6, 14.2.
- `docs/plan/20-architecture.md` section 3.10 `SessionManager`; `docs/plan/21-database-schema.md` `sessions`, `sessions_rotation`.
- `docs/plan/22-api-openapi.yaml`; `docs/plan/23-ws-protocol.md` (handshake).
- ADR-0010 auth and RBAC.""")

t(key="E43-T04", kind="Task",
  title="Auth rate-limit, lockout and enumeration-resistance review",
  labels=["type/chore","area/auth-rbac","priority/p0","security"],
  component="auth", sprint="Sprint 20", priority="P0 Critical", perspective="Security",
  risk="None", estimate=3, parent="E43", blocked_by=["E43-X01","E09"],
  body="""## Context
Pen-test scope item 1 (`docs/plan/04-security-program.md` section 13.2) is authentication: brute force, lockout bypass, TOTP bypass/replay, recovery-code abuse. The controls exist from E09 but have never been attacked as a set, and lockout is a double-edged control in a trading product: an attacker who can lock the Owner out of the terminal while a position is open has achieved a meaningful denial of service even without stealing anything.

Binding requirements: SR-014 (login responses indistinguishable between unknown user, wrong password and wrong TOTP **in body, status and timing**, with a dummy Argon2id verification for unknown users), SR-015 (per-account **and** per-source-address rate limiting with exponential backoff, e.g. 5 attempts/5 min then doubling), SR-016 (lock after 10 consecutive failures for 15 minutes, **Owner alerted**; Owner unlocks from the admin screen; the Owner's own unlock uses recovery codes), SR-021 (TOTP skew <= +/-1 step and **replay cache** rejecting a code already accepted), SR-022 (ten single-use 128-bit recovery codes, Argon2id-hashed, displayed once; use consumes, regeneration invalidates all prior; **each use audited and alerts the Owner**), SR-023 (documented break-glass path for total Owner lockout, audited and loudly surfaced afterwards).

`docs/plan/20-architecture.md` section 3.10 records `PasswordAuth` lockout as "after 5 failures / 15 min" against SR-016's 10 - reconcile explicitly.

## Scope / Deliverables
- Verify and correct the timing-equalisation of login responses: dummy Argon2id verification on unknown users; identical status, body and header set; measure and bound the timing delta.
- Implement/verify layered limiting: per-account, per-source-address, and a global floor, with exponential backoff; ensure the limiter cannot be bypassed by rotating the username, by casing/whitespace variants of the identifier, or by a spoofable header (client IP is taken from the trusted proxy configuration, never from `X-Forwarded-For` unconditionally).
- Reconcile the 5-vs-10 failure threshold and the lockout duration; implement one authoritative policy and update `docs/plan/20-architecture.md` section 3.10.
- Lockout must alert the Owner (SR-016) and must be visible on SCR-137 as a failed-login-spike finding (feeds E43-S02).
- TOTP: assert +/-1 step skew only and a working replay cache keyed by `(user, code, step)`; assert codes are not logged (SR-069).
- Recovery codes: single-use, Argon2id-hashed, displayed once, regeneration invalidates prior codes, every use audited **and** alerts the Owner.
- Break-glass CLI (SR-023): confirm it exists, is runnable only with filesystem access plus the KEK, writes an audit event, and causes a loud, persistent in-app notice afterwards. Rehearse it once and record the drill.
- **Denial-of-service consideration**: document and implement the mitigation that lockout of a trading-capable user does not disable risk-reducing paths - a locked-out user cannot place orders, but the Owner's kill-switch path and exchange-side stops remain unaffected (`04-security-program.md` section 6.15, RR-03).

## Out of scope
- Session/CSRF mechanics (E43-T03); RBAC coverage (E43-T09); API rate limiting for non-auth routes (SR-044 family, owned by E34's governor and re-tested in E43-Q04).

## Acceptance criteria
```gherkin
Scenario: Responses do not distinguish failure modes
  Given login attempts for an unknown user, a known user with a wrong password, and a known user with a wrong TOTP
  Then the status code, response body and headers are identical across all three
  And the median and p95 response times differ by less than the configured timing budget

Scenario: Brute force is throttled per account and per source
  Given repeated failed logins from one source address across many usernames
  Then the source is throttled with exponential backoff independently of any single account's counter

Scenario: Lockout triggers, alerts and expires
  Given the configured number of consecutive failures on one account
  Then the account is locked for the configured duration
  And the Owner is alerted
  And the lockout appears on the security posture summary
  And after the duration expires the account authenticates normally without manual action

Scenario: A TOTP code cannot be replayed
  Given a TOTP code that was already accepted for a user
  When the same code is presented again within its validity window
  Then authentication fails and the replay is logged

Scenario: A recovery code is single-use and noisy
  Given a valid unused recovery code
  When it is used
  Then it is consumed, the use is audited, the Owner is alerted, and the same code fails on a second attempt

Scenario: Lockout does not disable risk reduction
  Given a manager is locked out while holding an open position
  Then the position retains its native exchange-side stop-loss
  And the Owner can still act on that account through their own session
```

## Technical notes / design
- Limiter is a token bucket with persisted counters so a restart does not reset an attacker's budget; keys are `account:{user_id}` and `addr:{client_ip}` with separate parameters.
- Client IP resolution: trust only the configured proxy hop count; a test asserts a forged `X-Forwarded-For` does not reset the counter.
- Timing equalisation: a fixed minimum response duration plus dummy verification; measured in the test suite as a statistical assertion over >= 200 samples per branch, not a single comparison.
- TOTP replay cache: in-memory with a persisted fallback, entries expiring after the skew window; keyed by user + accepted step.
- Error codes: `E_AUTH_INVALID` (single generic code for all failure modes), `E_AUTH_LOCKED`, `E_AUTH_RATE_LIMITED`.
- Config keys: `auth.lockout.threshold`, `auth.lockout.duration_seconds`, `auth.ratelimit.account`, `auth.ratelimit.address`, `auth.timing.min_response_ms`.

## Test plan
- **Unit**: bucket arithmetic and backoff doubling; TOTP skew acceptance at -1/0/+1 and rejection at +/-2; replay-cache behaviour; recovery-code hashing and consumption; identifier normalisation for limiter keys.
- **Integration**: full brute-force sequence to lockout and recovery; per-address throttling across usernames; forged `X-Forwarded-For`; restart mid-attack preserving counters.
- **Statistical timing test**: assert the timing delta between failure branches is within budget.
- **E2E**: lockout UX and the Owner unlock path; recovery-code login; the Owner alert firing.
- **Drill**: break-glass CLI rehearsal on a scratch environment, recorded per SR-023.
- Coverage target: >= 90% on M18 auth modules.

## Security notes
Threats (`04-security-program.md` section 5.6): brute force, user enumeration, TOTP replay, recovery-code abuse, lockout-as-DoS. Data classification: credentials and TOTP material are secrets and must never be logged (SR-069). Controls as above. Note the explicit residual: RR-03 accepts that remote access can be lost while a position is open, mitigated by native stop-losses - the same reasoning bounds lockout DoS. Security review mandatory.

## Accessibility notes
Lockout and rate-limit states must be announced as text with the remaining time (CMP-035 Countdown/Timer text), not as a colour change; the generic failure message must not leak which field was wrong, while still being clear enough to be actionable.

## Performance notes
Limiter lookups add <= 1 ms p95 to the login path; the deliberate minimum-response-duration floor is a security budget, not a regression, and is documented as such in `docs/plan/06-performance-and-load-standard.md`.

## Observability
Metrics `cv_auth_failed_logins_total{reason_bucket}`, `cv_auth_lockouts_total`, `cv_auth_ratelimit_hits_total{scope}`, `cv_auth_recovery_code_used_total`. Audit events `auth.login.failed`, `auth.account.locked`, `auth.recovery_code.used`, `auth.breakglass.used`. Alerts: auth-failure spike, any recovery-code use, any break-glass use.

""" + DOD + """
## Dependencies
- **E09** Auth, sessions, 2FA & RBAC. **E43-X01** STRIDE refresh.
- Feeds **E43-S02** (failed-login-spike posture check) and **E43-Q04** (auth DoS load profile).

## Branch
`feat/e43-security-auth-ratelimit`. PR size guidance: (1) limiter + IP resolution, (2) lockout + alerting, (3) TOTP replay + recovery codes + break-glass drill.

## References
- `docs/plan/04-security-program.md` SR-014..SR-016, SR-020..SR-023, SR-028, SR-029; sections 5.6, 13.2 item 1, 14.2.
- `docs/plan/20-architecture.md` section 3.10.
- `docs/plan/21-database-schema.md` `users`, `sessions`.
- `docs/plan/11-user-stories.md` US-ONB-005, US-ONB-008.
- ADR-0010 auth and RBAC.""")

t(key="E43-T05", kind="Task",
  title="Dependency freeze, full SCA sweep and license-policy enforcement",
  labels=["type/chore","area/auth-rbac","priority/p0","security"],
  component="infra", sprint="Sprint 20", priority="P0 Critical", perspective="Security",
  risk="None", estimate=3, parent="E43", blocked_by=["E02"],
  body="""## Context
The pen-test is executed against a frozen build (code freeze **2027-07-02**, `docs/plan/30-release-roadmap.md` section 8.5). A freeze is only meaningful if the dependency graph underneath it is pinned and clean: a transitive bump between the test and the retest invalidates the test's conclusions, and a High-severity CVE discovered after the report is a finding nobody paid for.

Requirements: SR-130 (fully locked dependencies with hashes for Python, lockfiles committed, CI installs frozen with hash verification), SR-131 (container base images pinned **by digest**, rebuilt weekly, Trivy-scanned, multi-stage, non-root runtime, read-only root filesystem where feasible, dropped capabilities), SR-132 (GitHub Actions pinned to full commit SHAs, least-privilege `permissions`, `pull_request_target` prohibited without review), SR-134 (Dependabot/Renovate enabled for pip, npm, Docker and Actions; advisories affecting the order path or key handling triaged within 48 h), SR-135 (new runtime dependencies justified in the PR with code-owner approval), SR-136 (**license allowlist**: MIT, BSD-2/3, Apache-2.0, ISC, PSF, MPL-2.0, Unlicense/CC0 allowed; LGPL needs security+owner approval; GPL/AGPL/SSPL/BUSL/Commons Clause/non-commercial prohibited in shipped code), SR-138 (`postinstall` scripts reviewed; `--ignore-scripts` where the toolchain permits), SR-139 (vendored/forked third-party code recorded), SR-156 (scans clean of High/Critical at release; exceptions need a section 16.2 entry with expiry).

## Scope / Deliverables
- **Freeze**: produce and commit a frozen dependency set for backend (`uv.lock`/`requirements.txt` with hashes), frontend (`pnpm-lock.yaml`), container base images (digest-pinned) and GitHub Actions (SHA-pinned). Tag the freeze commit; the pen-test runs against this tag.
- **Full SCA sweep**: run `pip-audit` (cross-checked with `uv`/`safety`), `npm`/`pnpm audit --audit-level=high`, and Trivy against every built image and the filesystem. Triage every High/Critical: fix, replace, or record a section 16.2 exception with a compensating control and an expiry inside one release cycle. Produce a triage table on the ticket.
- **License scan**: run `pip-licenses` + `license-checker` against the frozen graph; enforce the SR-136 allowlist via a CI job with an allowlist file; resolve every violation before freeze. Record any LGPL usage with the required security+owner approval.
- **Actions hardening**: replace every floating action tag with a full commit SHA; set `permissions: contents: read` as the workflow default and grant narrowly per job; assert no `pull_request_target` exists without a recorded security review.
- **Container hardening verification**: base images by digest, non-root runtime user, read-only root filesystem where feasible, dropped Linux capabilities, weekly rebuild schedule in place.
- **postinstall review** (SR-138): enumerate JS dependencies with install scripts, justify each, and enable `--ignore-scripts` in CI where the toolchain permits, listing explicit exceptions.
- **Vendored code register** (SR-139): record any vendored or forked third-party code in `docs/plan/` with source, version, reason and update owner.
- **Freeze policy document**: what may change during the freeze window (security fixes only, with Security + Owner approval), who approves, and how the tester is informed of any change.

## Out of scope
- SBOM production and artefact signing - **E43-T07** (consumes this frozen graph).
- Secrets scanning of git history - **E43-T06**.
- Application-code SAST rules - **E43-X05**.

## Acceptance criteria
```gherkin
Scenario: The frozen graph installs reproducibly
  Given the freeze tag
  When CI installs backend and frontend dependencies with frozen lockfiles and hash verification
  Then installation succeeds and the resolved graph is byte-identical to the committed lockfiles

Scenario: No unresolved High or Critical vulnerability at freeze
  Given the SCA sweep across pip, npm and container images
  Then every High or Critical finding is fixed, or recorded as a section 16.2 exception with a compensating control, an owner approval and an expiry date
  And the exception table is reflected in docs/plan/04-security-program.md section 16.2

Scenario: A prohibited license blocks the build
  Given a dependency carrying a GPL, AGPL, SSPL, BUSL or non-commercial license is added to shipped code
  When the license-scan job runs
  Then the build fails and names the offending package and license

Scenario: Actions cannot float
  Given a workflow references an action by tag rather than a full commit SHA
  When CI runs
  Then the cv-unpinned-action Semgrep rule fails the build

Scenario: A change during the freeze is controlled
  Given a security fix must land during the freeze window
  Then it requires Security plus Owner approval, is recorded on this ticket, and the tester is notified of the new tag
```

## Technical notes / design
- Freeze tag naming: `pentest-freeze-<yyyymmdd>`; the retest tag is `pentest-retest-<yyyymmdd>`. Both hashes go into the evidence pack (E43-X07).
- The triage table records: package, version, advisory id, severity, path (direct/transitive), affected area (order path / key handling / other), decision, ticket, expiry.
- SR-134's 48-hour triage clock applies to advisories touching the order path or key handling; others get 7 days. Encode this in the Dependabot/Renovate configuration labels so the clock is visible.
- CI jobs added/confirmed as required checks: `pip-audit`, `npm-audit`, `license-scan`, `trivy` (already listed in `04-security-program.md` section 12.3).

## Test plan
- **CI**: frozen-install job; SCA jobs with a known-vulnerable fixture asserting the gate fails; license-scan with a prohibited-license fixture asserting failure; `cv-unpinned-action` rule with a floating-tag fixture.
- **Integration**: container starts as non-root with a read-only root filesystem and dropped capabilities; a test asserts the effective user id is not 0.
- **Manual**: triage table reviewed by the Security engineer; postinstall justification list reviewed.
- Coverage target: N/A (no application code); gate coverage is the artefact.

## Security notes
Threats: supply-chain compromise (`04-security-program.md` section 6.13), dependency-driven client vulnerabilities (pen-test scope item 7), and license risk to the shipped product. Data classification: no secrets touched, but CI must not gain access to production credentials (SR-140) - verify no new workflow requests privileged secrets. Security review mandatory.

## Accessibility notes
N/A - no UI surface.

## Performance notes
Verify the frozen graph does not regress startup time or bundle size beyond the budgets in `docs/plan/06-performance-and-load-standard.md`; record bundle size at the freeze tag as the R4 baseline.

## Observability
Metric `cv_scan_findings{tool,severity}` published from CI; `cv_dependency_exceptions_open` with the nearest expiry as a gauge, so an expiring exception becomes visible before it blocks a release.

""" + DOD + """
## Dependencies
- **E02** Monorepo scaffold & toolchain - supplies the CI pipeline and lockfile tooling this ticket hardens.
- Feeds **E43-T07** (SBOM from the frozen graph) and **E43-X02** (the tester receives the freeze tag).

## Branch
`chore/e43-security-dep-freeze`. PR size guidance: (1) lockfile freeze + frozen installs, (2) SCA triage + exceptions, (3) license scan + Actions pinning + container hardening.

## References
- `docs/plan/04-security-program.md` section 6.13 SR-130..SR-139, SR-156, section 12.1, section 12.3, section 16.2.
- `docs/plan/30-release-roadmap.md` section 8.5 (code freeze date).
- `docs/plan/20-architecture.md` section 5 (monorepo layout, tooling), section 8.3 (build, artefacts and release).
- ADR-0013 CI pipeline.""")

t(key="E43-T06", kind="Task",
  title="Full-history secrets scanning and credential-hygiene verification",
  labels=["type/chore","area/auth-rbac","priority/p0","security"],
  component="infra", sprint="Sprint 20", priority="P0 Critical", perspective="Security",
  risk="None", estimate=3, parent="E43", blocked_by=["E02"],
  body="""## Context
`gitleaks` runs on every PR and on a nightly full-history schedule (SR-142), but R4 requires a deliberate, recorded full-history sweep before the pen-test: a secret committed in R0 and deleted in R1 is still in the object store, and the tester is explicitly scoped to attempt reading secrets "through any API, log, export or error path" (`docs/plan/04-security-program.md` section 13.2 item 5). SR-143 is the rule that governs any hit: **rotate first, investigate second** - history rewriting is never treated as sufficient remediation (runbook IR-02).

Adjacent hygiene requirements verified here: SR-140 (CI must hold no production Bybit credentials - no live key, no funded demo key, no production KEK as a GitHub secret), SR-141 (CI secrets are environment-scoped with protection rules and required reviewers; prefer OIDC over long-lived tokens), SR-144 (developer environments use demo credentials only through the same envelope-encryption mechanism; `.env` files contain no exchange secrets and are gitignored; a committed `.env.example` documents non-secret settings only), SR-145 (test fixtures contain synthetic keys with an obvious dummy prefix, with a test asserting no fixture matches real key patterns), SR-146 (CI logs and artefacts are checked for secret leakage; workflows must not `set -x` around secret usage or dump the environment), and SR-006/SR-069 (redaction filter; audit entries never contain secrets).

## Scope / Deliverables
- **Full-history scan** with `gitleaks` across all refs and all objects (including dangling objects and stashes if reachable), plus a second-opinion scanner, with the complete rule set - not the PR diff rules. Record the run, the ruleset version and the result.
- **Triage and rotate**: for every hit, follow IR-02 - rotate the credential first, then determine exposure window and blast radius, then decide on history rewriting separately. Record each hit and its disposition (even "false positive" gets a recorded justification and a rule refinement).
- **CI secret inventory** (SR-140/SR-141): enumerate every repository and environment secret; assert none is a Bybit live key, a funded demo key or a production KEK; convert long-lived tokens to OIDC federation where the provider supports it; apply environment protection rules with required reviewers to release-bearing secrets.
- **Workflow log hygiene** (SR-146): audit all workflows for `set -x` around secret usage, environment dumps, and artefact uploads that could contain secrets; add a CI step that scans job logs and uploaded artefacts with the redaction rules.
- **Fixture assertion** (SR-145): implement/verify the test that asserts no committed fixture matches real Bybit key patterns and that all synthetic keys carry the agreed dummy prefix.
- **Developer-environment audit** (SR-144): confirm `.env` is gitignored, `.env.example` contains no secret values, and the documented developer path uses demo credentials through envelope encryption.
- **Redaction-filter verification** (SR-006/SR-069): a test that pushes known secret-shaped values through logging, error responses, audit payloads and the journal/audit export path, and asserts none survives - including in exception tracebacks and validation-error messages that echo input.
- **Pre-commit hook** parity: the same gitleaks rules run locally (SR-142).

## Out of scope
- Rotating keys as a routine operation (E27 owns rotation flows); this ticket rotates only what the sweep implicates.
- Dependency and license scanning - **E43-T05**.

## Acceptance criteria
```gherkin
Scenario: History is clean or accounted for
  Given a full-history gitleaks scan across every ref
  Then every hit has a recorded disposition
  And any hit representing a real credential has been rotated before any other remediation step

Scenario: CI holds no production credential
  Given the inventory of repository and environment secrets
  Then no secret is a Bybit live key, a funded demo key, or a production KEK
  And every release-bearing secret is environment-scoped with required reviewers

Scenario: A secret cannot escape through an error path
  Given a request whose payload contains a value shaped like an API secret
  When the request fails validation and when it raises an unhandled exception
  Then neither the error response, the structured log, the audit entry nor the exception traceback contains the value

Scenario: A real-looking key in a fixture fails CI
  Given a test fixture containing a string matching the real Bybit key pattern without the dummy prefix
  When CI runs
  Then the fixture assertion fails and names the file

Scenario: A committed secret blocks the merge
  Given a pull request introducing a credential-shaped string
  When gitleaks runs on the diff
  Then the build fails and the IR-02 runbook is referenced in the failure output
```

## Technical notes / design
- Full-history scan command must cover `--no-git` filesystem mode as well as git mode, to catch secrets in untracked-but-committed artefacts such as build outputs.
- The redaction filter (SR-006) is a single function applied at the logging adapter, the error-response serialiser and the audit writer - the test asserts all three paths, since a filter applied in only one place is the classic failure.
- Secret-shaped detection for the redaction test uses the same patterns as the gitleaks ruleset so the two controls agree.
- Dummy fixture prefix is a documented constant (e.g. `DUMMYKEY_`) asserted by both the fixture test and the gitleaks allowlist.

## Test plan
- **CI**: full-history scan job (scheduled + on-demand for this ticket); diff scan on PRs; log/artefact scan step with a deliberately leaky fixture job proving the step catches it.
- **Unit**: redaction filter against a corpus of secret shapes (API key, API secret, session token, TOTP seed, KEK handle, recovery code) embedded in nested payloads, list elements, exception args and f-string-interpolated messages.
- **Integration**: validation-error echo path; unhandled-exception path; audit write path; audit export path.
- **Manual**: secret inventory review by DevSecOps + Security engineer; workflow log audit.
- Coverage target: >= 90% on the redaction module.

## Security notes
Threats (`04-security-program.md` section 5.1, 5.9): key exfiltration via repository history, CI logs, error messages or exports - pen-test scope item 5. Data classification: this ticket handles the crown jewels (A-01/A-02 exchange credentials) by definition. Control precedence is fixed by SR-143: rotate, then investigate, then consider rewriting. Security review mandatory; any confirmed exposure triggers IR-02 and an incident note.

## Accessibility notes
N/A - no UI surface.

## Performance notes
The full-history scan is a scheduled job, not a PR-blocking one, so it has no PR latency budget; the diff scan must stay under the CI step budget agreed in `docs/plan/06-performance-and-load-standard.md` for pipeline duration.

## Observability
Metrics `cv_secrets_scan_findings_total{ruleset,disposition}`, `cv_ci_secret_inventory_violations`. Audit/incident events: any confirmed exposure creates an IR-02 incident note feeding `docs/plan/32-risk-register.md`.

""" + DOD + """
## Dependencies
- **E02** Monorepo scaffold & toolchain (CI, pre-commit infrastructure).
- Feeds **E43-X02**: the tester is told the history has been swept, so their credential-hunting time goes to live paths rather than to archaeology.

## Branch
`chore/e43-security-secrets-sweep`. PR size guidance: (1) scan configuration + full-history run, (2) redaction tests + fixes, (3) CI secret inventory + workflow log hygiene.

## References
- `docs/plan/04-security-program.md` SR-006, SR-069, SR-140..SR-146, SR-143 (IR-02), section 5.1, section 10.3 runbooks, section 12.1, section 13.2 item 5.
- `docs/plan/20-architecture.md` section 5 (monorepo layout), section 2.2 boundary B3.
- ADR-0009 secrets and key management.""")

json.dump(T, io.open(os.path.join(os.path.dirname(__file__), "_e43_part3.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("part3", len(T))
