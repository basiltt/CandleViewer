# -*- coding: utf-8 -*-
"""E46 part 6: security tickets."""
from _e46_lib import T

tickets = []

tickets.append(T("E46-X01", "Task",
    "STRIDE threat model for performance telemetry, diagnostics and profiling artefacts",
    ["type/security", "security", "perf", "area/chart-engine", "area/backend-platform", "priority/p2"],
    "cross-cutting", "Sprint 23", "P2 Medium", "Security", "R2 Render performance", 3, "E46",
    ["E46-K01", "E43"],
    """## Context
`docs/plan/04-security-program.md` requires a STRIDE threat model per epic, and `docs/plan/02-definition-of-ready-done.md` §2.1 makes the kickoff a DoR item for any epic with a security surface. E46 looks like a pure-engineering epic, which is exactly why it needs the model: it adds a telemetry surface that is designed to be *copied out of the application and pasted into a bug report*, a benchmark action that is a deliberate heavy workload triggerable by a user, a new class of on-disk artefacts (`py-spy` dumps, `memray` captures, heap snapshots, soak logs) that can embed order and account data, and a set of Prometheus metrics whose labels, if unbounded, become both a memory-exhaustion vector and an information leak.

The system's threat model is favourable — one owner plus a few managers, private network, Tailscale-only remote access, no untrusted users, metrics endpoint bound to the private network per US-OBS-001's NFR — and the model must say so explicitly, because a threat model that ignores the deployment context produces mitigations nobody will implement. The job here is to separate the handful of things that genuinely matter (artefact handling, snapshot redaction, cardinality bounds, benchmark abuse, environment separation for load scripts) from the long tail that is correctly accepted.

## Scope / Deliverables
- **Data-flow diagram** of E46's additions: engine stage timer → worker stats channel → React store → SCR-046 overlay → clipboard snapshot; backend stage spans → Prometheus/OTel → Grafana/Alertmanager; SCR-118 benchmark → local settings store → support bundle (US-OBS-007); profiling tools → local artefact directory → release artefact store; load/soak scripts → demo environment.
- **STRIDE analysis** per element and per flow, covering at minimum: Spoofing (can anything push fabricated metrics into the pipeline?), Tampering (local settings store is user-writable; baseline files in `bench/baselines/` gate CI — who can move a baseline and how is it reviewed?), Repudiation (is a baseline change auditable?), Information disclosure (copy-diagnostics snapshot, support bundle, GPU fingerprinting, profiling artefacts, metric labels, timing side channels), Denial of service (benchmark as a self-inflicted GPU hog, metric cardinality explosion, profiling overhead on a production process, load scripts mis-targeted), Elevation of privilege (does the diagnostics overlay or SCR-118 expose anything an RBAC Viewer should not see? is any debug hook reachable in a release build?).
- **Data classification** for each artefact type: stage timings (Internal), diagnostics snapshot (Internal, designed for external paste — therefore must contain no Confidential field), profiling captures and soak logs (Confidential), benchmark result (Internal), metric series (Internal, private-network-bound).
- **Named mitigations** mapped to the tickets that implement them: allow-list snapshot construction (E46-S01), benchmark rate-limiting/blocking and stored-value range validation (E46-S02), closed stage-id enum for cardinality (E46-T01, E46-T04), build-flag exclusion of the injected-regression harness from release builds (E46-Q01), artefact storage/retention/access rules (E46-Q02), load-script target allow-list excluding live (E46-Q01, E44), baseline-change review policy (E46-T10, E46-T11/ADR-0016).
- **Accepted risks** recorded with rationale and Owner sign-off: notably timing side channels in the displayed numbers, and GPU/driver fingerprinting in the snapshot (both accepted deliberately, both needed for support).
- **Abuse-case seeds** handed to E46-X02 for testing.
- **Feed into** `docs/plan/32-risk-register.md` for anything that rises above accepted.

## Out of scope
- Executing the security testing (E46-X02).
- Re-modelling threats already covered by E43 (security hardening) or E44 (environment separation) — this model references them and covers only what E46 adds.
- Product-wide RBAC design (E09/E42).

## Acceptance criteria
```gherkin
Scenario: The model covers every element E46 adds
  Given the E46 data-flow diagram
  Then every new element and flow has a STRIDE row
  And each row is either mitigated by a named ticket or explicitly accepted with a rationale

Scenario: Confidential data cannot reach a pasteable artefact
  Given the copy-diagnostics snapshot and the support bundle
  Then the model requires allow-list construction rather than deny-list redaction
  And it names the specific fields that must never appear: session tokens, API keys, account identifiers, order identifiers

Scenario: Cardinality is bounded by design
  Given the new metric labels introduced by E46
  Then the model states the maximum series count each adds
  And any label whose values are user- or data-derived is rejected or bounded, satisfying US-OBS-001's NFR

Scenario: An accepted risk is a decision, not an omission
  Given timing side channels and GPU fingerprinting
  Then each is recorded as accepted with its rationale and the Owner's sign-off
  And neither is absent from the model

Scenario: Profiling in production is governed
  Given a profiling capture may be taken against a running backend
  Then the model states who may take one, where it is written, that the path is gitignored, its retention, and that it is never attached to a public issue
```

## Technical notes / design
Method per `docs/plan/04-security-program.md`: DFD with trust boundaries drawn (browser/renderer ↔ worker, frontend ↔ backend over Tailscale, backend ↔ exchange, backend ↔ Prometheus, developer workstation ↔ artefact store), then STRIDE per element, then mitigation mapping, then residual-risk acceptance.

The trust boundary that matters most here is the *artefact* boundary — the point where data leaves the controlled system in a form a human will forward. Snapshot, support bundle and profiling capture all cross it, and all three are handled by the same rule: allow-list what leaves, classify what remains.

Cardinality arithmetic is written out explicitly, not asserted: nine frontend stages × environments, four backend stages × environments, per-engine labels × engine count, and the resulting series totals compared against the Prometheus instance's documented headroom.

## Test plan
The model is reviewed, not tested; its testable outputs are E46-X02's abuse cases and the SAST/DAST rules derived from it. Each mitigation must be traceable to a test in its implementing ticket — the model includes that mapping column so a mitigation cannot be recorded as "done" without a test.

## Security notes
This ticket *is* the security notes for the epic. Classification of the model document itself: Internal.

## Accessibility notes
N/A — no UI surface.

## Performance notes
One finding of the model is the performance cost of the security controls themselves: allow-list snapshot construction and bounded-cardinality enums are cheap; profiling overhead on a production process is not, and the model states the `py-spy --nonblocking` requirement (already in `06-performance-and-load-standard.md` §8) as a security-relevant availability control, not merely a convention.

## Observability
Requires that a baseline change and a profiling capture are both auditable events (repudiation), naming where that audit record lives — the append-only audit log for in-app actions, and PR review history for baseline changes.

## Definition of Done
- [ ] All five Gherkin scenarios satisfied.
- [ ] DFD with trust boundaries drawn and merged under `docs/plan/` or the security workspace per `04-security-program.md` conventions.
- [ ] STRIDE table complete: element, threat, likelihood/impact, mitigation ticket or acceptance, test reference.
- [ ] Accepted risks signed off by the Owner and recorded.
- [ ] Mitigations filed against or confirmed present in E46-S01, E46-S02, E46-T01, E46-T04, E46-T10, E46-Q01 and E46-Q02.
- [ ] Abuse-case seeds handed to E46-X02.
- [ ] `docs/plan/32-risk-register.md` updated where warranted.
- [ ] Reviewed by the Security engineer and the Architect.

## Dependencies
- **E46-K01** — the toolchain decision determines which artefact types exist and where captures are written.
- **E43** — the existing security hardening baseline and the program's STRIDE conventions.

## Branch
`docs/e46-threat-model`. Docs-only.

## References
`docs/plan/04-security-program.md` · `docs/plan/02-definition-of-ready-done.md` §2.1, §3.1 · `docs/plan/11-user-stories.md` US-OBS-001, US-OBS-003, US-OBS-007 · `docs/plan/06-performance-and-load-standard.md` §8 · `docs/plan/14-screens-catalogue.md` SCR-046, SCR-118, SCR-119 · `docs/plan/20-architecture.md` §12.1 · `docs/plan/32-risk-register.md`
"""))

tickets.append(T("E46-X02", "Task",
    "Security review, abuse cases and SAST rules for the E46 telemetry and benchmark surface",
    ["type/security", "security", "perf", "area/chart-engine", "area/backend-platform", "priority/p2"],
    "cross-cutting", "Sprint 25", "P2 Medium", "Security", "R2 Render performance", 3, "E46",
    ["E46-X01", "E46-S01", "E46-S02", "E46-T01", "E46-T04", "E46-T10"],
    """## Context
E46-X01 produces the model; this ticket proves the mitigations exist and hold, and leaves behind automation so they cannot silently rot. `docs/plan/02-definition-of-ready-done.md` §3.2 requires, for anything labelled `security`, that SAST/SCA/secrets scanning is clean or triaged and that a Security engineer review comment is present; the planning brief additionally mandates SAST (CodeQL/Semgrep/Bandit), DAST (OWASP ZAP) and secrets scanning as standing controls.

The specific risk this ticket exists to close is quiet and durable: the copy-diagnostics snapshot and the support bundle are built from an allow-list *today*, and six months from now someone adds a convenient field. A one-off manual review does not prevent that. A committed Semgrep rule and a test that fails when a secret-shaped key reaches the snapshot builder does.

## Scope / Deliverables
- **Security review** of the epic's code surface: the snapshot builder and clipboard path (E46-S01), the benchmark runner, its guards and the local settings read path (E46-S02), the stage-timer and metric label construction (E46-T01, E46-T04), the trace/span-id and ingestion-timestamp propagation into the WS envelope (`docs/plan/23-ws-protocol.md` §3.1), the CI gate and baseline-update workflow (E46-T10), and the load/soak script target configuration (E46-Q01).
- **Abuse cases executed**, from E46-X01's seeds:
  1. A user with RBAC **Viewer** opens SCR-046 and SCR-118 and attempts to read or change anything beyond their role.
  2. The local settings store is hand-edited to out-of-range, wrong-typed and hostile values (huge panel counts, negative cadences, a string where a number belongs, a deeply nested object) and the app is launched.
  3. "Run benchmark" is triggered repeatedly and concurrently, and while an order ticket is open and while replay runs, attempting to starve the trading path.
  4. A crafted state object containing secret-shaped keys is fed to the snapshot builder; the output is inspected for leakage.
  5. A metric label is driven from user-controlled input (symbol name, workspace name) to attempt a cardinality explosion.
  6. A load script is pointed at the live environment base URL.
  7. A baseline file is modified in a PR without the required review path, attempting to move a gate silently.
  8. The injected-regression build flag is sought in a production bundle.
- **SAST rules** committed (Semgrep for the repo, Bandit for Python where applicable): a rule forbidding construction of a diagnostics/support artefact by serialising a whole state object; a rule flagging any Prometheus/OTel label whose value is not drawn from a closed enum or a bounded constant; a rule flagging any log or artefact write of an identifier field name from the deny list. Each rule ships with a passing and a failing test case.
- **DAST**: a ZAP pass over any new or changed HTTP surface touched by this epic (the metrics endpoint's network binding, `/admin/health` and `/system/build` as consumed by the overlay) confirming the private-network binding of the metrics endpoint from US-OBS-001's NFR and that no new unauthenticated endpoint appeared.
- **Regression tests**: a permanent test asserting the snapshot allow-list (secret-shaped key absent from output), a test asserting the injected-regression flag is absent from the release bundle, and a test asserting metric label cardinality stays within the modelled bound.
- **Findings triage**: each finding fixed, or accepted with Owner sign-off and recorded; **Security engineer sign-off comment** posted on the epic.

## Out of scope
- Threat modelling (E46-X01).
- Pen-test and its remediation (E43 / the R4 gate) — this ticket does not re-run a pen-test.
- Product-wide RBAC implementation (E09/E42); abuse case 1 verifies RBAC behaviour on these two screens, it does not change RBAC.
- Functional QA (E46-Q01..Q04).

## Acceptance criteria
```gherkin
Scenario: Nothing sensitive leaves in the snapshot
  Given a state object seeded with a session token, an API key, an account id and an order id
  When the copy-diagnostics snapshot is built
  Then none of those values or key names appear in the output
  And the test that proves this is permanent and runs in CI

Scenario: The benchmark cannot starve the trading path
  Given "Run benchmark" is triggered repeatedly and concurrently
  Then only one run executes at a time
  And it is refused with a stated reason while an order ticket is open or replay is active
  And it is cancellable

Scenario: Hostile local settings do not crash or escalate
  Given the local settings store contains out-of-range, wrong-typed and hostile values
  When the app launches
  Then each invalid value falls back to its documented default with a logged warning
  And the app starts normally and no value is used unvalidated

Scenario: Metric cardinality cannot be driven by user input
  Given an attempt to use a user-controlled string as a metric label value
  Then the committed SAST rule flags it in CI
  And at runtime the label set remains within the bound stated in the E46-X01 model

Scenario: A load script cannot target live
  Given a load script configured with the live environment base URL
  Then it refuses to start with an explicit error

Scenario: A baseline cannot move silently
  Given a PR that modifies a file in bench/baselines/ without the required review and rationale
  Then the CI workflow blocks the merge

Scenario: A Viewer sees nothing beyond their role
  Given a user with the Viewer role
  When they open SCR-046 and SCR-118
  Then no control that mutates shared or account state is available to them
  And no account or order data is present in anything either screen displays

Scenario: The debug slowdown harness is not shipped
  Given a production build
  Then the injected-regression build flag and its code path are absent from the bundle
```

## Technical notes / design
Allow-list testing is done by seeding rather than by inspection: build a state object containing deliberately secret-shaped values and assert their absence in the output, so the test keeps working when the snapshot gains new legitimate fields. Both key names and values are asserted.

Semgrep rules live alongside the repo's existing ruleset with the same review requirements; each rule is accompanied by a fixture pair (should-flag, should-not-flag) so that a rule that stops matching is itself caught.

Abuse case 7's control is a CI workflow condition on the `bench/baselines/` path plus a CODEOWNERS entry — the policy is stated in ADR-0016 (E46-T11) and enforced here.

DAST scope is deliberately narrow: E46 adds essentially no HTTP surface, so the pass is a confirmation (nothing new appeared, the metrics binding is unchanged) rather than a full scan, and the report says so.

## Test plan
- **Unit/CI**: the three permanent regression tests (snapshot allow-list, release-bundle flag absence, label cardinality bound).
- **SAST**: rule fixture pairs; full-repo run clean or triaged.
- **Manual**: the eight abuse cases, each with a written result.
- **DAST**: ZAP pass report attached.
- **SCA/secrets**: `pip-audit`, `npm audit`, secrets scan clean or triaged over the epic's changed paths.

## Security notes
This ticket is the security verification for E46. Classification of its outputs: the review report and abuse-case results are Internal; any finding that reveals an exploitable path is handled per the program's vulnerability-handling process and is not discussed in a public issue until fixed.

## Accessibility notes
Abuse case 1 (Viewer role) is executed with keyboard-only navigation as well as mouse, so that a role restriction implemented only as a visual hide is caught — a control that is invisible but still focusable and operable is both an a11y defect and a security one.

## Performance notes
The permanent regression tests must be cheap enough to run on every PR; the cardinality test reads the registered metric descriptors rather than scraping a live endpoint. The SAST rules must not add more than a trivial amount to the existing Semgrep run time.

## Observability
Confirms that the audit trail required by E46-X01 (baseline changes, profiling captures) actually exists and is queryable, and that the new metric surface is free of user-controlled labels.

## Definition of Done
- [ ] All eight Gherkin scenarios verified with recorded results.
- [ ] Security review report merged; every reviewed surface listed.
- [ ] Eight abuse cases executed and written up.
- [ ] SAST rules committed with fixture pairs and green in CI; Bandit/Semgrep/CodeQL clean or triaged.
- [ ] DAST pass report attached; metrics endpoint private-network binding confirmed.
- [ ] Three permanent regression tests merged and running on every PR.
- [ ] `bench/baselines/` CODEOWNERS + workflow guard in place.
- [ ] Findings fixed or accepted with Owner sign-off; **Security engineer sign-off comment posted on E46**.
- [ ] Outcome summarised for E46-Q04's evidence pack.

## Dependencies
- **E46-X01** supplies the model and the abuse-case seeds.
- **E46-S01**, **E46-S02**, **E46-T01**, **E46-T04**, **E46-T10** supply the code and configuration under review; all must be landed before the review is meaningful.

## Branch
`chore/e46-security-review`. Rules and tests may land as separate small PRs.

## References
`docs/plan/04-security-program.md` · `docs/plan/02-definition-of-ready-done.md` §3.2, §4.2 · `docs/plan/11-user-stories.md` US-OBS-001, US-OBS-003, US-OBS-007 · `docs/plan/14-screens-catalogue.md` SCR-046, SCR-118 · `docs/plan/23-ws-protocol.md` §3.1 · `docs/plan/22-api-openapi.yaml` `/admin/health`, `/system/build` · `docs/plan/06-performance-and-load-standard.md` §7.4, §8 · `docs/plan/05-accessibility-standard.md`
"""))
