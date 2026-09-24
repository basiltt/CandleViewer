# -*- coding: utf-8 -*-
"""E48 part 5 — engineering tasks T04-T06."""
from _e48_gen import t

T04 = """## Context
`docs/plan/30-release-roadmap.md` §9.3 exit criterion 5 requires the **DR playbook executed with measured RTO/RPO recorded**. `docs/plan/07-release-and-prr.md` §5.3 supplies the budget this measurement is scored against, and states plainly that exceeding either figure is a **fail** that blocks PRR sign-off and must be logged as a P1 finding in `docs/plan/32-risk-register.md` with a remediation Task — not noted and waved through:

| System | RPO | RTO |
|---|---|---|
| Postgres (accounts, RBAC, rule configs, orders/journal metadata) | ≤15 min (continuous WAL archiving between full backups) | ≤2 h to a booting, queryable instance in a scratch environment |
| QuestDB hot-tier (recent OHLC/tick) | ≤24 h (reconstructible from Parquet cold tier + re-ingestion) | ≤4 h to reconstruct the most-recently-traded symbol's hot-tier data via cold-tier replay |
| Parquet/DuckDB cold tier | 0 (immutable, append-only, redundantly stored) | ≤4 h to restore access to at least one symbol's full history from the off-box redundant copy |

Note what the RPO column actually demands: it is not enough to restore successfully, the drill must establish **how much data was lost** — which requires knowing the last committed write before the simulated failure and comparing it against the last write present after restore. A drill that reports only a duration has measured RTO and silently skipped RPO.

This is distinct from E48-S04's rehearsal of RB-06/RB-07. Those prove the *procedure text* is followable; this proves the *system meets its recovery budget*. Where one execution can serve both, it runs once with this Task's measurement discipline applied, and is recorded on both tickets.

## Scope / Deliverables
- **`docs/runbooks/dr/playbook.md`** — the disaster-recovery playbook: total-loss-of-host scenario, the ordered restoration sequence across the three tiers, the decision points (what can be reconstructed vs what is lost), the maintenance-mode / kill-switch preconditions, and the verification steps that prove the restored system is correct rather than merely running.
- **Drill procedure** (`docs/runbooks/dr/drill.md`) — how to run the measurement so that two people running it get comparable numbers: the marker-write protocol, the clock-start definition (the moment the failure is declared, not the moment someone starts typing), the scratch-environment provisioning, and the result template.
- **Executed drill**, one per tier, in a **scratch environment** — never against the live recorder tier (hard constraint; this is the R15 data-lifecycle mitigation):
  - *Postgres*: restore from the automated backup + WAL archive, boot the application against it, run a read query and an RBAC check. Measure RTO (declaration → app serving) and RPO (marker-write delta).
  - *QuestDB hot tier*: reconstruct the most-recently-traded symbol's hot data via cold-tier replay. Measure RTO and the actual data-loss window.
  - *Parquet/DuckDB cold tier*: restore at least one symbol's full history from the off-box redundant copy and verify integrity. RPO must measure **0**; a non-zero result is a P1 finding by definition, since the tier is specified as append-only with no acceptable loss.
- **Integrity verification**, not just availability: after each restore, an assertion that the restored data is *correct* — for Postgres, the audit-chain integrity check (`POST /api/v1/admin/audit/verify`, `docs/plan/04-security-program.md` §6.8 / §8.1); for the cold tier, a row-count and checksum comparison against the pre-failure state for the restored symbol.
- **Results recorded** in `docs/plan/32-risk-register.md` with an explicit **pass or fail per tier against the §5.3 table**, plus the raw numbers, the drill date, the executor and the build tag. SCR-146 Admin: backups & restore surfaces a "last restore drill" line — the drill updates it (the screen already renders `Last restore drill: <date> (passed, 24 min)`).
- **Backup-configuration confirmations** required by §5.3's first three checkboxes: Postgres backup schedule and WAL interval consistent with the ≤15-minute RPO; QuestDB strategy documented (including the explicit "accepted as replaceable from Parquet + re-ingestion" decision if that is the chosen posture); cold-tier redundancy and the automated 30-day retention / pin-to-keep enforcement verified.
- **P1 findings + remediation Tasks** for any tier that fails, filed against the owning epic, with the PRR consequence stated.

## Out of scope
- Rehearsing the procedure text for readability — E48-S04 (RB-06, RB-07).
- Any drill against **prod (live)**. No live data, no live keys, no live positions are touched. The playbook states this as a precondition.
- Building new backup capability. The backup jobs, the restore wizard (SCR-146) and the retention enforcement are E42's and the infrastructure epics' deliverables; this Task measures them. A missing capability is a Bug, and it fails the drill.
- Multi-region or hot-standby DR. The system is a single self-hosted host (WSL, later a VPS) per `docs/plan/00-planning-brief.md`; the DR posture is restore-from-backup, and the playbook says so rather than implying an availability guarantee that does not exist.

## Acceptance criteria
```gherkin
Scenario: Each tier's drill produces both numbers
  Given a completed drill for a tier
  Then the record contains a measured RTO and a measured RPO
  And each is compared against the docs/plan/07-release-and-prr.md section 5.3 target
  And the record carries an explicit pass or fail verdict, not only a raw duration

Scenario: RPO is measured, not assumed
  Given the marker-write protocol
  When the failure is simulated
  Then the last marker written before failure and the last marker present after restore are both recorded
  And the RPO is their time difference

Scenario: A missed budget becomes a P1 finding
  Given a tier whose measured RTO exceeds its target
  Then a P1 finding is logged in docs/plan/32-risk-register.md
  And a remediation Task is filed and linked
  And the PRR sign-off is recorded as blocked until it is resolved or formally risk-accepted by the Owner

Scenario: Restored data is verified correct, not merely present
  Given the Postgres restore has completed
  When the audit-chain integrity verification runs
  Then it passes
  And a divergence is treated as a failed drill even if the RTO target was met

Scenario: The cold tier loses nothing
  Given the Parquet cold tier drill
  Then the measured RPO is zero
  And a non-zero result is a P1 finding regardless of the RTO achieved

Scenario: The live tier is never touched
  Given any drill execution
  Then it runs in a scratch environment provisioned for the drill
  And the record names that environment
  And no live credential, position or recorder volume was accessed
```

## Technical notes / design
**Marker-write protocol** (this is the whole trick to measuring RPO honestly): before the simulated failure, a low-rate writer inserts a monotonic marker row into each tier at a known cadence (Postgres: a row in a drill table, 10 s cadence; QuestDB/Parquet: the natural ingestion stream already carries timestamps, so the marker is the last ingested tick timestamp per symbol). At failure declaration, record `T_fail` and the last marker id/timestamp committed. After restore, read the highest marker present. `RPO = t(last_marker_before_fail) − t(last_marker_after_restore)`. Without this, RPO is a guess dressed as a number.

**Clock-start definition**: RTO starts at *failure declaration*, not at first keystroke, and includes provisioning the scratch environment if the playbook's scenario requires it. This matters because a 20-minute restore preceded by 90 minutes of environment provisioning is a 110-minute RTO, and the §5.3 Postgres budget is 2 hours.

**Restoration order** in the total-loss scenario, and why: Postgres first (it holds RBAC, accounts and OMS state — without it nothing can be authorised or reconciled), then cold-tier Parquet access (immutable history, needed to rebuild anything else), then QuestDB hot tier by replay from cold. Trading stays disabled via the kill switch (`04-security-program.md` §9) until all three are verified, and the playbook makes re-enabling an explicit, separate, owner-authorised step — restoring a system and letting it place orders in the same breath is the failure mode this ordering exists to prevent.

**Exchange state is not restorable.** The playbook must state prominently what SCR-146's restore wizard already tells the operator: a restore does not change anything on Bybit. Positions and orders that exist on the exchange survive the disaster; the local mirror must be **reconciled** against the exchange after restore, not assumed. The reconciliation step reuses E45's reconciliation machinery and is part of the playbook's verification, not an afterthought.

**Endpoints/screens used**: `GET /api/v1/admin/backups`, `POST /api/v1/admin/backups/{backupId}/verify`, `POST /api/v1/admin/backups/{backupId}/restore`, `GET /api/v1/admin/jobs/{jobId}` (restore is a long-running job with staged progress), `POST /api/v1/admin/audit/verify`, `GET /api/v1/admin/health`; screens SCR-146 (backups & restore) and SCR-143 (system health).

Result-record template (one per tier, stored under `docs/runbooks/dr/records/`):

```
tier: postgres | questdb_hot | parquet_cold
drill_date: 2027-09-02
executor / observer: <names>
environment: scratch-<id>        build tag: <tag>
T_fail: <ts>   T_restored: <ts>   RTO_measured: <hh:mm>   RTO_target: 02:00
last_marker_before: <ts>   last_marker_after: <ts>   RPO_measured: <mm:ss>   RPO_target: 00:15
integrity_verification: pass | fail (<what was checked>)
verdict: PASS | FAIL     findings: <links>
```

## Test plan
- **Drill execution** is itself the test; it is executed once per tier, with a QA observer from E48-Q02 present, and is repeated for any tier that fails after remediation.
- **Automated assertions during the drill**: application boots against the restored Postgres and answers `GET /api/v1/admin/health` (readiness, `/health/ready`); an RBAC check returns the expected permission set for a known user; the audit-chain verification passes; for the cold tier, a checksum + row-count comparison for the restored symbol.
- **Negative test**: attempt the restore against a *deliberately corrupted* backup artefact and confirm the verify step (`POST /api/v1/admin/backups/{backupId}/verify`) rejects it before restore begins — a backup system that cannot detect a bad backup has an unmeasured RPO of infinity.
- **Retention test**: confirm the automated retention job enforces the 30-day default and honours pin-to-keep, by checking a pinned artefact survives past the window in the scratch environment.
- **Reproducibility**: the drill procedure is run by a second person for the Postgres tier only, to confirm the numbers are comparable (within 20%); a wide divergence means the procedure is under-specified and is corrected.
- Coverage target: N/A (operational drill). The objective criteria are the six measured numbers and their verdicts.

## Security notes
- Threat (`docs/plan/04-security-program.md` §6.10, SR-090…SR-099): backups contain envelope-encrypted credentials and the full audit log. A drill that decrypts them in a scratch environment creates a second copy of the crown jewels. Control: the scratch environment is provisioned with its own KEK-access path, is torn down and its volumes destroyed at drill end, and the teardown is recorded in the drill record. If the drill requires a real KEK, the Security engineer supervises.
- Threat (tampering / repudiation): the audit chain must verify after restore; a restored audit log that fails integrity verification means either backup corruption or tampering, and is escalated under IR-01 rather than retried quietly.
- Threat (information disclosure): drill records contain timings, symbol names and marker ids — no balances, no account ids, no keys. E48-X02 audits the records before they are merged.
- Downloading a backup is high-severity audited (`backup.downloaded`, SCR-146); the drill's downloads appear in the audit log and are expected — the drill record names them so an auditor can distinguish drill activity from an incident.
- Data classification: the drill touches restored copies of internal-confidential and secret-bearing data. Label `security` set; Security engineer sign-off required.

## Accessibility notes
N/A for the drill itself. The playbook and drill documents follow the *Do* template rules (real step tables, no images, intact heading hierarchy) so they are usable with a screen reader — the operator recovering a dead system may well be doing it from a phone-tethered terminal at an unhelpful hour.

## Performance notes
The budgets here are operational, not product: the §5.3 RTO/RPO table is the budget and the drill is the benchmark. No `docs/plan/06-performance-and-load-standard.md` budget applies. One observation worth recording for the next engineer: the cold-tier restore time scales with the symbol's history size, so the record states the restored symbol's data volume alongside the duration — a 4-hour restore of one month of BTCUSDT is a different result from 4 hours for one day.

## Observability
- The drill exercises and validates the backup-related alerting from `07-release-and-prr.md` §5.1 (disk usage approaching the recorder retention budget) and confirms the SCR-143 health surface reflects the degraded/restoring state truthfully.
- SCR-146's "last restore drill" line is updated by the drill — if it is not updated automatically, that is a Bug against E42, filed here.
- Drill records are retained under `docs/runbooks/dr/records/` and referenced from `docs/plan/32-risk-register.md`.

## Definition of Done
- [ ] `docs/runbooks/dr/playbook.md` and `drill.md` merged on the *Do* template with non-author reviewers.
- [ ] Three drills executed in a scratch environment, with a QA observer, before 2027-09-04.
- [ ] Six numbers measured (RTO + RPO per tier), each with an explicit pass/fail verdict against `07-release-and-prr.md` §5.3.
- [ ] Integrity verification passed per tier (audit chain for Postgres; checksum/row-count for cold tier).
- [ ] Negative test (corrupted backup rejected) and retention/pin test executed.
- [ ] Results recorded in `docs/plan/32-risk-register.md`; SCR-146's last-drill line updated.
- [ ] Any missed budget filed as a P1 finding with a remediation Task and the PRR consequence stated.
- [ ] Scratch environments torn down and volumes destroyed; teardown recorded.
- [ ] Security engineer sign-off; QA sign-off from E48-Q02.
- [ ] Exchange-state reconciliation step executed and recorded as part of the verification.
- [ ] Demoed to the Owner: the measured table walked through at Sprint Review.

## Dependencies
- `blocked_by` E48-T03 (RB-06/RB-07 procedures are the DR playbook's building blocks).
- Cross-epic: E42 (SCR-146 restore wizard and the backup jobs being measured), E45 (reconciliation machinery used in post-restore verification), E44 (kill switch — trading stays disabled through the restore), E04 (infrastructure for provisioning scratch environments).
- Coordinates with E48-S04 on shared RB-06/RB-07 executions; blocks E48-T06 (PRR cannot pass without these numbers).

## Branch
`chore/e48-dr-playbook-and-drill` — playbook + drill procedure in one PR, drill records in a second after execution.

## References
- `docs/plan/07-release-and-prr.md` §5.3 (RPO/RTO table and the pass/fail rule), §5.2, §7
- `docs/plan/30-release-roadmap.md` §9.3 criterion 5, §9.4 Docs gate, §9.5 key dates
- `docs/plan/04-security-program.md` §6.8 audit integrity, §6.10 SR-090…SR-099 backups, §8.1, §9 kill switch, §10.3 IR-01
- `docs/plan/14-screens-catalogue.md` SCR-143, SCR-146
- `docs/plan/22-api-openapi.yaml` `/admin/backups`, `/admin/backups/{backupId}/verify`, `/admin/backups/{backupId}/restore`, `/admin/jobs/{jobId}`, `/admin/audit/verify`, `/admin/health`, `/health/ready`
- `docs/plan/21-database-schema.md` (tiering, retention, pin-to-keep)
- `docs/plan/32-risk-register.md` (R15 data lifecycle)
"""

t("E48-T04", "Task",
  "Execute the disaster-recovery playbook and measure RTO/RPO per tier",
  ["type/ops", "area/docs", "priority/p0", "security", "qa"],
  "infra", "Sprint 25", "P0 Critical", "Ops", "R15 Data lifecycle", 5, "E48",
  ["E48-T03", "E42", "E45", "E44", "E04"], T04)


T05 = """## Context
Risk **R10 Key-person** in `docs/plan/32-risk-register.md` is the reason this epic exists, and this Task is its falsifiable test. `docs/plan/30-release-roadmap.md` §9.3 exit criterion 6 names the **onboarding guide** as a GA deliverable; §9.1 goal 4 states the intent more usefully — *"leave behind documentation and runbooks good enough that the system is operable by someone who did not build it."*

An onboarding guide that has never been followed by a newcomer is a document about what its author already knows. So the deliverable is not the guide: it is the guide **plus a recorded trial** in which someone who has never seen the repository goes from `git clone` to a running local stack in one working day, following only `docs/onboarding/`, with every point at which they got stuck recorded and then fixed.

The system they must get running is non-trivial: Python 3.12 FastAPI modular monolith, React + TypeScript frontend with a custom WebGL engine package, an Electron shell, and three storage tiers (Postgres, QuestDB, Parquet/DuckDB) under docker compose in WSL Ubuntu (`docs/plan/00-planning-brief.md`, `docs/plan/20-architecture.md`). "It works on my machine" is the default state of such a stack; the trial is what converts it.

## Scope / Deliverables
- **`docs/onboarding/README.md`** — the one-day path, in order: prerequisites (WSL Ubuntu, Docker, Python 3.12, Node, the exact versions), clone, `make bootstrap`, bring up the stack, seed fixture data, run the test suite, open the web app, open the Electron shell, place a paper order against the demo environment. Each step states its **expected observation** and the most likely failure with its fix.
- **`docs/onboarding/architecture-tour.md`** — a reading order through the reconciled documents (E48-T02), not a re-explanation: what to read first (`20-architecture.md` C4 L1/L2), what to read when touching each area, which ADRs matter for which subsystem, and the module map from architecture doc to directory.
- **`docs/onboarding/how-we-work.md`** — the SDLC in the form a newcomer needs it: branch naming, conventional commits, PR size guidance, the required checks and what each one means, the merge queue, the DoR/DoD gates, the ceremonies. Links to `docs/plan/01-sdlc-and-branching.md` and `02-definition-of-ready-done.md` rather than restating them; states the three rules people actually trip on (2 approvals incl. a code-owner, the `contracts` gate blocks merge, no direct pushes to `main`).
- **`docs/onboarding/local-development.md`** — the daily loop: `make contracts`, `make docs`, running a single test, running the E2E suite, regenerating the API/WS reference, connecting to the demo environment, where logs go, how to reset the local data tiers.
- **`docs/onboarding/glossary.md`** — the order-flow vocabulary a competent engineer will *not* know: footprint, delta, CVD, imbalance, iceberg (estimated), stop-run (estimated), value area, TPO, speed of tape, DOM heatmap, trade group, fan-out, native SL, per-account profile. Cross-linked to SCR-058's detector methodology so the in-app explanation and the engineer explanation do not diverge.
- **The trial**: one engineer from outside the build team (QA/SDET, DevSecOps or a designer with scripting ability — the point is that they did not build it) executes the guide on a clean machine, timeboxed to one working day, **observed but not helped**. Every stumble is logged with a timestamp.
- **Corrections** merged for every stumble, and a **re-trial** of any section that blocked the trial entirely.
- **Trial record** (`docs/onboarding/trial-record.md`): date, participant, machine/OS, elapsed time to each milestone, the stumble log, and the verdict against the one-day criterion.

## Out of scope
- A guide for non-engineers — the Owner/Manager/Viewer guides are E48-S01 and E48-S02.
- Building or fixing the developer tooling. If the trial shows `make bootstrap` is broken on a clean machine, that is a Bug against E01/E02 (filed here, and it fails the trial until fixed) — this Task documents and proves, it does not build.
- Onboarding to Bybit itself, exchange account creation, or anything requiring live credentials. The trial uses the demo environment and fixture data only; no live key is ever issued to a trial participant.
- Android, mobile or a separate admin app — none exist.

## Acceptance criteria
```gherkin
Scenario: A newcomer reaches a running stack in one day
  Given an engineer who has never seen the repository, on a clean machine
  When they follow only docs/onboarding/
  Then within one working day the backend, the three storage tiers, the web app and the Electron shell are running locally
  And they have run the test suite successfully
  And they have placed a paper order against the demo environment

Scenario: Help given is a defect
  Given the trial is observed
  When the participant asks a question that the guide should have answered
  Then the observer records it as a stumble and does not answer it until the timebox rule requires unblocking
  And every stumble produces a correction to the guide

Scenario: A blocking stumble forces a re-trial
  Given a stumble that stopped progress entirely
  When the correction is merged
  Then that section is re-trialled by a different person before this Task is Done

Scenario: Every step states what success looks like
  Given docs/onboarding/README.md
  Then every numbered step has an expected observation
  And every step with a known common failure names it and its fix

Scenario: The trial never touches live
  Given the trial participant
  Then they are issued no live credential
  And the environment used is demo with fixture data
  And the guide states this as a rule, not a suggestion

Scenario: The guide does not restate what it links to
  Given the how-we-work document
  Then it links to docs/plan/01-sdlc-and-branching.md and 02-definition-of-ready-done.md for the full rules
  And it contains no duplicated rule text that could drift from them
```

## Technical notes / design
The one-day path is a sequence of **milestones with timestamps**, because "one working day" only means something if the intermediate times are visible. Target splits, recorded in the trial record:

| Milestone | Target elapsed |
|---|---|
| Prerequisites installed, repo cloned | 1 h |
| `make bootstrap` complete, stack up under docker compose | 2 h |
| Fixture data seeded, web app opens and renders a chart | 3 h |
| Unit + contract suites green locally | 4 h |
| Electron shell runs | 5 h |
| Paper order placed against demo | 6 h |

Slack of two hours is deliberate; a trial that only fits with zero slack has not proven one day for the next person.

**Demo environment caveat that must be in the guide**: demo has no WS order entry — order placement against demo is REST-only (`docs/plan/01-sdlc-and-branching.md` §9, `docs/plan/07-release-and-prr.md` §4.1). A newcomer who tries to place a demo order over WS will fail confusingly; the guide states this at the step, not in an appendix.

**Fixture data**: the guide uses the recorded Bybit fixtures already used by the integration suite (`docs/plan/03-testing-strategy.md` §4.1) rather than a bespoke onboarding dataset, so the newcomer's local data is the same data the tests use and a divergence in one surfaces in the other.

**Observation protocol for the trial**: the observer takes timestamped notes and does not intervene, except that if the participant is blocked for >30 minutes on one step the observer unblocks them, records the unblock as a **blocking stumble**, and the trial continues — a trial that ends at the first wall measures less than one that reaches the end with its walls enumerated.

## Test plan
- **The trial is the test.** Executed once, then re-trialled per blocking stumble.
- **Automated**: a CI job (`onboarding-smoke`) runs `make bootstrap` plus stack-up plus the seed step in a clean container on a weekly schedule, so the guide's first three milestones cannot rot silently between now and whenever the next engineer actually arrives. This is the durable half of the deliverable.
- **Link and front-matter checks** via E48-T01's CI job across `docs/onboarding/`.
- **Glossary check**: every term in the glossary that also appears in SCR-058's methodology drawer is compared for consistency; a divergence is corrected in whichever surface is wrong.
- **Second-reader check**: the architecture tour is read by an engineer from a *different* area than its author (a frontend engineer reads the backend path and vice versa) to catch assumed knowledge.
- Coverage target: N/A. Objective criteria: the trial completes within one working day, and `onboarding-smoke` is green.

## Security notes
- Threat (credential exposure, `docs/plan/04-security-program.md` §6.14 SR-140…SR-146 — secrets in CI and developer environments): an onboarding guide is the classic place where someone helpfully pastes a working key or a KEK path. The guide contains **no secret, no KEK location, no tailnet address**; it describes how to obtain access through the proper channel and stops there. E48-X02 audits it.
- Threat (privilege escalation / over-provisioning): a newcomer is granted the minimum — demo environment, fixture data, no live key, no prod access, Viewer-equivalent RBAC on any shared environment. The guide states the access-request procedure and what will and will not be granted on day one.
- Control: the trial participant's temporary access is time-boxed and revoked at trial end; the revocation is recorded.
- Data classification: the guide is internal, non-secret by construction. Label `security` set so the Security engineer reviews it before merge.

## Accessibility notes
The onboarding documents follow `docs/plan/05-accessibility-standard.md` and E48-D01's *Learn* template: heading hierarchy intact, real tables, alt text on every screenshot describing what the reader must notice, terminal output given as text rather than as an image (so it is searchable and screen-reader accessible — and copy-pasteable, which is the practical reason).

## Performance notes
No product budget applies. The operational budget is the one-day criterion above, with the milestone splits as its sub-budgets. `make bootstrap` itself should complete in ≤20 minutes on the reference developer machine; longer is recorded as a finding against the tooling epics, since a bootstrap nobody waits through is a bootstrap nobody runs.

## Observability
- `onboarding-smoke` CI job result is the ongoing signal that the guide still works; a failure opens a Bug automatically.
- The trial record is the evidence for R10's risk-register update: `docs/plan/32-risk-register.md` R10 moves from "unmitigated" to "mitigated, evidenced by the trial of <date>" — or stays open with the gap named, if the trial failed.

## Definition of Done
- [ ] All five onboarding documents merged with non-author reviewers in front-matter.
- [ ] Trial executed by someone outside the build team on a clean machine, observed, timestamped.
- [ ] Every stumble logged and corrected; every blocking stumble re-trialled by a different person.
- [ ] `docs/onboarding/trial-record.md` merged with the verdict against the one-day criterion.
- [ ] `onboarding-smoke` CI job added and green on a weekly schedule.
- [ ] Glossary reconciled with SCR-058's methodology content.
- [ ] Architecture tour cross-read by an engineer from another area.
- [ ] `docs/plan/32-risk-register.md` R10 updated with the trial evidence.
- [ ] Security engineer review (no secrets, minimum access) recorded; trial access revoked and revocation logged.
- [ ] Demoed to the Owner: the trial timeline and the stumble log presented at Sprint Review.

## Dependencies
- `blocked_by` E48-T02 (the architecture tour reads the reconciled documents — touring stale architecture would teach the newcomer something false) and E48-D01 (the *Learn* template and front-matter schema).
- Cross-epic: E01/E02 (repo scaffolding, `make bootstrap`, CI), E04 (docker compose local stack), E43 (Electron shell packaging the guide walks through).
- Relies on E48-T01's `make docs` and link checker being in place for the documentation loop section.

## Branch
`docs/e48-onboarding-guide` — guide in one PR, `onboarding-smoke` CI job in a second, trial record and corrections in a third after execution.

## References
- `docs/plan/30-release-roadmap.md` §9.1 goal 4, §9.3 criterion 6
- `docs/plan/32-risk-register.md` R10 key-person
- `docs/plan/00-planning-brief.md` (stack, WSL/docker compose, team)
- `docs/plan/20-architecture.md` (C4 L1–L3), `docs/plan/27-adrs/README.md`
- `docs/plan/01-sdlc-and-branching.md` §9 (demo REST-only), `02-definition-of-ready-done.md`
- `docs/plan/03-testing-strategy.md` §4.1 recorded fixtures
- `docs/plan/04-security-program.md` §6.14 SR-140…SR-146
- `docs/plan/14-screens-catalogue.md` SCR-058
"""

t("E48-T05", "Task",
  "Write the engineer onboarding guide and prove it with a clone-to-running trial",
  ["type/docs", "area/docs", "priority/p1", "security", "type/ci"],
  "docs", "Sprint 26", "P1 High", "Development", "R10 Key-person", 2, "E48",
  ["E48-T02", "E48-D01", "E01", "E04", "E43"], T05)


T06 = """## Context
This is the last ticket in the plan. `docs/plan/30-release-roadmap.md` §9.3 exit criterion 8 — *"Final PRR re-run passes; GA declared; `v1.1.0` tagged"* — and §9.5's key date of **2027-09-24** land here. `docs/plan/07-release-and-prr.md` supplies the three checklists that must be executed: §4 release checklist, §5 PRR, and §6 the Live-enablement gate, which §1 states is re-run **in full, all four items, no subset** for R5 because R5 touches resilience/chaos/failover and security-debt burn-down — areas that directly affect the fan-out safety invariant and key handling.

The estimate is 1 point, and that is not a mistake: by the time this ticket starts, every input has been produced by another ticket. Its work is execution, evidence assembly and sign-off collection — not investigation. If this ticket turns out to be large, something upstream was skipped, and the correct response is to go fix that rather than to grow this one.

## Scope / Deliverables
- **Release checklist execution** (`07-release-and-prr.md` §4):
  - §4.1 pre-cut on `main`: all R5 epics Done or explicitly descoped; zero open P0/P1 bugs (E49's deliverable, verified here); full test pyramid green; **the `@demo-rest-only` E2E order-flow subset green against staging** with the assertion that no WS order-entry frames were sent to demo; coverage ≥85% backend/engine and ≥80% frontend with no regression; `CHANGELOG.md` Unreleased section reviewed.
  - §4.2 cut and soak: `release/1.1.0` branch cut; deployed to staging (demo); the **72-hour soak** from `30-release-roadmap.md` §10.1.0 (`q11`, starting 2027-09-06) monitored daily; any P0/P1 found restarts the soak clock; Owner demo performed with acceptance recorded.
  - §4.4 cut to prod: tag `v1.1.0`; GitHub Release published from the generated changelog; deploy via the same automation validated on staging; feature flags set to their intended prod defaults; rollback readiness reconfirmed; hypercare window opened; `main` reconciled with the release branch.
- **PRR execution** (§5), as a ceremony with Architect, DevSecOps, Security engineer, QA lead and the on-call owner: §5.1 observability (dashboards reviewed live, a synthetic alert fired and confirmed to reach the on-call channel), §5.2 runbooks (satisfied by E48-T03 + E48-S04's rehearsal records, and by the on-call read-through), §5.3 backups and restore drill (satisfied by E48-T04's measured pass/fail table), §5.4 capacity (E46's benchmarks and the k6/Locust load results with the 3–5× headroom statement; the per-account Bybit rate-limit budget for the in-scope fan-out account count), §5.5 security sign-off (SAST/SCA/secrets/DAST/container clean or risk-accepted with expiry; **STRIDE models for all R5-scope epics reviewed as a set** for cross-epic interaction risk; audit log verified append-only; keys confirmed envelope-encrypted and withdrawal OFF with a live spot-check in the admin screen), §5.6 rollback rehearsal (satisfied by E48-S04's RB-09 execution).
- **Live-enablement gate re-run in full** (§6, all four items): independent pen-test against the deployed staging build with Critical/High resolved and Medium/Low resolved or Owner-risk-accepted in writing; **key-permission audit** of every configured Bybit key verified *in the Bybit account settings*, not from app config — withdrawal OFF, IP whitelist restricted to the Tailscale-reachable addresses, trade+read scope only; **kill-switch test** end-to-end in staging (triggered, no new orders placeable, existing positions/orders unaffected, released cleanly); **Owner's written authorisation** having reviewed the pen-test summary and key audit.
- **GA evidence pack** assembly: one index linking every exit criterion of §9.3 to its evidence ticket — perf (E46), a11y conformance report (E47), defect state (E49), runbook rehearsal records and DR measurements (E48-S04, E48-T04), documentation completeness (E48-S01/S02/T01/T02/T05), chaos catalogue re-run (E45), the two-consecutive-weeks live-usage record with no P0 incident and no unresolved reconciliation discrepancy (criterion 7).
- **Release notes** for `v1.1.0` finalised from the accumulated changelog fragments, with the Security subsection written without exploit detail per §3.
- **GA declaration** recorded on this ticket with the Owner's acceptance.

## Out of scope
- Performing the pen-test (an independent tester, engaged per §6) — this ticket schedules it, triages its findings and records the outcome.
- Fixing anything the checklists surface. A failed checklist item sends the release back to soak with a named follow-up; the fix is a Bug against the owning epic.
- Post-GA operation beyond opening the hypercare window (§8 first-24h and first-7-day monitoring is on-call's standing duty, not this ticket's).
- Any R6+ planning.

## Acceptance criteria
```gherkin
Scenario: Every checklist item is executed and evidenced
  Given the release checklist, the PRR checklist and the Live-enablement gate
  Then every checkbox is ticked with a link to its evidence
  And no item is marked N/A without a one-line reason recorded

Scenario: The Live-enablement gate is re-run in full
  Given R5 is a release touching resilience and security-debt burn-down
  Then all four items of docs/plan/07-release-and-prr.md section 6 are executed
  And the PRR sign-off note states explicitly which case of the section 1 trigger rule applied and why
  And no item is skipped as already-done-at-R4

Scenario: Keys are verified at the exchange, not in the app
  Given the key-permission audit
  When each configured Bybit key is checked
  Then it is verified in the Bybit account settings directly
  And withdrawal permission is OFF, the IP whitelist is Tailscale-only, and scope is trade plus read
  And a key failing any of these blocks the gate

Scenario: The kill switch stops new risk without touching existing positions
  Given the kill-switch test in staging
  When the switch is triggered
  Then no new order can be placed and rule-engine execution and fan-out halt
  And existing open positions and orders are unchanged
  And the switch releases cleanly afterwards

Scenario: A failing item blocks the cut
  Given any checklist item that fails
  Then a no-go is recorded with named follow-up actions
  And the release returns to staging soak
  And the PRR is rescheduled rather than the item being waived

Scenario: The demo order-entry path is proven REST-only
  Given the at-demo-rest-only tagged E2E subset
  When it runs against staging
  Then it passes and asserts no WS order-entry frames were sent
  And a skipped or failing job blocks the release

Scenario: GA is declared with evidence
  Given the GA evidence pack
  Then every one of the eight exit criteria in docs/plan/30-release-roadmap.md section 9.3 links to its evidence
  And the Owner records written acceptance
  And v1.1.0 is tagged from the release branch HEAD
```

## Technical notes / design
Version: `v1.1.0` per `30-release-roadmap.md` §9. Semver reasoning (`07-release-and-prr.md` §2): R5 adds capability and hardening without a breaking contract change, so MINOR from the `1.0.0` declared at R4 Live enablement. If any R5 change did break the OpenAPI/WS contract or a persisted schema without a migration path, the bump is MAJOR instead and this ticket records the reasoning — the decision is explicit, not inferred from the commit log alone (the conventional-commits automation proposes, the release owner confirms).

Sequencing against the R5 calendar (`30-release-roadmap.md` §9.5, §10.1.0):

```
2027-09-04  E48-S04 rehearsals and E48-T04 drills complete (before the soak, so they cannot perturb it)
2027-09-06  release/1.1.0 cut; staging deploy; 72 h soak + GA regression (q11) begins
2027-09-10  documentation and runbook rehearsals complete (roadmap key date)
2027-09-1x  PRR ceremony; Live-enablement gate items executed; pen-test findings triaged
2027-09-24  tag v1.1.0, GitHub Release, prod deploy, hypercare opens, GA declared
```

The pen-test must be engaged early enough that Critical findings can be fixed before 09-24; the engagement is booked at the start of Sprint 25, not when this ticket starts. That booking is this ticket's only work item that cannot be deferred to Sprint 26.

Rollback readiness (§4.4, §7): before traffic reaches the new build unattended, confirm the previous tag redeploys cleanly and that R5's migrations are additive/backward-compatible so rolling back the app tag needs no emergency down-migration. E48-S04's RB-09 rehearsal is the evidence; this ticket re-confirms it against the actual release artefact.

Feature-flag posture at cut (§8): newly shipped user-visible behaviour defaults off or owner-only in prod, then ramps to all managers as hypercare confirms stability. This ticket records the flag-by-flag intended state so the ramp is a plan rather than a series of decisions made under pressure.

## Test plan
- **Checklist execution is the test**; each item's evidence is an artefact produced elsewhere and linked here.
- **Full pyramid re-run on the release candidate**: unit, contract (all nine `contracts` gates), integration against recorded Bybit fixtures, E2E Playwright web + Electron, the `@demo-rest-only` subset against staging, load (k6/Locust), engine FPS benchmarks, ingestion soak, security scans, axe-core.
- **Chaos catalogue full re-run** on the GA candidate (`30-release-roadmap.md` §9.4 Chaos gate) — executed by E45's harness, result recorded here.
- **Synthetic alert test** (§5.1): fire one synthetic alert and confirm it reaches the on-call channel out-of-band (SR-126 — the channel must not depend on the app being healthy).
- **Kill-switch test** as specified in §6, in staging, with the three assertions above.
- **Post-tag smoke**: health checks, a chart render, a demo paper order, and dashboard green-state confirmed within the first hour of the prod deploy.
- Coverage target: the §4.1 thresholds (≥85% backend/engine, ≥80% frontend) verified, not newly produced.

## Security notes
- This ticket *is* a security gate as much as a release gate. §5.5 and §6 are its substance: the STRIDE set review across all R5 epics (including E48-X01's model) for cross-epic interaction risk; the manual key-permission audit at the exchange; the kill-switch exercise.
- Threat (the gate itself being rushed to hit a date): `07-release-and-prr.md` §6 closes with the rule that Live-enablement is never rushed to hit a calendar date — if a Critical pen-test finding cannot be resolved, the release slips or ships with live trading behind an OFF flag. This ticket must state which of those happened; "we shipped anyway" is not an available option.
- Threat (information disclosure in release notes): the Security subsection describes fixes generally, never with exploit detail (§3); full detail stays in the Security engineer's internal finding tracker.
- Threat (repudiation): the Owner's written authorisation and every sign-off are recorded as ticket comments, and the audit log is verified append-only as part of §5.5 — the record of who authorised GA must itself be tamper-evident.
- Data classification: the evidence pack references secret-adjacent material (key audit results) — it records *that* each key was verified compliant, never the key or its fragment.
- Label `security` set; Security engineer is a required sign-off.

## Accessibility notes
The a11y gate at GA is E47's deliverable; this ticket verifies its evidence is present and complete — conformance report published, zero unresolved Level A/AA failures without written acceptance (`30-release-roadmap.md` §9.4 A11y gate) — and blocks the cut if it is not. No new UI is introduced here.

## Performance notes
Verification only: every budget in `docs/plan/06-performance-and-load-standard.md` CI-enforced (E46's deliverable), the 72-hour soak showing flat memory and no frame-budget regression, and the §9.4 rule that a >5% regression on any hard budget fails the build. This ticket confirms the gate is armed and green; it does not measure.

## Observability
- Hypercare window opened per §8 with a named on-call engineer on the release ticket; no unrelated prod deploys during the first 24 h.
- The first-7-day metric checks (order success rate, WS uptime/reconnect frequency, ingestion gaps, rule-engine error rate, recorder disk trend) are baselined against pre-release values as part of this ticket's close-out.
- GA declaration, tag, and sign-offs are recorded on the ticket and in `CHANGELOG.md`.

## Definition of Done
- [ ] §4 release checklist fully executed with evidence links.
- [ ] 72-hour soak completed clean on the release candidate.
- [ ] §5 PRR ceremony held; go decision recorded with sign-offs from Architect, DevSecOps, Security engineer and QA lead.
- [ ] §6 Live-enablement gate re-run in full, all four items, with the §1 trigger-rule reasoning stated in writing.
- [ ] Pen-test completed; Critical/High resolved; Medium/Low resolved or Owner-risk-accepted in writing.
- [ ] Key-permission audit completed at the exchange for every configured key.
- [ ] Kill-switch test executed and passed in staging.
- [ ] Chaos catalogue full re-run green.
- [ ] GA evidence pack assembled, linking all eight §9.3 exit criteria to their evidence.
- [ ] `v1.1.0` tagged; GitHub Release published; prod deploy completed via validated automation.
- [ ] Feature-flag prod defaults set and recorded; rollback readiness reconfirmed.
- [ ] Hypercare window opened; post-tag smoke green.
- [ ] GA declared 2027-09-24 with the Owner's written acceptance recorded.
- [ ] Retro note filed for the R5 train.

## Dependencies
- `blocked_by` E48-S04 (rehearsal records satisfy PRR §5.2 and §5.6), E48-T04 (measured RTO/RPO satisfies §5.3), E48-T05 (onboarding evidence for exit criterion 6), E48-Q03 (the GA readiness regression and evidence pack), E48-X02 (redaction review of everything published).
- Cross-epic: E46 (perf budgets CI-enforced — §5.4 and §9.4), E47 (accessibility conformance report — §9.4), E49 (zero open P0/P1 — §4.1 and criterion 3), E45 (chaos catalogue re-run — §9.4), E44 (kill switch — §6).
- This ticket blocks nothing; it is the terminal node of the plan.

## Branch
`chore/e48-ga-release` — release-branch cut and the changelog/release-notes finalisation are the only code-adjacent changes; everything else is evidence recorded on the ticket. PR is small by design.

## References
- `docs/plan/07-release-and-prr.md` §1 trigger rule, §2 semver, §3 changelog, §4 release checklist, §5 PRR, §5.1–§5.6, §6 Live-enablement gate, §7 rollback, §8 post-release monitoring
- `docs/plan/30-release-roadmap.md` §9.3 exit criteria, §9.4 quality gates, §9.5 key dates, §10.1.0 Gantt
- `docs/plan/04-security-program.md` §5 STRIDE, §6.8 audit, §9 kill switch, SR-126, SR-030…SR-039 key permissions
- `docs/plan/03-testing-strategy.md` (pyramid, `contracts` gate, chaos layer)
- `docs/plan/06-performance-and-load-standard.md`, `docs/plan/05-accessibility-standard.md`
- `docs/plan/02-definition-of-ready-done.md` §2.2, §4
"""

t("E48-T06", "Task",
  "Execute the GA checklist, re-run the PRR and Live-enablement gate, tag v1.1.0",
  ["type/ops", "area/docs", "priority/p0", "security", "qa", "perf", "a11y"],
  "docs", "Sprint 26", "P0 Critical", "Ops", "R5 Scope", 1, "E48",
  ["E48-S04", "E48-T04", "E48-T05", "E48-Q03", "E48-X02", "E46", "E47", "E49", "E45", "E44"], T06)
