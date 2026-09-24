# -*- coding: utf-8 -*-
"""Generate docs/plan/backlog/E48.json — Documentation, runbooks & GA readiness."""
import json, os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backlog", "E48.json")

T = []


def t(key, kind, title, labels, component, sprint, priority, perspective, risk,
      estimate, parent, blocked_by, body, phase="P5 Collaboration & Polish",
      milestone="R5 Hardening / GA"):
    T.append({
        "key": key, "kind": kind, "title": title, "labels": labels,
        "component": component, "phase": phase, "sprint": sprint,
        "priority": priority, "perspective": perspective, "risk": risk,
        "estimate": estimate, "parent": parent, "blocked_by": blocked_by,
        "milestone": milestone, "body": body,
    })


# --------------------------------------------------------------------------
# EPIC
# --------------------------------------------------------------------------
EPIC_BODY = """## Context
R5 (`docs/plan/30-release-roadmap.md` §9) has four goals; E48 owns the fourth outright — *"leave behind documentation and runbooks good enough that the system is operable by someone who did not build it"* — and co-owns the GA gate itself.

Three facts shape this epic:

1. **The runbooks are not optional and not "written" — they must be *rehearsed*.** `docs/plan/07-release-and-prr.md` §5.2 requires a runbook for each of: WS disconnect/reconnect storm, exchange outage/5xx, rate-limit breach handling, OMS stuck-order reconciliation, fan-out partial-failure recovery, Postgres failover, QuestDB/Parquet recovery from corruption, feature-flag emergency kill, and full-system rollback. `docs/plan/04-security-program.md` §10.3 adds the incident-response runbooks IR-01 (account compromise) and IR-02 (secret exposed). R5 exit criterion 5 (`30-release-roadmap.md` §9.3) upgrades "read through" to **"all runbooks rehearsed at least once; DR playbook executed with measured RTO/RPO recorded"**. That is the single largest piece of work in this epic and it is a *doing* task, not a *writing* task.
2. **The docs must describe the system that was actually built, not the system that was planned.** `docs/plan/02-definition-of-ready-done.md` §2.2 requires the `2x-*` architecture/schema docs and `1x-*` product docs to reflect *final shipped behaviour* where they diverged during implementation. After 22 sprints of implementation across 47 preceding epics, divergence is certain. E48 performs the reconciliation sweep, updates the ADR index, and publishes an API/WS reference generated **from the contract** (`docs/plan/22-api-openapi.yaml`, `docs/plan/23-ws-protocol.md`) rather than hand-maintained, so it cannot rot again.
3. **The reader is a person, and there are four of them.** `docs/plan/10-personas.md` defines P1 Owner / discretionary order-flow trader, P2 Account Manager, P3 Viewer / analyst, P4 Admin (owner hat), plus the M1 Rule-author mode. The user guide is written per persona against the permission matrix in `10-personas.md` §7 — a Manager must never be told to do something RBAC forbids them, and a Viewer must never be handed an order-ticket walkthrough.

E48 also carries the **GA checklist execution**: the final PRR re-run (`07-release-and-prr.md` §5), the R5 full four-item Live-enablement gate re-run (§6 — mandatory in full for R5 per §1's trigger rule), the release checklist (§4), the `v1.1.0` tag and the GA declaration on 2027-09-24.

## Goal
At the GA cut, every one of the following is true and evidenced on a ticket:
- A persona-scoped user guide exists and has been read end-to-end by someone who is not its author.
- Every runbook in `07-release-and-prr.md` §5.2 and `04-security-program.md` §10.3 has a dated rehearsal record with observed-vs-expected results.
- The DR playbook has been *executed*, with measured RTO/RPO per tier compared against the pass/fail table in `07-release-and-prr.md` §5.3.
- `docs/plan/20-architecture.md`, `21-database-schema.md`, `24-internal-schemas.md` and the ADR index match the built system, and a CI check keeps the API/WS reference in sync with the contract.
- An engineer who has never seen the repo can go from clone to a running local stack, following only `docs/onboarding/`, in one working day — proven by an actual trial.
- The GA checklist is executed, the PRR passes, `v1.1.0` is tagged.

## Scope (in)
- Persona user guide (P1/P2/P3/P4 + M1 rule-author mode) — E48-S01, E48-S02.
- In-app help surface accuracy: SCR-119 Help & about, SCR-058 detector-methodology drawer, SCR-018 guided tour copy, SCR-019 setup checklist, CMP-094 HotkeyOverlay, CMP-096 WhatsNewPanel, CMP-207 BuildFooter — E48-S03.
- Published API/WS reference + CI contract-freshness gate — E48-T01.
- Architecture/schema/ADR reconciliation sweep — E48-T02.
- Runbook set completion — E48-T03; runbook *rehearsal programme* — E48-S04.
- DR playbook + measured RTO/RPO drill — E48-T04.
- Engineer onboarding guide + trial — E48-T05.
- GA checklist execution, PRR re-run, release notes, `v1.1.0` tag — E48-T06.
- Design: documentation IA and reading experience (D01), SCR-119/SCR-058 content-design update (D02), design QA of documentation surfaces (D03).
- QA: documentation-accuracy black-box verification (Q01), rehearsal-observation charter (Q02), GA readiness regression + evidence pack (Q03).
- Security: STRIDE for the documentation and support-bundle surface (X01), redaction review of every published artefact and rehearsal record (X02).

## Scope (out)
- Android and any mobile documentation — Android is out of scope per the owner decision of 2026-09-14 (`docs/plan/00-planning-brief.md`).
- A separate admin application's documentation — there is no separate admin app; owner/admin functions are RBAC-gated screens inside the web app.
- Exchanges other than Bybit USDT linear perpetuals.
- *Fixing* the defects that documentation review uncovers: findings are filed as Bugs against E49 (Defect burn-down) unless the fix is a one-line doc correction.
- Performance and accessibility remediation — E46 and E47 respectively. E48 only *documents* their outcomes (the perf budget table and the accessibility conformance report are produced by those epics and referenced here).
- Public/marketing documentation, a docs website, or anything internet-facing: this is a private, Tailscale-only, single-owner system.

## Exit criteria
1. R5 exit criterion 5 met: all runbooks rehearsed at least once with dated records; DR playbook executed with measured RTO/RPO recorded in `docs/plan/32-risk-register.md`.
2. R5 exit criterion 6 met: user guide, ops runbooks, API/WS reference, ADR index and onboarding guide all complete.
3. `07-release-and-prr.md` §5 PRR passes with all sub-checklists green; the R5 full four-item Live-enablement gate (§6) is re-run and signed off in writing by the Owner.
4. The "Docs" quality gate of `30-release-roadmap.md` §9.4 is satisfied: *every runbook rehearsed and dated; docs reviewed by someone who did not write them* — the reviewer's name and date appear on each document's front-matter.
5. `v1.1.0` tagged; GA declared 2027-09-24; release notes published.

## Story / ticket list
| Key | Kind | Title | Pts |
|---|---|---|---|
| E48-D01 | Task (design) | Documentation information architecture & reading experience | 3 |
| E48-D02 | Task (design) | Content-design pass on SCR-119, SCR-058, SCR-018, SCR-019 | 3 |
| E48-D03 | Task (design-qa) | Design QA of the documentation and help surfaces | 2 |
| E48-S01 | Story | Owner & Admin user guide (P1, P4) | 5 |
| E48-S02 | Story | Manager, Viewer and rule-author guides (P2, P3, M1) | 3 |
| E48-S03 | Story | Reconcile the in-app help surfaces with shipped behaviour | 3 |
| E48-S04 | Story | Rehearse every runbook and record observed-vs-expected | 5 |
| E48-T01 | Task | Publish the API/WS reference from the contract + CI freshness gate | 5 |
| E48-T02 | Task | Reconcile architecture, schema docs and the ADR index with the built system | 3 |
| E48-T03 | Task | Complete the operations runbook set | 2 |
| E48-T04 | Task | Disaster-recovery playbook with measured RTO/RPO | 5 |
| E48-T05 | Task | Engineer onboarding guide + clone-to-running trial | 2 |
| E48-T06 | Task | Execute the GA checklist, re-run the PRR, tag v1.1.0 | 1 |
| E48-Q01 | Task (qa) | Documentation-accuracy black-box verification | 5 |
| E48-Q02 | Task (qa) | Rehearsal-observation charter & exploratory docs sweep | 3 |
| E48-Q03 | Task (qa) | GA readiness regression + evidence pack | 5 |
| E48-X01 | Task (security) | STRIDE threat model: documentation & support-bundle surface | 3 |
| E48-X02 | Task (security) | Redaction review of every published artefact and rehearsal record | 3 |

Engineering points (Stories + Tasks only): 5 + 3 + 3 + 5 + 5 + 3 + 2 + 5 + 2 + 1 = **34**, exactly the R5 budget for E48 in `docs/plan/30-release-roadmap.md` §3. Design (3+3+2 = 8), QA (5+3+5 = 13) and Security (3+3 = 6) carry their own points on top and are tracked against the design/QA/security capacity lines, per `docs/plan/00-planning-brief.md`. This Epic's `estimate` field is the sum of **all** children = 34 + 8 + 13 + 6 = **61**.

## Risks
| Risk | Why it bites here | Mitigation |
|---|---|---|
| **R10 Key-person** | This epic exists *because* of R10 — the whole system currently lives in the heads of the people who built it. If E48 slips, R10 remains unmitigated at GA. | E48 is scheduled S25–S26 with T05's onboarding trial as the falsifiable test of R10 mitigation; the trial is run by someone outside the build team. |
| **R5 Scope** | "Documentation" is unbounded unless fenced. | Every ticket names its artefacts explicitly; anything not named is out of scope and filed to Backlog. |
| **R15 Data lifecycle** | Rehearsal of QuestDB/Parquet recovery and the DR drill touches real recorded data and retention policy. | Drills run against a scratch environment with restored copies, never against the live recorder tier; the DR ticket states this as a hard constraint. |
| **R11 Alert reliability** | Runbook rehearsals depend on alerts firing to *start* the runbook; a rehearsal that is manually triggered proves the procedure but not the detection. | Each rehearsal fires the real synthetic alert path (`07-release-and-prr.md` §5.1) where one exists, and records separately whether detection or only response was exercised. |
| **Documentation drift after GA** | The reference could rot the day after it is published. | T01's CI freshness gate makes contract drift a build failure, not a documentation debt. |
| **Rehearsal windows collide with the 72 h soak** | `30-release-roadmap.md` §10.1.0 places `q11` GA regression + 72 h soak at 2027-09-06 → 2027-09-24 on the GA candidate; a runbook rehearsal that perturbs the environment would invalidate the soak. | S04 and T04 are scheduled in S25 and must complete before the soak starts on 2027-09-06 (R5 key dates: "Documentation and runbook rehearsals complete" = 2027-09-10 — E48 targets 09-04 to leave slack); any rehearsal that must run later uses a separate scratch environment. |

## Dependency graph (children)
```mermaid
flowchart TD
    subgraph Design["Design — S23/S24 (2 sprints ahead)"]
        D01[E48-D01 Docs IA & reading experience]
        D02[E48-D02 Content design: SCR-119/058/018/019]
        D03[E48-D03 Design QA of docs surfaces]
    end
    subgraph Eng["Engineering — S25/S26"]
        T02[E48-T02 Architecture/ADR reconciliation]
        T01[E48-T01 API/WS reference + CI gate]
        T03[E48-T03 Runbook set completed]
        S01[E48-S01 Owner & Admin guide]
        S02[E48-S02 Manager/Viewer/rule-author guides]
        S03[E48-S03 In-app help reconciliation]
        S04[E48-S04 Runbook rehearsals]
        T04[E48-T04 DR playbook + RTO/RPO drill]
        T05[E48-T05 Onboarding guide + trial]
        T06[E48-T06 GA checklist / PRR / v1.1.0]
    end
    subgraph Assure["QA & Security"]
        Q01[E48-Q01 Docs-accuracy verification]
        Q02[E48-Q02 Rehearsal-observation charter]
        Q03[E48-Q03 GA readiness regression + evidence]
        X01[E48-X01 STRIDE docs & support bundle]
        X02[E48-X02 Redaction review]
    end

    D01 --> S01
    D01 --> S02
    D01 --> T05
    D02 --> S03
    S03 --> D03
    T02 --> T01
    T02 --> T05
    T03 --> S04
    T03 --> T04
    S01 --> S02
    S01 --> Q01
    S02 --> Q01
    T01 --> Q01
    X01 --> X02
    S04 --> Q02
    T04 --> Q02
    Q01 --> Q03
    Q02 --> Q03
    X02 --> Q03
    S04 --> T06
    T04 --> T06
    T05 --> T06
    Q03 --> T06
```

## Cross-epic dependencies
- **E46 Performance hardening** — the perf budget results table quoted by the user guide and the PRR §5.4 capacity section is produced by E46; E48 cannot publish final numbers before E46 closes (S25).
- **E47 Accessibility conformance** — the VPAT-shaped conformance report is produced by E47; E48 links and indexes it, and the user guide's accessibility section quotes it.
- **E49 Defect burn-down** — documentation review findings that are product defects are filed to E49; the GA checklist's "zero open P0/P1" criterion is E49's to satisfy.
- **E43 Security hardening & pen-test remediation / E44 Live-enablement gating** — supply the pen-test summary, key-permission audit procedure and kill-switch drill that the R5 Live-enablement gate re-run (T06) repeats.
- **E45 Reconciliation, chaos & failover resilience** — supplies the chaos catalogue whose scenarios several runbooks respond to; rehearsals reuse E45's fault-injection harness rather than inventing one.
- **E42 Admin screens** — SCR-146 Admin: backups & restore is the operator-facing surface the DR playbook drives; SCR-143/147 are quoted by runbooks.
- **E01/E02** — the docs tree, CI and the repo conventions that T01's freshness gate plugs into.

## Definition of Done (epic)
- [ ] All children Done or explicitly descoped with a recorded disposition.
- [ ] R5 exit criteria 5 and 6 evidenced (rehearsal records + DR measurement + six document sets complete).
- [ ] `30-release-roadmap.md` §9.4 "Docs" gate satisfied: every runbook dated and rehearsed; every document carries a non-author reviewer name and date.
- [ ] `docs/plan/2x-*` and `1x-*` docs match shipped behaviour; ADR index reconciled.
- [ ] a11y: the in-app help surfaces changed by S03 pass axe-core and a manual screen-reader pass (`docs/plan/05-accessibility-standard.md`).
- [ ] security: X01 STRIDE finalised, X02 redaction review clean, Security engineer sign-off.
- [ ] QA sign-off: Q03 evidence pack complete and accepted.
- [ ] Demoed to the Owner: a live walkthrough of one runbook rehearsal and the onboarding trial result.
- [ ] Final PRR passed; `v1.1.0` tagged; GA declared.

## References
- `docs/plan/30-release-roadmap.md` §9 (R5), §9.3 exit criteria, §9.4 gates, §9.5 key dates, §10.1.0 Gantt reading notes.
- `docs/plan/07-release-and-prr.md` §4 release checklist, §5 PRR, §5.2 runbooks, §5.3 backups/restore + RPO/RTO table, §5.6 rollback rehearsal, §6 Live-enablement gate, §7 rollback, §8 post-release monitoring.
- `docs/plan/04-security-program.md` §10 incident response, §10.3 runbooks IR-01/IR-02.
- `docs/plan/02-definition-of-ready-done.md` §2, §3, §4.
- `docs/plan/10-personas.md` §2–§7 (P1–P4, M1, permission matrix).
- `docs/plan/14-screens-catalogue.md` SCR-018, SCR-019, SCR-058, SCR-119, SCR-143, SCR-145, SCR-146, SCR-147.
- `docs/plan/20-architecture.md`, `21-database-schema.md`, `22-api-openapi.yaml`, `23-ws-protocol.md`, `24-internal-schemas.md`, `26-chart-engine-design.md`, `27-adrs/`.
- `docs/plan/03-testing-strategy.md`, `05-accessibility-standard.md`, `06-performance-and-load-standard.md`, `32-risk-register.md` (R10 key-person), `33-raci.md`.
"""

t("E48", "Epic", "Documentation, runbooks & GA readiness",
  ["type/feature", "area/docs", "priority/p1", "qa", "security", "design", "handoff"],
  "docs", "Sprint 25", "P1 High", "Ops", "R10 Key-person", 61, None,
  ["E46", "E47", "E43", "E44", "E45", "E42", "E01", "E02"], EPIC_BODY)
