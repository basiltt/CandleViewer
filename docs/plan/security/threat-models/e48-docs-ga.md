# E48 — STRIDE threat model: documentation, diagnostics and GA-evidence surface

Version 1.0 · 2026-10-04 · Document owner: Security engineer · Approver: basiltt (Owner) — **owner approval pending**
Classification: **Restricted** (this model names weaknesses). Lives only in the private repo and private docs
site. It is **excluded** from the support bundle (the collector MUST carry an explicit exclusion rule for
`docs/plan/security/**`) and from the shareable subset of the GA evidence pack.
Method: `docs/plan/04-security-program.md` (STRIDE per epic); L/I scale per `32-risk-register.md` §1.1.

## 1. Scope and assets

| ID | Asset / flow | Owning ticket |
|----|--------------|---------------|
| A1 | Published docs site (build pipeline, hosting, network binding, generated API/WS examples) | E48-T02 |
| A2 | Runbook set `docs/runbooks/**` and its CODEOWNERS/review path | E48-T03 |
| A3 | Support-bundle pipeline (collect, redact, scan, cap, write, audit) | E48-S01 |
| A4 | `GET /system/build` and the in-app help content bundle | E48-S01 / E48-S02 |
| A5 | DR playbook, backup artefacts, drill scratch environments | E48-T04 |
| A6 | GA evidence pack and attestation files | E48-T06 |
| A7 | Release notes / changelog publication path | E48-T07 |

Out of scope: OMS, keys, RBAC internals (E09, ADR-0009/0010 — referenced, not redone); verification of
controls (E48-X02); the external pen-test (E43).

## 2. Data-flow and trust boundaries

Actors: owner, manager, viewer, on-call engineer, CI, attacker-with-network-access, attacker-with-a-manager-account
(insider). Boundaries from `20-architecture.md` §2.2: (TB1) browser/Electron to backend over loopback/Tailscale;
(TB2) backend to local filesystem (bundles, backups); (TB3) repo/CI to publish target (docs host, release page);
(TB4) operator to production during an incident (runbook execution).

Flows: F1 contributor, PR, CODEOWNERS review, docs build, private host. F2 permitted user requests a support
bundle, async job, bundle file, download. F3 operator reads a runbook and runs a privileged command. F4 CI builds
the evidence pack as an attested archive. F5 backup, verify, restore into a scratch environment.

**Asymmetry (recorded):** documentation controls are *review-time*, not runtime. A tampered runbook is caught by
CODEOWNERS review or not at all, so the review rule is structural (two-key on `docs/runbooks/**`, enforced by
branch protection), never cultural. The insider-with-manager-role case is considered throughout, because the
support bundle and docs site are reachable by more roles than the admin surfaces.

## 3. Control index

| Control | Description | Implemented in |
|---------|-------------|----------------|
| C-DOC-1 | Docs site binds to loopback/Tailscale only; no public listener; CI bind/probe test fails on a non-private listener | E48-T02 |
| C-DOC-2 | Docs build pinned and offline; generated examples and `docs/runbooks/**` pass the secret scan; bounded build timeout | E48-T02 (accuracy aspect: E48-T01) |
| C-DOC-3 | Docs-publish and evidence workflows use job-level least-privilege `permissions` (contents: read), no long-lived tokens | E48-T02, E48-T06 |
| C-RB-1 | Two approvals plus CODEOWNERS on `docs/runbooks/**`; verified commits; alert on merge with fewer than 2 approvals | E48-T03 |
| C-RB-2 | Runbooks use least-privilege procedures; lint rejects privileged-shortcut patterns; incident-log entry required | E48-T03 |
| C-SB-1 | Redaction is **allow-list (deny-by-default)**; unknown fields are dropped | E48-S01 |
| C-SB-2 | Pre-write secret scan **fails closed**; a scanner error aborts generation, never emits an unscanned bundle | E48-S01 |
| C-SB-3 | Size and rate cap, single concurrent job, off the request path, bounded disk quota | E48-S01 |
| C-SB-4 | Server-side RBAC; bundle bound to the authenticated actor and scoped to their accounts; `support_bundle.generated` audit event | E48-S01 |
| C-SB-5 | Collector exclusion of `docs/plan/security/**`, key material, `.env`, audit-chain keys | E48-S01 |
| C-SB-6 | Bundle carries a sha256 manifest, short TTL, deleted after expiry | E48-S01 |
| C-BLD-1 | `/system/build` returns only version, short commit and build time; no licence holder, host or path data | E48-S01 |
| C-DR-1 | Backups verified against a sha256 manifest before restore; abort on mismatch | E48-T04 |
| C-DR-2 | Scratch environments use synthetic/redacted data, isolation check before start, torn down and verified empty; short-lived restore credentials | E48-T04 |
| C-DR-3 | `dr.drill_executed` audit event with actor, scope, result | E48-T04 |
| C-EV-1 | Evidence pack built in CI from commit-pinned inputs; sha256 manifest attested (PEP 740 style) | E48-T06 |
| C-EV-2 | Shareable subset excludes restricted content; `ga.evidence_pack_built` audit event | E48-T06 |
| C-CL-1 | Changelog Security entries state impact and fixed version only, never exploit steps; security-reviewed | E48-T07 |
| C-CL-2 | Release notes change only via the reviewed-PR path; no direct edit of the published page | E48-T07 |

## 4. Per-element STRIDE enumeration

NA = not applicable, with reason. Every cell is explicit; none omitted. Rating is L x I (1-5 each).

### A1 Docs site (E48-T02)
| Cat | Threat | L/I | Control |
|-----|--------|-----|---------|
| S | Forged "official" docs from a look-alike or tampered host | 2/3 | C-DOC-1, C-DOC-3 |
| T | Injected content or script in the docs build (markdown, dependency) | 2/4 | C-DOC-2 |
| R | NA — read-only static content; edits attributed by git history and PR review | — | — |
| I | Secret in a generated API/WS example; site bound to a public interface | 3/5 | C-DOC-2, C-DOC-1 |
| D | Docs build blocking or exhausting CI | 2/2 | C-DOC-2 |
| E | Over-scoped `GITHUB_TOKEN` in the publish workflow | 2/4 | C-DOC-3 |

A publicly reachable site is an **unacceptable risk**, not a trade-off; C-DOC-1 is verified by an automated probe
that fails the build.

### A2 Runbooks (E48-T03)
| Cat | Threat | L/I | Control |
|-----|--------|-----|---------|
| S | Change attributed to a trusted author via spoofed commit identity | 2/3 | C-RB-1 |
| T | Tampered step (disable SL check, widen permissions) executed during an incident | 2/5 | C-RB-1 |
| R | Unattributable runbook execution during an incident | 3/3 | C-RB-2 (incident-log entry) plus C-2.9 audit of admin actions |
| I | Runbook embeds hostnames, credentials or key locations | 2/4 | C-DOC-2 |
| D | NA — a document cannot deny service itself; a wrong step is covered under T | — | — |
| E | Runbook normalises a privileged shortcut (bypass kill switch/SL, shared root credentials) | 2/5 | C-RB-2 |

### A3 Support bundle (E48-S01) — modelled as an exfiltration primitive
| Cat | Threat | L/I | Control |
|-----|--------|-----|---------|
| S | Bundle attributed to the wrong actor (replayed request, session reuse) | 2/3 | C-SB-4 |
| T | Bundle modified after generation or forged | 2/3 | C-SB-6 |
| R | Untracked bundle generation | 3/3 | C-SB-4 |
| I | Unredacted key/token/account id/order payload in a bundle; this model included | 3/5 | C-SB-1, C-SB-2, C-SB-5 |
| D | Unbounded generation exhausting disk or CPU | 3/3 | C-SB-3 |
| E | Manager-role insider obtains data beyond their account scope | 3/4 | C-SB-4 |

Stated rules: redaction is allow-list (deny-by-default), not blacklist; the pre-write scan fails closed; a
scanner error aborts generation rather than emitting an unscanned bundle.

### A4 `/system/build` and help bundle (E48-S01, S02)
| Cat | Threat | L/I | Control |
|-----|--------|-----|---------|
| S | NA — public metadata, no identity asserted | — | — |
| T | Help content altered to mislead operators (wrong shortcut for a destructive action) | 2/3 | C-DOC-2 (built from reviewed source) |
| R | NA — read-only; covered by standard request logging | — | — |
| I | Deployment fingerprinting via version/licence data | 3/2 | C-BLD-1 |
| D | Endpoint hammered | 2/1 | C-12.7 rate limiting; static response |
| E | NA — exposes no privileged action | — | — |

### A5 DR playbook, backups, scratch environments (E48-T04)
| Cat | Threat | L/I | Control |
|-----|--------|-----|---------|
| S | Restore performed with another operator's credentials | 2/4 | C-DR-2, C-DR-3 |
| T | Modified backup artefact restored without verification | 2/5 | C-DR-1 |
| R | Untracked drill execution | 3/3 | C-DR-3 |
| I | Restored real data left in a scratch environment | 3/4 | C-DR-2 |
| D | Drill touching production resources and causing an outage | 2/4 | C-DR-2 |
| E | Long-lived restore credentials | 2/4 | C-DR-2 |

### A6 GA evidence pack (E48-T06)
| Cat | Threat | L/I | Control |
|-----|--------|-----|---------|
| S | Forged attestation in the pack | 2/5 | C-EV-1 |
| T | Scan result or accepted-risk list edited after the fact | 2/5 | C-EV-1 |
| R | Pack built or altered without a record | 2/3 | C-EV-2 |
| I | Aggregated security posture leaked through the shareable subset | 2/4 | C-EV-2, §6 |
| D | NA — static archive, no runtime service | — | — |
| E | Build job with write access beyond the artefact store | 2/4 | C-DOC-3 |

### A7 Changelog / release notes (E48-T07)
| Cat | Threat | L/I | Control |
|-----|--------|-----|---------|
| S | NA — authorship by git history | — | — |
| T | Notes edited after publication to hide a fix | 2/2 | C-CL-2 |
| R | NA — PR review trail | — | — |
| I | Exploit detail in a Security entry | 2/4 | C-CL-1 |
| D | NA — static text | — | — |
| E | NA — confers no privilege | — | — |

## 5. Mapping check and accepted risks

Every threat above names an implementing control owned by an E48 ticket. Residual risks, accepted with owner and
expiry (filed in `32-risk-register.md` §9 as RSK-053..RSK-055):

| Risk | Residual | Owner | Expiry |
|------|----------|-------|--------|
| RSK-053 | Review-time-only runbook integrity: a compromised owner account plus a second colluding approver bypasses C-RB-1 (single-owner project: second approver is an agent review) | Security engineer | 2027-03-25 (GA) |
| RSK-054 | Allow-list redaction may drop diagnostically useful fields, slowing support | Owner/PO | 2027-06-30 |
| RSK-055 | Manager-role insider can see aggregate (non-secret) diagnostics for assigned accounts | Security engineer | 2027-03-25 (GA) |

## 6. Data classification

| Artefact | Class |
|----------|-------|
| Docs site | Internal/Confidential |
| Runbooks | Internal/Confidential |
| Support bundle | Restricted |
| GA evidence pack | Restricted (shareable subset: Internal-shared) |
| Changelog / release notes | Internal-shared |
| Drill records | Restricted |
| This threat model | Restricted |

## 7. Required telemetry

Audit events `support_bundle.generated`, `dr.drill_executed`, `ga.evidence_pack_built`; alert
`support_bundle.secret_detected`; alert on any merge touching `docs/runbooks/**` with fewer than two approvals
(detection control for A2 tampering).

## 8. Abuse cases handed to E48-X02

Each: actor, entry point, attempted action, expected refusal.

| ID | Actor | Entry point | Attempted action | Expected refusal |
|----|-------|-------------|------------------|------------------|
| AB-1 | Manager | support-bundle API | Request a bundle after seeding a fake API key and a session token into logs | Allow-list redaction drops both; the scan finds none; if the scanner is forced to error, no bundle file is produced and `support_bundle.secret_detected`/failure is audited |
| AB-2 | Manager | support-bundle API | Request a bundle covering an account not assigned to them | 403; no file written |
| AB-3 | Viewer | support-bundle API | Request any bundle | 403 server-side regardless of UI |
| AB-4 | Manager | support-bundle API | Fire 50 concurrent generation requests | At most one job runs; others get 429; disk stays under quota |
| AB-5 | Any permitted role | support-bundle output | Inspect bundle for `docs/plan/security/**`, `.env`, key material | Absent (collector exclusion rule) |
| AB-6 | Contributor | PR to `docs/runbooks/**` | Merge a runbook step disabling the native SL check with one approval | Branch protection blocks merge; if bypassed, the alert fires |
| AB-7 | Contributor | docs source | Add a generated example containing a key-shaped string | Docs build secret scan fails the job |
| AB-8 | Network attacker | docs host | Connect to the docs site from a non-Tailscale, non-loopback address | Connection refused; CI bind probe fails if a public listener is configured |
| AB-9 | Attacker | docs-publish workflow | Use the workflow token to push to a branch | Token is read-only; push refused |
| AB-10 | Operator | DR restore | Restore a backup whose sha256 does not match the manifest | Restore aborts before any write |
| AB-11 | Operator | DR drill | Complete a drill and inspect the scratch environment | Verified empty/torn down; only synthetic data was present |
| AB-12 | Attacker | `GET /system/build` | Read licence holder, host paths or build machine details | Only version, short commit, build time returned |
| AB-13 | Contributor | evidence pack | Alter a scan result then rebuild the pack | Digest mismatch against attested manifest; verification fails |
| AB-14 | Contributor | changelog PR | Add a Security entry containing exploit steps | Security reviewer rejects; lint on the Security section flags code blocks |
