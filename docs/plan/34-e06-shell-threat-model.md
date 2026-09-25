# 34 — E06 shell/engine boundary: STRIDE model and hardening checklist

Date: 2026-09-25 · Owner: Security engineer (spike) · Status: **draft — pending Architect + chart-engine lead review and minute**
Ticket: `E06-X01` · Companions: `04-security-program.md` §5 (method), §6.11 (SR-110…SR-119), `27-adrs/ADR-0011-electron-vs-tauri.md`,
`26-chart-engine-design.md`, `32-risk-register.md`.

Scope: the E06 desktop-shell-vs-engine spike only. This is **not** a new area of `04-security-program.md` §5 —
it is a pre-decision model that (a) rehearses Area 9 (Electron shell) and its Tauri counterpart against the
harness built for E06-T01, and (b) turns ADR-0011 criterion 5 into a pass/fail checklist. Where a threat is
already governed by an existing `SR-nnn` requirement, this doc cites it rather than restating it (C-16.5).

---

## 1. Assets

| Asset | Why it matters here |
|---|---|
| Desktop shell privilege boundary | Renderer/WebView runs untrusted-adjacent content (chart data, fonts, shaders); a breach reaches the OS if the boundary is soft. |
| KEK held in the OS keychain (`ADR-0009`) | The chosen shell must bridge to it without ever holding key material in the renderer. |
| Auto-update channel | Unsigned or unverified updates are a code-execution vector on the trading host. |
| Rendering pipeline inputs (WS frames, shaders, fonts) | The SDF text atlas is generated at runtime from a font file — an executable-adjacent input (`26-…` §3.7). |
| Diagnostics payload (SCR-046 "copy diagnostics") | Leaves the app via clipboard/paste; must never carry account/user context. |

## 2. Trust boundaries

| ID | Boundary | Electron form | Tauri form |
|---|---|---|---|
| TB-E1 | Renderer <-> preload <-> main process | `contextBridge` API surface | WebView <-> Rust host, `invoke()` command surface |
| TB-E2 | Web page <-> shared worker (chart render worker) | `OffscreenCanvas` worker, same-origin | same |
| TB-E3 | App <-> OS keychain | native keychain binding via main process | native keychain binding via Rust host |
| TB-E4 | App <-> update server | HTTPS, pinned host, signature check | HTTPS, pinned host, signature check |

These map onto the existing `04-security-program.md` §4.1 boundary register; TB-E1/TB-E3/TB-E4 are the
Electron-side instances of boundaries already named there (Area 9, A-16/AC-09).

## 3. STRIDE threats

Each row states likelihood (L) / impact (I) using the register's 1–5 scale, existing control, required
control, owner, and whether E06 can close it or must hand it to E10/E11.

### 3.1 Spoofing (S)

| T | Threat | L | I | Existing control | Required control | Owner | Disposition |
|---|---|---|---|---|---|---|---|
| S1 | A malicious page impersonates the app's deep-link handler to trigger an in-app action | 2 | 4 | None yet (deep links not implemented) | Deep-link handler validates scheme + target against an allow-list; accepts **navigation intents only**, never actions, without in-app confirmation (mirrors SR-117) | E10 | Constraint on E10 |
| S2 | A spoofed update server (DNS/host compromise) serves a build signed with a different, attacker-controlled key | 1 | 5 | None yet (auto-update not implemented) | Update feed host is pinned; signature verified against the app's embedded public key, not a key fetched at runtime (SR-115) | E10 | Constraint on E10 |

### 3.2 Tampering (T)

| T | Threat | L | I | Existing control | Required control | Owner | Disposition |
|---|---|---|---|---|---|---|---|
| T1 | Supply-chain tampering of engine/bench dependencies (compromised npm package in `packages/chart-engine` or its bench tooling) | 2 | 4 | SR-130…SR-139 (supply chain: lockfiles, audit, allowlisted licences) | Same controls apply unchanged to E06's harness deps; no exception for spike code | E06 (harness) / E03 (programme) | E06 applies existing SR-13x |
| T2 | Font or shader asset swapped for a malicious one (the SDF atlas is generated at runtime from the font, so a tampered font is an executable-adjacent input) | 1 | 4 | None recorded yet | Fonts and shader sources are **vendored and pinned** (checked into the repo or a pinned lockfile hash), never fetched at runtime; CI checksum-verifies them | E11 | Constraint on E11 |
| T3 | Unsigned or unverified update installs a malicious build | 1 | 5 | SR-115 (signed releases, signature-verified feed, no downgrade) | Applies verbatim; auto-update stays **off** in the harness and in production until signing exists | E10 | Constraint on E10 (already governed by SR-115) |
| T4 | Remote/untrusted content loaded into a trusted window (Electron) or an unexpected origin loaded into the WebView (Tauri) | 1 | 4 | SR-113 (`will-navigate`/`setWindowOpenHandler` deny non-local origins) | Same requirement stated for the Tauri candidate: WebView navigation restricted to the app's local origin, external links open in the OS browser | E10 | Constraint on E10 |

### 3.3 Repudiation (R)

**Not material at this layer, because:** the shell boundary itself does not perform actions requiring
non-repudiation (orders, key changes, admin actions) — those are backend-enforced and already covered by
the append-only audit log (C-2.9, `04-security-program.md` §8). The one shell-level action worth recording
for traceability, not repudiation, is **update application** and **update signature failure**, which are
required observability events (see §7 below) so that a hardening or rollback decision has an evidentiary
trail. No dedicated control beyond that observability requirement is needed here.

### 3.4 Information disclosure (I)

| T | Threat | L | I | Existing control | Required control | Owner | Disposition |
|---|---|---|---|---|---|---|---|
| I1 | The SCR-046 "copy diagnostics" payload leaks account/user context or an order-correlation id via clipboard | 2 | 4 | None recorded yet (E06-D02 spec in progress) | Field allow-list only: FPS, frame-time p50/p95, draw calls, GPU memory, buffer uploads/s, WS message rate, dropped frames, build/version string. **No user id, no account id, no symbol-linked order correlation id.** A violation is a security defect, not a product decision (see §5 abuse cases) | E06-D02 spec / E11 impl | E06 defines the allow-list; E11 implements it |
| I2 | The DOM mirror (values reproduced into the DOM for accessibility per `26-…` §12, `role="application"`) re-exposes chart data at the DOM inspection surface | 2 | 3 | None recorded yet | The mirror inherits the chart's data classification (same as the canvas content it mirrors); it is not an "unclassified invisible surface" — E11 must treat DOM-mirrored text with the same sensitivity as the rendered pixels | E11 | Constraint on E11 |
| I3 | GPU memory residue (freed chart buffers not zeroed) readable by another process on a shared/compromised host | 3 | 2 | RSK-（none dedicated) | Accepted residual, consistent with `32-risk-register.md`'s existing "K9 memory exposure under host compromise" Medium-accepted risk; no new control required beyond that acceptance | Backend/host owner | Already accepted at Medium in the risk register |
| I4 | `nodeIntegration`/an over-broad preload leaks environment or filesystem info to a compromised renderer | 2 | 4 | SR-110, SR-111 | Applies verbatim (contextIsolation, no generic `invoke`) | E10 | Constraint on E10 (already governed) |

### 3.5 Denial of service (D)

| T | Threat | L | I | Existing control | Required control | Owner | Disposition |
|---|---|---|---|---|---|---|---|
| D1 | A GPU context-loss loop (driver reset, VM/RDP context switch) repeatedly crashes and restarts the render pipeline | 3 | 3 | None recorded (engine context-loss handling is an E11 milestone item) | Bounded restart with backoff; a context-loss counter surfaces on the diagnostics overlay so it is a visible, not silent, failure mode | E11 | Constraint on E11 |
| D2 | Unbounded ring-buffer growth (WS message backlog, DOM ladder history) exhausts memory | 2 | 4 | C-2.18 (bounded queues, backend); engine equivalent not yet specified | Chart-engine ring buffers and WS ingestion queues on the renderer side are bounded with an explicit overflow policy, mirroring C-2.18's backend rule | E11 | Constraint on E11 |
| D3 | A rogue or misbehaving WS producer sends an upload storm, saturating GPU buffer upload bandwidth and blowing the frame budget | 2 | 3 | `06-performance-and-load-standard.md` frame budget gate (bench, not runtime) | Runtime-side rate limiting/coalescing on buffer uploads (batch, don't upload per message) — already implied by `26-…` §3.8 LUT/streaming design; call out explicitly as a DoS control, not just a perf one | E11 | Constraint on E11 |

### 3.6 Elevation of privilege (E)

| T | Threat | L | I | Existing control | Required control | Owner | Disposition |
|---|---|---|---|---|---|---|---|
| E1 | `nodeIntegration`/permissive preload grants a compromised renderer OS-level access (Electron) | 2 | 5 | SR-110, SR-111 (`04-security-program.md` §6.11, already Critical/High rated in §5.9 E1/E2) | Applies verbatim; harness shells built for E06-T01 must have these flags on **before** measurement (see §4) | E06 (harness), E10 (production) | Already governed; E06 applies it to the harness now |
| E2 | Tauri's WebView equivalent: an over-broad `invoke()` command surface grants a compromised WebView Rust-host access | 2 | 5 | None recorded (Tauri not yet in the security programme) | Tauri equivalent of SR-111: a fixed, typed, allowlisted command surface; no generic passthrough command; argument validation both sides | E06-T03 (decision), E10 (if Tauri chosen) | New requirement, parallel to SR-111 — recorded here for symmetry regardless of which shell wins |
| E3 | WebView2's OS-updated component changes rendering/security behaviour underneath the app without a release cycle (Tauri/Windows) | 3 | 3 | None — this is inherent to WebView2 | **Documented as a named, accepted characteristic**, not closed by a control: benefit — security patches arrive without us shipping; risk — behaviour changes under the application without our sign-off. Must be stated in ADR-0011's criterion-5 evaluation, not hidden | E06-T03 | Recorded as an accepted characteristic with an owner (Architect) to monitor WebView2 release notes |
| E4 | Electron's counterpart: we own the Chromium update treadmill; a missed update ships a known-vulnerable renderer | 2 | 4 | None recorded yet if Electron is chosen | Named owner (E10/Architect) and a cadence (track Electron LTS releases; patch within the security programme's SLA) recorded as a **required control if Electron wins** | E10 | Constraint on E10, conditional on ADR-0011 outcome |

### 3.7 STRIDE coverage check

All six categories are addressed: S (§3.1), T (§3.2), R (§3.3, explicitly "not material, because…"), I (§3.4),
D (§3.5), E (§3.6). No category is silently omitted — satisfies the ticket's first acceptance criterion.

---

## 4. Shell hardening checklist (ADR-0011 criterion 5, made checkable)

Criterion 5 requires "a documented, working equivalent of every shell responsibility: OS-keychain bridge for
the KEK, auto-update with signature verification, deep links, multi-window workspace persistence, and
Playwright-drivable E2E." Each responsibility below maps to one or more pass/fail items a reviewer can mark
by observation, for **both** candidate shells.

| # | Responsibility (ADR-0011 crit. 5) | Checklist item | Pass/fail evidence |
|---|---|---|---|
| 1 | Baseline hardening | `contextIsolation: true`, `nodeIntegration: false`, `nodeIntegrationInWorker: false`, `sandbox: true`, `webSecurity: true` (Electron) / equivalent WebView isolation flags (Tauri) | Inspect `BrowserWindow`/`WebviewWindow` construction args; SR-114-style build assertion output |
| 2 | Baseline hardening | Strict CSP in force, no `unsafe-eval`, enforced via header + `<meta>` fallback | Inspect response headers / meta tag in the packaged build; CSP report-only run with zero violations on the reference workload |
| 3 | Baseline hardening | Allow-list preload/`invoke` surface only — no generic channel passthrough | Manual review of preload/command registration code; grep for dynamic channel/command names |
| 4 | Baseline hardening | Navigation and `window.open`/external-navigation blocked by default; external links open in OS browser | Attempt in-app navigation to an external origin during the harness run; must be refused |
| 5 | Baseline hardening | Remote module / equivalent disabled | Inspect config; absence confirmed |
| 6 | OS-keychain bridge for the KEK | App can store and retrieve a test secret via the OS keychain through the shell's bridge, on the target OS | Store/retrieve round-trip test passes; failure mode when the keychain is locked/unavailable is a **defined, non-silent error** (not a fallback to plaintext) |
| 7 | Auto-update with signature verification | Update artefact signature is verified before install; a tampered artefact is rejected; downgrade is refused | Feed a harness build with a mismatched signature; install must be refused with a logged event |
| 8 | Auto-update with signature verification | Rollback path is documented and exercised at least once in the harness (even if disabled in production until signing is operational, per SR-115) | Rollback drill log |
| 9 | Deep links | Handler validates scheme and target against an allow-list; unexpected schemes/targets are refused, not silently ignored | Attempt an out-of-allow-list deep link during the harness run; must be refused and logged |
| 10 | Multi-window workspace persistence | Workspace layout persists across restarts without writing secrets (KEK, session token) to disk in plaintext | Inspect the persisted workspace file/store contents after a session; grep for secret material |
| 11 | Playwright-drivable E2E | The harness shell can be launched, driven, and asserted against by Playwright (Electron driver or Tauri's WebDriver equivalent) without manual steps | A Playwright smoke script opens the harness, reads the diagnostics overlay, and closes it cleanly in CI |

Any item that **cannot** be marked pass for a candidate is recorded against that candidate's ADR-0011
evaluation, not silently dropped — this is what makes criterion 5 "checkable by a reviewer... without further
interpretation" (ticket's second acceptance criterion).

---

## 5. Harness shells hardened before measurement

E06-T01's Electron and Tauri harness shells (used to produce the M0 performance numbers, `06-performance-and-load-standard.md`
§7.1–§7.4) **must** be built with items 1–5 of §4 enabled before any benchmark run counts as evidence. Concretely:
- `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`, and a strict CSP (no `unsafe-eval`) are on
  for every harness build, verified per item 1–2 above.
- Any hardening item that could not be enabled in the harness (e.g. a Tauri capability not yet available, or
  a flag that conflicts with a benchmarking hook) is recorded **with its expected performance implication**,
  so the M0 report's validity is known rather than assumed. Sandboxing and context isolation add IPC overhead;
  a **hardened-vs-unhardened delta** is captured as its own benchmark row (not just a pass/fail gate), per the
  ticket's technical notes — this is useful evidence for ADR-0011 in its own right, independent of the raw
  frame-time numbers.
- No network egress during a harness run is checked as part of this same pass (shared with E06-Q01); the
  shell's network posture is part of the trust boundary being measured, not a separate concern.

---

## 6. Abuse cases

### 6.1 Diagnostics payload (SCR-046 "copy diagnostics", E06-D02)

| Abuse attempt | Expected defence |
|---|---|
| Include the logged-in user's id in the payload | Rejected by the field allow-list (§3.4 I1); the spec enumerates exactly: FPS, frame-time p50/p95, draw calls, GPU memory, buffer uploads/s, WS message rate, dropped frames, build/version string |
| Include an account id or account label | Rejected by the same allow-list; no account-scoped field exists in the schema |
| Include a symbol-linked order-correlation id | Rejected by the same allow-list; the overlay has no access to order-domain data by construction (it reads engine/render counters only, not OMS state) |
| Round-trip the payload through the DOM mirror and read it via accessibility tooling instead of the copy button | Same allow-list applies regardless of exit path — the constraint is on the data available to the overlay, not on the button |

A violation of the allow-list is defined as a **security defect**, filed and triaged as such, not treated as
a product/UX decision to relax later (ticket's third acceptance criterion).

### 6.2 Engine input surface

| Abuse attempt | Expected defence |
|---|---|
| A WS frame declares an array length/offset larger than the actual buffer, attempting an out-of-bounds read on decode | Rejected per SR-128: the engine validates all array lengths and offsets before use; never allocates buffer sizes directly from an untrusted length field |
| A crafted font file is substituted for the vendored SDF-source font to smuggle malformed glyph data into the runtime atlas generator | Rejected by §3.2 T2: fonts are vendored and pinned (checksum-verified), never fetched, so substitution requires a repo/CI compromise already covered by supply-chain controls (SR-13x), not a runtime trust decision |
| A shader source is swapped to exfiltrate GPU memory contents via a crafted read | Same as above — shaders are vendored/pinned, not fetched at runtime |

---

## 7. Handoff — unresolved constraints owned by E10 / E11

| Constraint | From | Owner | Notes |
|---|---|---|---|
| Deep-link allow-list validation (S1) | §3.1 | E10 | Production implementation; harness only stubs it |
| Update-feed pinning + signature verification (S2, T3) | §3.1, §3.2 | E10 | SR-115 already covers Electron; Tauri needs the equivalent stated in its own ADR-0011 evaluation |
| Vendored/pinned font and shader assets, CI checksum verification (T2) | §3.2 | E11 | Treat as executable-adjacent, not design-only |
| Non-local-origin navigation blocking, both shells (T4) | §3.2 | E10 | SR-113 for Electron; Tauri equivalent required |
| DOM mirror inherits chart data classification (I2) | §3.4 | E11 | Do not treat as an unclassified invisible surface |
| Bounded ring buffers + overflow policy on the renderer side (D2) | §3.5 | E11 | Mirrors backend C-2.18 |
| Upload coalescing/rate limiting as an explicit DoS control (D3) | §3.5 | E11 | Not just a perf optimisation |
| Context-loss bounded restart + visible counter (D1) | §3.5 | E11 | Surface on SCR-046 |
| Tauri `invoke()` allow-list surface, symmetric to SR-111 (E2) | §3.6 | E06-T03 / E10 | New requirement if Tauri is chosen |
| WebView2 OS-update characteristic recorded as accepted, monitored (E3) | §3.6 | Architect | Not closable; monitor only |
| Chromium update ownership + cadence, if Electron wins (E4) | §3.6 | E10 | Named owner + SLA required |
| Required observability events: update applied, update signature failure, deep link refused | §3.3 | E10 | Defined now so E10 implements them from day one, not retrofitted |

None of these constraints remain owned by the closed E06-X01 spike (ticket's fifth acceptance criterion).

---

## 8. Risk register update

`32-risk-register.md` is **not** modified by this PR — this PR touches only this new document. That is a
deliberate, not an incidental, omission: this model does not surface a new Critical/High residual risk
beyond what §5.9/§5.11 of `04-security-program.md` already records for Electron (all Low after mitigation,
two accepted Medium items), so no register edit is warranted yet. The Tauri-side equivalents (E2, E3, E4
above) are new but are recorded here as constraints on E06-T03/E10 rather than as standalone register
entries, since they are conditional on which shell ADR-0011 selects. **If Tauri is chosen, a follow-up PR
must add a dedicated `32-risk-register.md` entry before E06-T03 closes** (flagged for the E06-T03 owner;
tracked so this doesn't get silently dropped).

---

## 9. Sign-off

- [ ] Reviewed in a working session with the Architect and the chart-engine lead; findings minuted (link when scheduled).
- [ ] Security engineer sign-off comment posted on GitHub issue #120.
- [ ] Checklist (§4) handed to E06-T01 before the harness benchmark matrix runs.

