# -*- coding: utf-8 -*-
"""E48 part 3 — stories S01-S04."""
from _e48_gen import t

S01 = """## Context
`docs/plan/30-release-roadmap.md` §9.3 exit criterion 6 requires a **user guide** at GA, and §9.4's Docs gate requires it to have been *reviewed by someone who did not write it*. `docs/plan/10-personas.md` gives the guide its shape: it is not one document but a set, because P1 (Owner / discretionary order-flow trader) and P4 (Admin, owner hat) are the same human wearing two hats with very different tasks, while P2/P3/M1 are different people with narrower permissions (E48-S02).

P1 is the person who trades: chart, footprint, DOM, order ticket, brackets, algos, positions, replay, journal. P4 is the same person doing the janitorial work that keeps trading possible: users and roles, exchange accounts and API keys, per-account profiles, feature flags, backups, health, audit log, recorder and retention. Conflating them produces a guide where the trading content is buried in admin procedure; splitting them by *hat* produces two documents each of which is read in one sitting.

This guide is the primary artefact that discharges risk **R10 Key-person** in `docs/plan/32-risk-register.md`: today the system is only operable by the people who built it.

## Scope / Deliverables
Written into `docs/guide/` using the **Learn** template from E48-D01, with valid front-matter including a non-author reviewer.

**`docs/guide/owner/` (P1 — trading):**
- *Getting oriented*: the app shell and global chrome (SCR-010 chrome, workspace/layout model SCR-040-family), DEMO vs LIVE badging and what switching actually changes, panic buttons (CMP-211 PanicButtons), the kill switch.
- *Reading the market*: charting core (SCR-050-family), footprint, volume/delta/TPO profiles, Deep-Stats rows, DOM ladder & liquidity heatmap, big trades, CVD & delta panes, OI/funding/liquidations/basis, speed of tape / imbalance / regime — each section states what is **measured** and what is *(estimated)*, linking the SCR-058 methodology entries authored in E48-D02.
- *Trading*: order ticket and chart/DOM trading, brackets, scaled orders, emulated OCO/iceberg/TWAP/chase, positions & orders management, the native exchange-side SL invariant on every fanned-out order and why it exists.
- *Automation*: trade groups and fan-out, per-account profiles, risk caps / lockouts / kill-switch, alerts & notifications, rule engine from a *user's* standpoint (authoring is M1, covered in E48-S02).
- *Reviewing*: journal & analytics, replay & tick replay, recording and retention from the trader's side ("why is there no history before this date").
- *When it goes wrong*: what the disconnected/stale/degraded states mean (SCR-152, SCR-153, SCR-158, SCR-159), what the user should do, and which runbook the operator hat then picks up (link into `docs/runbooks/`).

**`docs/guide/admin/` (P4 — operating):**
- Users, roles and invitations; the RBAC model and the permission matrix reproduced from `docs/plan/10-personas.md` §7.
- Exchange accounts, sub-accounts and API keys: creating a key with withdrawal permission **OFF**, IP whitelisting to the deployment's egress IP (and the fact that Bybit applies the whitelist per key, so every master and sub-account key is whitelisted separately), the 48-hour sub-account key restriction, key rotation, and what the app does when the egress IP changes.
- Per-account profiles: leverage, sizing rule, SL/TP offsets, risk caps, allowed symbols.
- Feature flags (SCR-145), backups & restore (SCR-146), exchange connectivity & rate limits (SCR-147), system health, audit log and how to read/verify it.
- Recorder and retention administration: the recorded-symbol list, auto-record behaviour, the 30-day default, pin-to-keep, disk budget.
- The admin re-auth rule (`/admin/*` requires role owner **and** an admin re-auth token ≤15 min old) and why a 404 rather than a 403 is returned to non-owners by the router.
- A pointer, not a duplicate, to every operations runbook (E48-T03) and the DR playbook (E48-T04).

**Cross-cutting:** a one-page "first hour" quick-start for each hat; the GA version banner; screenshots produced under E48-D01's standard from the fixture dataset.

## Out of scope
- P2 Manager, P3 Viewer and M1 rule-author guides — E48-S02.
- Engineer-facing material (build, run, architecture) — E48-T05.
- Runbook *content* — E48-T03/T04; this guide links to them and must not restate steps, so there is exactly one place a procedure lives.
- API/WS reference — E48-T01.
- Android/mobile; any exchange other than Bybit USDT linear perpetuals.

## Acceptance criteria
```gherkin
Scenario: Both hats are covered end to end
  Given the delivered guide
  Then docs/guide/owner covers every P1 primary task listed in docs/plan/10-personas.md section 2
  And docs/guide/admin covers every P4 primary task listed in section 5
  And a coverage table in the guide index maps each persona task to the section that covers it

Scenario: Estimated values are never presented as measured
  Given every section describing a detector or heuristic-derived value
  Then the value is labelled (estimated) exactly as the product labels it
  And the section links to the corresponding SCR-058 methodology entry
  And the statement that Bybit provides no L3/MBO feed appears in the order-flow overview

Scenario: The key procedure cannot be followed into an unsafe state
  Given the API-key creation walkthrough in docs/guide/admin
  When a reader follows it
  Then withdrawal permission OFF and per-key IP whitelisting are mandatory numbered steps, not notes
  And the guide states that a key without both is rejected by the application

Scenario: Reviewed by a non-author
  Given each delivered document's front-matter
  Then reviewer is present, is not equal to author, and reviewed_on is a date within this epic's window

Scenario: A procedure appears exactly once
  Given the guide and the runbook set
  When any operational procedure is searched for
  Then it is fully written in exactly one document and referenced by anchor elsewhere

Scenario: Screenshots leak nothing
  Given every screenshot in the guide
  Then it was produced from the fixture dataset
  And no account id, balance, key fragment or tailnet address is visible
```

## Technical notes / design
Structure per E48-D01's Learn template. Each chapter opens with a "you can do this if…" permission callout generated from `docs/plan/10-personas.md` §7 — for the owner guide this is trivially "yes", but the callout is kept so S02 can reuse identical section skeletons with different callouts and the two guides stay structurally diffable.

Screenshots: produced from the named fixture dataset in a scripted capture pass so they can be regenerated when the UI changes; the capture script lives with the guide, and each image records the build tag it came from in its alt/caption slot. Runbooks contain no images at all (E48-D01 constraint) — the guide may.

Authoring order is deliberate: write the admin guide's key/profile chapters **after** E48-T02's reconciliation sweep confirms the shipped behaviour of those screens, so the guide does not document a superseded flow.

## Test plan
- **Task-coverage check** (automated-assisted): the persona task lists from `docs/plan/10-personas.md` §2 and §5 are encoded as a checklist file; a script asserts every task id appears in the guide's coverage table. Missing entries fail the check.
- **Walkthrough test**: the reviewer performs three end-to-end procedures against the demo environment using only the guide — (a) add a sub-account and a correctly-scoped key, (b) create a trade group and fan out one bracketed order, (c) read a footprint bar and explain the delta. Any step that requires asking a question is a defect.
- **Link check**: every internal anchor resolves (reuse E48-T01's checker).
- **Front-matter schema check** on every file (E48-D01 schema, wired by E48-T01's CI gate).
- No unit/contract/integration layers apply; this Story's automated surface is the coverage, link and schema checks.

## Security notes
- Threats (`docs/plan/04-security-program.md`): information disclosure via screenshots and worked examples; and *instructional* risk — a guide that teaches an unsafe key configuration is a security defect, not a documentation defect.
- Controls: the key chapter's mandatory steps mirror SR-033 (per-key IP whitelisting, egress-IP detection and alerting) and the withdrawal-OFF invariant from `docs/plan/00-planning-brief.md`; E48-X02 reviews the finished text and every image; the fixture dataset removes live data from the capture path entirely.
- The guide must not document internal endpoint layouts, KEK handling, or audit-chain internals beyond what an operator needs to *use* the admin screens.
- Data classification: internal-confidential. Not published anywhere internet-facing.
- `security` review label: required on this Story (it documents key handling and RBAC) — Security engineer sign-off before Done.

## Accessibility notes
- Heading hierarchy per E48-D01; single h1; no skipped levels.
- Every screenshot carries alt text describing what the reader must notice.
- The permission matrix is reproduced as a real table with header cells.
- Instructions never rely on colour alone ("the red chip" → "the red *Stale* chip labelled Stale").
- Plain-language pass per `docs/plan/05-accessibility-standard.md`.

## Performance notes
N/A at runtime. Authoring constraint: image payload per chapter ≤2 MB so the repo stays clone-friendly for the E48-T05 onboarding trial; screenshots are PNG-optimised.

## Observability
N/A — the guide adds no code. It documents the existing `help.*` analytics only insofar as SCR-119 links into it.

## Definition of Done
- [ ] `docs/guide/owner/` and `docs/guide/admin/` complete, using the E48-D01 Learn template.
- [ ] Coverage table maps every P1 and P4 persona task to a section; coverage check passes.
- [ ] Three walkthrough tests executed by a non-author with zero blocking questions.
- [ ] Every document's front-matter valid, reviewer ≠ author, dated.
- [ ] Link check and schema check green in CI (E48-T01's gate).
- [ ] Security engineer sign-off (key/RBAC content).
- [ ] a11y: heading/alt-text/table checks pass.
- [ ] QA sign-off via E48-Q01.
- [ ] Demoed: the walkthrough test recorded and shown at Sprint Review.
- [ ] Feature flag state: N/A — documentation is not flag-gated.

## Dependencies
- `blocked_by` E48-D01 (templates, IA, front-matter schema, screenshot standard) and E48-T02 (shipped-behaviour reconciliation, so the admin chapters document what exists).
- Cross-epic: E42 (admin screens SCR-143/145/146/147 and the audit log), E27 (accounts, sub-accounts, key vault) and E47 (accessibility statement referenced from the guide). These are all closed before S25.

## Branch
`feat/e48-docs-owner-admin-guide`. Split the PR by chapter group (orientation+market, trading+automation, admin) to keep each diff reviewable; three PRs of roughly equal size rather than one large one.

## References
- `docs/plan/10-personas.md` §2 (P1), §5 (P4), §7 permission matrix
- `docs/plan/30-release-roadmap.md` §9.3 exit criterion 6, §9.4 Docs gate
- `docs/plan/14-screens-catalogue.md` SCR-058, SCR-119, SCR-143, SCR-145, SCR-146, SCR-147, SCR-152, SCR-153, SCR-158, SCR-159
- `docs/plan/15-component-catalogue.md` CMP-211 PanicButtons
- `docs/plan/04-security-program.md` SR-033, §10.3
- `docs/plan/32-risk-register.md` R10 key-person
"""

t("E48-S01", "Story", "Write the Owner and Admin user guide (personas P1 and P4)",
  ["type/docs", "area/docs", "priority/p1", "security", "a11y", "qa"],
  "docs", "Sprint 25", "P1 High", "Product", "R10 Key-person", 5, "E48",
  ["E48-D01", "E48-T02", "E42", "E27"], S01)


S02 = """## Context
The user guide is persona-scoped because the permission matrix in `docs/plan/10-personas.md` §7 is real and enforced: a **P2 Account Manager** trades only the accounts assigned to them and cannot touch users, keys or flags; a **P3 Viewer / analyst** cannot place an order at all; **M1 Rule author** is a *mode* rather than a person — the Owner or a Manager wearing it — and is the only audience for the rule engine's two editors (form editor and node-graph editor).

Handing all three the owner guide would be worse than giving them nothing: it would teach procedures that RBAC forbids them, producing support questions and, worse, the belief that the system is broken when a control is absent. E48-S01 establishes the section skeleton and the permission-callout pattern; this Story reuses it with narrowed content and correct callouts.

## Scope / Deliverables
Written into `docs/guide/` with the **Learn** template (E48-D01), front-matter with a non-author reviewer.

**`docs/guide/manager/` (P2):**
- What a Manager can and cannot do, reproduced from the §7 matrix, stated positively first and then as an explicit "not available to you, and why" list so absent controls are explained rather than mysterious.
- The accounts assigned to you: how assignment works, per-account profiles as *constraints you operate inside* (leverage, sizing rule, SL/TP offsets, risk caps, allowed symbols) and what happens when you hit one.
- Trading: order ticket, chart/DOM trading, brackets, scaled orders, emulated algos, positions and orders — the same procedures as the owner guide but scoped to assigned accounts, and always by reference to the owner guide's canonical section where the steps are identical (no duplicated procedure).
- Trade groups and fan-out from the Manager's side: what a fan-out looks like when you are one of the destination accounts, and the native exchange-side SL invariant.
- Risk caps, lockouts and the kill switch: what each feels like from the inside, and who can release it (not you).
- Alerts and notifications; journal entries you own.
- Disconnect/stale/degraded states and the single escalation instruction: notify the Owner; you do not run runbooks.

**`docs/guide/viewer/` (P3):**
- The read-only contract: what is visible, what is not, and the guarantee that no control you can reach can place an order.
- Analysis workflow: charts, footprint, profiles, Deep-Stats, CVD, DOM heatmap, replay and tick replay, journal/analytics in read-only form, export/print where available.
- Reading *(estimated)* values honestly — the same methodology links as the owner guide.

**`docs/guide/rule-author/` (M1 mode):**
- When you are in this mode and what it does not change about your permissions.
- The **form editor** and the **node-graph editor** as two views of the same rule IR: what each is good at, what round-trips losslessly and what does not.
- Authoring a rule end to end: triggers, conditions, actions, the dry-run/simulation path, arming and disarming, and the rule runtime's independence from your UI session (a rule you armed keeps running after you sign out — this is stated explicitly because US-ONB-009's "sign out everywhere" scenario guarantees it).
- Safety: how risk caps and the kill switch override a rule; why a rule cannot bypass the native-SL invariant.
- Debugging: evaluation history, why a rule did not fire, and the error states.

## Out of scope
- P1/P4 content — E48-S01 (referenced, never duplicated).
- Rule engine internals, the IR schema and the node type reference — engineer-facing, covered by E48-T02's reconciliation of `docs/plan/24-internal-schemas.md` and ADR-0007.
- Administrative procedures of any kind: a Manager or Viewer who needs one escalates to the Owner.
- Android/mobile; non-Bybit exchanges.

## Acceptance criteria
```gherkin
Scenario: No guide teaches a forbidden action
  Given the manager, viewer and rule-author guides
  When every procedure is checked against the permission matrix in docs/plan/10-personas.md section 7
  Then no procedure requires a permission the persona lacks
  And each guide contains an explicit not-available list naming the controls the persona will not see and why

Scenario: The viewer guide contains no order-placement procedure
  Given docs/guide/viewer
  Then it contains no step that submits, amends or cancels an order
  And it states that no reachable control can place an order

Scenario: Procedures are referenced, not duplicated
  Given a procedure identical between the owner and manager guides
  Then the manager guide links to the owner guide's anchored section
  And the steps are not restated

Scenario: Rule-author guide states runtime independence
  Given docs/guide/rule-author
  Then it states that armed rules continue to run server-side after the author signs out
  And it states that risk caps and the kill switch override a rule

Scenario: Round-trip honesty between the two editors
  Given the section comparing the form editor and the node-graph editor
  Then it names exactly which constructs survive a round trip between them and which do not
  And that list matches the shipped behaviour verified during E48-T02

Scenario: Reviewed by a non-author
  Given each document's front-matter
  Then reviewer is present, differs from author, and reviewed_on is set
```

## Technical notes / design
Reuse E48-S01's section skeleton so the four guides are structurally diffable: a reviewer can diff `owner/trading.md` against `manager/trading.md` and see exactly the scope narrowing. The permission callout at the head of each chapter is generated from a single machine-readable copy of the §7 matrix (`docs/_meta/permissions.yaml`) so the four guides cannot drift from each other or from the matrix; if the matrix changes, one file changes.

The "not available to you, and why" list is generated from the same file — the absence of a control is derived, not hand-listed, which is what keeps it correct.

Rule-author content must be verified against the built product, not the spec: the form↔node round-trip fidelity list is produced by actually round-tripping a representative rule set in the demo environment and recording the result.

## Test plan
- **Permission diff test**: a script cross-checks every procedure's required-permission tag against `docs/_meta/permissions.yaml`; a procedure tagged with a permission the guide's persona lacks fails the build. This is the primary automated guard and runs in the E48-T01 CI gate.
- **Duplication check**: a similarity check across guide files flags any procedure body duplicated between personas above a threshold; duplicates must become links.
- **Round-trip verification**: at least 6 representative rules (simple threshold, multi-condition, time-window, nested boolean, action-fan-out, rule referencing a per-account profile) round-tripped form→node→form and node→form→node in the demo environment; results recorded and reflected in the text.
- **Walkthrough test** by a non-author for each persona: Manager places a bracketed order on an assigned account; Viewer completes an analysis task; Rule author builds, dry-runs, arms and disarms one rule.
- Link and front-matter schema checks as in E48-S01.

## Security notes
- Threat: privilege confusion — a guide that implies a Manager can do more than they can invites attempts, which show up as 403s and as noise in the audit log; worse, a guide that leaks admin procedure to a Manager gives a compromised Manager account a roadmap.
- Control: the manager/viewer guides contain no administrative procedure at all, and the generated not-available list explains absence without explaining how the Owner performs the action.
- The rule-author guide must state the safety overrides (risk caps, lockouts, kill switch, native-SL invariant) — an author who believes a rule can bypass them is a safety risk.
- Data classification: internal-confidential. `security` label applies (RBAC content); Security engineer sign-off before Done.

## Accessibility notes
- Same conventions as E48-S01: heading hierarchy, real tables for the permission matrix, alt text on every screenshot, no colour-only instructions.
- Node-editor descriptions must be meaningful without seeing the graph — describe the node's role in words before referring to its shape or colour, since the node editor is itself an E47 focus area.

## Performance notes
N/A at runtime; image payload budget per chapter ≤2 MB as in E48-S01.

## Observability
N/A — no code. The rule-author debugging chapter documents existing rule-evaluation logs/metrics rather than adding any.

## Definition of Done
- [ ] `docs/guide/manager/`, `docs/guide/viewer/`, `docs/guide/rule-author/` complete on the E48-D01 Learn template.
- [ ] `docs/_meta/permissions.yaml` created and the four guides' callouts generated from it.
- [ ] Permission diff test and duplication check green in CI.
- [ ] Round-trip fidelity list verified against the demo environment with the 6-rule corpus.
- [ ] Walkthrough test executed per persona by a non-author, zero blocking questions.
- [ ] Front-matter valid, reviewer ≠ author, dated.
- [ ] Security engineer sign-off; a11y checks pass; QA sign-off via E48-Q01.
- [ ] Demoed at Sprint Review (rule-author walkthrough recording).

## Dependencies
- `blocked_by` E48-S01 (section skeleton, callout pattern, canonical procedures to link to) and E48-D01 (templates/IA).
- Cross-epic: E36/E37 (rule form editor and node-graph editor — the round-trip behaviour being documented), E09 (auth/RBAC semantics), E39 (risk caps, lockouts, kill switch).

## Branch
`feat/e48-docs-manager-viewer-rule-guides`. Three PRs, one per persona guide, plus a small first PR introducing `docs/_meta/permissions.yaml` and the callout generation.

## References
- `docs/plan/10-personas.md` §3 (P2), §4 (P3), §6 (M1), §7 permission matrix
- `docs/plan/11-user-stories.md` US-ONB-009 (armed rules survive sign-out)
- `docs/plan/27-adrs/ADR-0007-rule-ir.md`
- `docs/plan/24-internal-schemas.md` (rule IR, OMS state machine)
- `docs/plan/30-release-roadmap.md` §9.3 exit criterion 6
"""

t("E48-S02", "Story",
  "Write the Manager, Viewer and rule-author guides (P2, P3, M1)",
  ["type/docs", "area/docs", "priority/p1", "security", "a11y", "qa"],
  "docs", "Sprint 25", "P1 High", "Product", "R10 Key-person", 3, "E48",
  ["E48-S01", "E48-D01", "E36", "E37", "E39"], S02)


S03 = """## Context
The app ships its own documentation surfaces, and at GA they must be true. E48-D02 produced a redline package for SCR-119 Help & about, SCR-058 detector methodology drawer, SCR-018 guided tour, SCR-019 setup checklist, plus label review for CMP-094 HotkeyOverlay, CMP-096 WhatsNewPanel and CMP-207 BuildFooter. This Story applies it.

Three things make this more than a string swap. First, SCR-119 is specified to be **fully available offline** with no network calls except an explicit update check — so the glossary and methodology copy must be bundled, within the ≤40 KB payload budget E48-D02 set. Second, SCR-119 exposes the **diagnostics bundle export**, whose behaviour US-OBS-007 constrains (secrets removed, generation fails loudly on a secret-pattern hit, size-capped with truncation stated) — the copy must match the behaviour, and where it does not, the *behaviour* is authoritative and the mismatch is a Bug. Third, SCR-019's per-role task copy is bound to the RBAC permission matrix, so it consumes `docs/_meta/permissions.yaml` from E48-S02 rather than hard-coding role logic a second time.

## Scope / Deliverables
- **SCR-119 Help & about**: apply every redline row — version rows (app, engine, backend, protocol, build hash, Bybit API version) via CMP-036 KeyValueRow; update-check result states; the copy-diagnostics control's statement of contents; the bundled **glossary** and **licence/attribution list** in CMP-051 Accordion sections; outward links (CMP-021 Link) to `docs/guide/`, the hotkey cheatsheet, the accessibility statement from E47, and the SCR-058 drawer; CMP-096 WhatsNewPanel `1.1.0` entry; CMP-207 BuildFooter labels.
- **SCR-058 detector methodology drawer**: the per-detector content authored in E48-D02 — heuristic, inputs, tunable thresholds, known false-positive modes, and the standing statement that Bybit provides no L3/MBO feed so these are proxies. Wire the drawer so **every** `(estimated)` chip in the product opens the matching entry; a chip with no entry must fail a test, not open an empty drawer.
- **SCR-018 guided tour**: replace the 8-stop copy; verify each stop's target still exists and each named hotkey is current; preserve the existing rules (dismissible, resumable from Settings → Help, never auto-shown twice, never blocking a trading control while LIVE).
- **SCR-019 setup checklist**: per-role task copy and blocked-reason strings rendered as **visible text**, driven by `docs/_meta/permissions.yaml`; deep links re-pointed at the anchored guide sections.
- **CMP-094 HotkeyOverlay**: label review against the shipped hotkey set; any hotkey present in the app but missing from the overlay is added, any stale entry removed.
- A **link table** extracted at build time listing every outward documentation link the app contains, emitted as an artefact that E48-T01's CI link checker and E48-D03's sweep consume.

## Out of scope
- Layout or component changes to these screens (content-only pass; a real layout defect is a Bug to E49).
- New components or new analytics events.
- Changing detector algorithms or diagnostics-bundle behaviour — if copy and behaviour disagree, file a Bug against the owning epic and document the shipped behaviour.
- Writing the guide content itself (E48-S01/S02) — this Story links to it.

## Acceptance criteria
```gherkin
Scenario: Every estimated chip opens a real methodology entry
  Given the built application
  When each (estimated) chip in the product is activated
  Then the SCR-058 drawer opens on a populated entry for that detector
  And an automated test enumerating chips against entries fails if any chip has no entry

Scenario: Help and about works with no network
  Given the application is running with all network access blocked
  When the user opens SCR-119
  Then every section including the glossary and the licence list renders fully
  And only the explicit update-check control reports a failure, in the check-failed state

Scenario: The diagnostics copy matches the behaviour
  Given the copy on the diagnostics-bundle control
  When a bundle is generated
  Then the contents match what the copy claims
  And a seeded secret pattern causes generation to fail loudly, as the copy states

Scenario: Blocked setup tasks explain themselves in visible text
  Given a manager viewing SCR-019
  Then tasks the manager cannot complete are marked aria-disabled
  And the reason is rendered as visible text next to the task, not only as a tooltip or a disabled style

Scenario: No documentation link is dead
  Given the extracted link table from the build
  When the link checker runs in CI
  Then every link resolves to an existing file and an existing explicit anchor
  And a missing anchor fails the build

Scenario: Tour stops match the shipped app
  Given the 8 tour stops
  When the tour is run end to end in the GA candidate
  Then every named control and panel exists
  And every named hotkey is registered in the shipped hotkey map

Scenario: Payload budget respected
  Given the settings bundle before and after this Story
  Then the added string payload is at most 40 KB uncompressed
```

## Technical notes / design
- Glossary, methodology and licence text ship as bundled string resources (JSON/TS modules) imported by the settings route's lazy chunk, so the app-boot budget in `docs/plan/06-performance-and-load-standard.md` is unaffected — only the settings chunk grows, and its growth is asserted in the size check.
- Chip→entry binding is by a **detector id**, not a display string, so translating or rewording a chip cannot break the link. The enumeration test walks the detector registry and asserts a methodology entry exists for every registered detector that renders an `(estimated)` chip.
- SCR-019 role logic consumes `docs/_meta/permissions.yaml` at build time (generated into a typed constant) — no second source of RBAC truth in the frontend.
- The link table is emitted by a small build step that scans the bundled string resources and route metadata for `docs/` targets; its output is `artifacts/doc-links.json`, consumed by E48-T01's checker.
- Error codes: no new ones. The update-check failure path reuses the existing check-failed state specified for SCR-119.

## Test plan
- **Unit**: glossary/methodology resource loaders; the detector-id→entry lookup (hit, miss, unknown id); the SCR-019 task-visibility function across owner/manager/viewer × each task; string-payload size assertion.
- **Contract**: none new. The link table's JSON shape is asserted against a schema shared with E48-T01.
- **Integration**: SCR-119 rendered with network blocked (offline test) asserting full content and the check-failed state; diagnostics-bundle copy-vs-behaviour test with a seeded secret pattern asserting loud failure.
- **E2E (Playwright, web + Electron)**: run the 8-stop tour to completion; open SCR-058 from at least three different `(estimated)` chips on different screens; complete one SCR-019 task as owner and confirm the same task shows a visible blocked reason as manager.
- **Enumeration test**: every registered detector has a methodology entry (this is the test that must fail loudly rather than degrade).
- **a11y**: axe-core on SCR-119, SCR-058, SCR-018, SCR-019 in CI; manual screen-reader pass over the drawer and the checklist.
- Coverage: ≥80% on the touched frontend package per `docs/plan/02-definition-of-ready-done.md` §3.2.

## Security notes
- Threat: information disclosure through the help surface — the licence/attribution list and any diagnostics description could enumerate internal package names or endpoints. Control: the published list is restricted to third-party dependencies and their licences; internal package names are not emitted.
- Threat: the diagnostics bundle is the highest-value artefact a user can produce; over-promising in copy ("fully anonymised") would encourage unsafe sharing. Control: copy states exactly the guarantees US-OBS-007 provides and no more; E48-X01's STRIDE model covers this surface and E48-X02 reviews the final strings.
- Threat: an outward link pointing off-tailnet would break the Tailscale-only posture and leak referrer information. Control: the link checker rejects any non-repo-relative documentation link.
- Data classification: internal. `security` label applies.

## Accessibility notes
- SCR-058 drawer: each detector section carries a heading so screen-reader users can jump between detectors; the drawer is a focus-trapped dialog with Esc to close and focus restored to the originating chip.
- SCR-019: real checkbox semantics with `aria-disabled` plus the reason as visible text; completion announced politely (existing spec preserved).
- SCR-018: focus moves to the coach-mark content and is restored on exit; reduced-motion disables the spotlight animation; the tour must never block a trading control while LIVE.
- SCR-119: static content with headings and a version table; the copy-diagnostics button's accessible name states what it copies; licence text in a scrollable region with a heading.
- axe-core green on all four surfaces; manual screen-reader pass recorded per `docs/plan/05-accessibility-standard.md`.

## Performance notes
- SCR-119 makes no network calls except the explicit update check and is fully available offline (its own spec) — preserved and tested.
- SCR-019 derives status from a single `GET /api/v1/onboarding/checklist` cached 60 s and never polls while hidden — preserved; no additional request is introduced.
- Added string payload ≤40 KB uncompressed, asserted in CI; settings chunk growth reported in the PR.
- SCR-018 coach marks use a single overlay layer with pointer-events pass-through and never remount the underlying panel — unchanged.

## Observability
No new events. Preserve `help.about_viewed`, `help.diagnostics_copied`, `help.update_check_requested`, `tour.started`, `tour.step_viewed`, `tour.dismissed`, `tour.completed`, `setup.task_completed`, `setup.checklist_dismissed`. Add the `artifacts/doc-links.json` build artefact for CI consumption (build-time, not runtime telemetry).

## Definition of Done
- [ ] All redline rows applied; E48-D03 design-QA sign-off recorded.
- [ ] Detector enumeration test green; zero chips without entries.
- [ ] Offline render test green; payload size assertion green.
- [ ] Link table emitted and green under E48-T01's checker.
- [ ] axe-core green on the four surfaces; manual screen-reader pass recorded.
- [ ] Coverage ≥80% on touched frontend packages.
- [ ] `docs/plan/14-screens-catalogue.md` entries updated if behaviour diverged during implementation.
- [ ] Changelog fragment written (user-visible change).
- [ ] Security engineer review comment present.
- [ ] QA sign-off via E48-Q01; demoed at Sprint Review.
- [ ] Feature flag: none — help-surface copy ships unflagged; recorded as such.

## Dependencies
- `blocked_by` E48-D02 (redline package), E48-S01 and E48-S02 (the guide sections and `docs/_meta/permissions.yaml` the links and role logic point at).
- Consumes E47's accessibility statement (linked from SCR-119) and the detector registry from the order-flow epics.

## Branch
`feat/e48-inapp-help-reconcile`. Suggest three PRs: (1) glossary/methodology resources + detector binding + enumeration test, (2) SCR-119/CMP-096/CMP-207/CMP-094 copy + link table build step, (3) SCR-018 tour + SCR-019 checklist copy. Each well under 400 LOC.

## References
- `docs/plan/14-screens-catalogue.md` SCR-018, SCR-019, SCR-058, SCR-119
- `docs/plan/15-component-catalogue.md` CMP-021, CMP-036, CMP-051, CMP-094, CMP-096, CMP-207
- `docs/plan/11-user-stories.md` US-OBS-007, US-SET-009, US-ONB-007
- `docs/plan/05-accessibility-standard.md`, `docs/plan/06-performance-and-load-standard.md`
- `docs/plan/02-definition-of-ready-done.md` §3.2
"""

t("E48-S03", "Story",
  "Reconcile the in-app help surfaces with shipped behaviour",
  ["type/docs", "area/docs", "priority/p1", "a11y", "qa", "security", "design-qa"],
  "web", "Sprint 25", "P1 High", "Development", "R10 Key-person", 3, "E48",
  ["E48-D02", "E48-S01", "E48-S02"], S03)


S04 = """## Context
This is the largest and least substitutable piece of E48. `docs/plan/07-release-and-prr.md` §5.2 requires runbooks to exist and to have been **read through** by the on-call rotation. `docs/plan/30-release-roadmap.md` §9.3 exit criterion 5 raises the bar for R5: *"All runbooks rehearsed at least once"*, and §9.4's Docs gate requires *"every runbook rehearsed and dated"*. A runbook that has never been executed is a hypothesis.

The set to rehearse (from `07-release-and-prr.md` §5.2 and `04-security-program.md` §10.3):

| # | Runbook | Rehearsal environment |
|---|---|---|
| RB-01 | WS disconnect / reconnect storm | staging (demo), fault injection |
| RB-02 | Exchange outage / 5xx | staging, fault injection |
| RB-03 | Rate-limit breach handling (Bybit `10018`) | staging, fault injection |
| RB-04 | OMS stuck-order reconciliation | staging (demo accounts) |
| RB-05 | Fan-out partial-failure recovery | staging (demo accounts) |
| RB-06 | Postgres failover | scratch environment |
| RB-07 | QuestDB / Parquet recovery from corruption | scratch environment |
| RB-08 | Feature-flag emergency kill | staging |
| RB-09 | Full-system rollback | staging (this rehearsal also satisfies `07-release-and-prr.md` §5.6) |
| IR-01 | Suspected unauthorised order / account compromise | tabletop + staging for the technical steps |
| IR-02 | Secret exposed | tabletop + real rotation of a *test* key |

RB-06 and RB-07 overlap the DR drill but are not the same thing: E48-T04 measures RTO/RPO against the §5.3 targets; this Story proves the *procedure text* is followable. Where a single execution can serve both, it is run once and recorded on both tickets, with the measurement discipline of T04 applied.

Timing is constrained: `30-release-roadmap.md` §10.1.0 places the GA regression + 72-hour soak (`q11`) from 2027-09-06, and a rehearsal that perturbs the environment after that date would invalidate the soak. All staging rehearsals therefore complete by **2027-09-04**; anything later runs in an isolated scratch environment.

## Scope / Deliverables
- A **rehearsal schedule** covering all 11 items, each with a named executor (an on-call rotation member who did **not** write that runbook — this is the point), a named observer from QA (E48-Q02), the environment, and the date.
- **Execution** of each rehearsal, following the runbook text literally. The rule is: *if the text is wrong, you do what the text says and record the failure* — you do not improvise and then write down what you wished the text said.
- A **rehearsal record** per runbook, appended to that runbook's Do-template record table (E48-D01) and carrying: date, executor, observer, environment, build tag, **step-by-step observed vs expected**, wall-clock duration, deviations, and a verdict (pass / pass-with-corrections / fail).
- **Correction PRs** to the runbook text for every deviation found — the corrections are part of this Story, not a follow-up.
- **Re-rehearsal** of any runbook that scored *fail*, after correction, before GA.
- Fault injection reusing **E45's chaos harness** (WS drop, exchange 5xx, rate-limit `10018`) rather than a new mechanism, so the rehearsal exercises the same faults the chaos catalogue asserts.
- Detection-vs-response recording: for each rehearsal, state whether the real alert path fired (per `07-release-and-prr.md` §5.1's alert list) or whether the fault was injected manually — so the evidence never over-claims that detection was proven.
- Update of `docs/plan/32-risk-register.md` with anything a rehearsal surfaced.

## Out of scope
- Writing the runbooks (E48-T03) — this Story rehearses and corrects them.
- The DR playbook's RTO/RPO measurement (E48-T04).
- Fixing product defects that a rehearsal exposes: a runbook step that cannot succeed because the *system* is wrong produces a Bug against the owning epic (or E49), and the rehearsal is recorded as failed until the Bug is fixed and the rehearsal re-run.
- Rehearsing against **prod (live)**. No rehearsal touches live funds or live keys. IR-02's rotation uses a disposable test key.

## Acceptance criteria
```gherkin
Scenario: Every runbook has a dated rehearsal record
  Given the eleven runbooks in scope
  Then each has a record naming date, executor, observer, environment and build tag
  And each record contains an observed-versus-expected line for every numbered step
  And no record has a verdict field left empty

Scenario: The executor did not write the runbook
  Given each rehearsal record
  Then the executor is not the author of that runbook
  And where that was impossible it is recorded as an explicit deviation with the reason

Scenario: A wrong step is recorded, not improvised around
  Given a runbook step whose expected observation does not occur
  When the executor continues
  Then the record states what was observed, what the executor did next, and that the step is a deviation
  And a correction PR to that runbook is linked from the record

Scenario: Failures are re-rehearsed
  Given a runbook with verdict fail
  When the corrections are merged
  Then the runbook is rehearsed again before GA
  And both records are retained, the later one superseding for gate purposes

Scenario: Detection is not over-claimed
  Given a rehearsal where the fault was injected manually
  Then the record states that detection was not exercised
  And only rehearsals where the real alert fired are recorded as having proven detection

Scenario: The soak is not perturbed
  Given the GA regression and 72-hour soak starting 2027-09-06
  Then every staging rehearsal completed on or before 2027-09-04
  And any later rehearsal ran in an isolated scratch environment

Scenario: Live is never touched
  Given all eleven rehearsals
  Then none executed against prod live
  And IR-02's rotation used a disposable test key, verified afterwards as revoked
```

## Technical notes / design
Record format (appended to each runbook, machine-readable front-matter key `rehearsed_on` plus a human table):

```
| Step | Expected observation | Observed | Verdict |
|---|---|---|---|
| 1 | Kill switch active within 5 s; new orders rejected | active in 3.1 s; rejected with the documented code | pass |
| 2 | ... | ... | deviation -> PR #1234 |
```

Fault injection per runbook: RB-01 drops the market WS at the harness level and asserts reconnection, resubscription, book resync and gap recording (the behaviour US-OBS-006's WS-disconnect drill already asserts automatically — the rehearsal adds the *human procedure* on top). RB-02 injects 5xx; RB-03 injects the rate-limit error path and exercises backoff plus the per-UID budget behaviour; RB-05 forces a partial fan-out (some accounts filled, some not) which is the single most safety-relevant rehearsal because the native exchange-side SL invariant must hold for every leg that did fill.

RB-09 (full-system rollback) is executed as the §5.6 rollback rehearsal: previous tag redeploys cleanly, migration compatibility confirmed, feature flags flip without a redeploy. Recording it once and citing it on both tickets is explicitly allowed; recording it twice from one execution is not.

IR-01 is run as a **tabletop** for the destructive steps (host rebuild, Tailscale node-key rotation) and as a real execution for the non-destructive ones (kill switch, session revocation, `GET /v5/user/query-api` verification, audit-chain integrity check against the off-box mirror). The record must state which steps were tabletop.

## Test plan
- **Per rehearsal**: the runbook itself is the test script; the observed-vs-expected table is the result.
- **Harness reuse check**: confirm each injected fault is the same fault the E45 chaos catalogue asserts, so a rehearsal passing while the catalogue fails (or vice versa) is impossible to miss.
- **Safety assertion on RB-05**: after a forced partial fan-out, assert every filled leg carries a native exchange-side SL; this assertion is automated and runs as part of the rehearsal, not eyeballed.
- **Regression**: any correction to a runbook that changes a step's expected observation triggers a re-read by the on-call rotation (§5.2's read-through requirement) recorded on the runbook.
- **Evidence integrity**: records are committed to the repo, not kept in a chat thread; E48-Q03's evidence pack indexes them.

## Security notes
- IR-01 and IR-02 are security runbooks; their rehearsal is supervised by the Security engineer and is in scope for `docs/plan/04-security-program.md` §10.
- IR-02's rehearsal performs a **real rotation of a disposable test key** — rotate first, investigate second (SR-143) — and afterwards verifies via `GET /v5/user/query-api` that the old key is gone and the new one is correctly scoped (withdrawal OFF, IP-whitelisted per SR-033).
- Rehearsal records themselves are sensitive: they contain environment topology, timing and failure modes. They are internal-confidential, must contain no key material, no tailnet addresses beyond what is already documented, and are reviewed by E48-X02 before the evidence pack is assembled.
- Kill-switch exercises during RB-08 and IR-01 must confirm the documented semantics: new order placement, rule-engine execution and fan-out all halt; existing open positions and orders are unaffected; release afterwards is clean.
- `security` label required; Security engineer sign-off before Done.

## Accessibility notes
N/A — no UI is produced. One authoring constraint carries over: runbook tables are real markdown tables with header cells (not ASCII art) so they are navigable by screen reader, and runbooks contain no images (they must be readable when everything else is down).

## Performance notes
No product performance budget applies. Two operational timings are recorded because they are what the on-call rotation actually needs to know: wall-clock duration of each rehearsal, and time-to-first-effective-action for the safety-critical ones (RB-05, RB-08, IR-01). These are recorded, not budgeted — the budgeted figures are T04's RTO/RPO.

## Observability
- Each rehearsal notes which Prometheus metrics and Grafana panels the executor actually used, and files a Task against E46/E49 for any panel that was missing or misleading — this is how `07-release-and-prr.md` §5.1's dashboard review becomes evidence-based rather than a nod.
- Where a synthetic alert exists, it is fired and confirmed to reach the on-call channel (§5.1's own requirement), and that confirmation is part of the record.
- Rehearsal execution is itself audited where it triggers audited actions (kill switch, session revocation, key rotation) — the audit entries are cited in the record.

## Definition of Done
- [ ] All 11 runbooks rehearsed, each with a complete dated record including observed-vs-expected per step.
- [ ] Every deviation has a merged correction PR; every `fail` verdict has a post-correction re-rehearsal.
- [ ] Executors were non-authors, or the exception is recorded.
- [ ] RB-09 recorded as satisfying `07-release-and-prr.md` §5.6 rollback rehearsal.
- [ ] RB-05's native-SL assertion automated and passing.
- [ ] IR-01/IR-02 supervised and signed off by the Security engineer; test key verified revoked.
- [ ] All staging rehearsals completed by 2027-09-04.
- [ ] `docs/plan/32-risk-register.md` updated with anything surfaced.
- [ ] On-call rotation re-read any corrected runbook (§5.2).
- [ ] QA observation records from E48-Q02 attached; QA sign-off.
- [ ] Demoed to the Owner: one rehearsal walked through live at Sprint Review.

## Dependencies
- `blocked_by` E48-T03 (the runbooks must exist to be rehearsed) and E45 (chaos/fault-injection harness and the chaos catalogue whose faults are reused).
- Cross-epic: E44 (kill switch, environment separation — RB-08 and IR-01 depend on it), E34 (fan-out and the rate-limit governor — RB-03, RB-05), E29 (OMS state machine — RB-04), E03/E04 (observability and CI/infra for the scratch environments).
- Coordinates with E48-T04 on the shared RB-06/RB-07 executions.

## Branch
`chore/e48-runbook-rehearsals` — records plus correction PRs. Correction PRs are separate and small, one per runbook, so a corrected procedure is reviewable on its own.

## References
- `docs/plan/07-release-and-prr.md` §5.1 observability/alerts, §5.2 runbooks, §5.6 rollback rehearsal, §7 rollback procedure
- `docs/plan/04-security-program.md` §9 kill switch, §10.2 incident flow, §10.3 IR-01/IR-02, SR-033, SR-143
- `docs/plan/30-release-roadmap.md` §9.3 exit criterion 5, §9.4 Docs gate, §9.5 key dates, §10.1.0 (`q11` soak window)
- `docs/plan/11-user-stories.md` US-OBS-004, US-OBS-006
- `docs/plan/03-testing-strategy.md` (chaos/failover layer)
- `docs/plan/32-risk-register.md`
"""

t("E48-S04", "Story",
  "Rehearse every runbook and record observed-versus-expected results",
  ["type/ops", "area/docs", "priority/p0", "security", "qa", "chaos"],
  "infra", "Sprint 25", "P0 Critical", "Ops", "R11 Alert reliability", 5, "E48",
  ["E48-T03", "E45", "E44", "E34", "E29"], S04)
