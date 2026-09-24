# -*- coding: utf-8 -*-
"""Generate docs/plan/backlog/E46.json — Performance hardening & budget enforcement (R5)."""
import json, os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backlog", "E46.json")

PHASE = "P5 Collaboration & Polish"
MS = "R5 Hardening / GA"

def T(key, kind, title, labels, component, sprint, priority, perspective, risk,
      estimate, parent, blocked_by, body):
    return dict(key=key, kind=kind, title=title, labels=labels, component=component,
                phase=PHASE, sprint=sprint, priority=priority, perspective=perspective,
                risk=risk, estimate=estimate, parent=parent, blocked_by=blocked_by,
                milestone=MS, body=body)

tickets = []

# ---------------------------------------------------------------- EPIC
epic_body = """## Context
R5 (`docs/plan/30-release-roadmap.md` §9) exists to convert "meets budget on reference hardware once" into "meets budget under the Owner's real, messy, multi-day usage, and stays there because CI refuses to let it drift". E46 is the epic that does the performance half of that job.

Every number this epic defends is already written down: the 15 budgets in `docs/plan/06-performance-and-load-standard.md` §2, the per-stage frame allocation in §4.3, the WS tick→screen stage allocation in §5.1, the order-ack allocation in §5.2, the ingestion/memory/storage budgets in §6, the harness design in §7, the ≤5 % CI regression gate in §7.4, the profiling playbook in §8, the consolidated load scenarios in §9 and the capacity plan in §10. The chart-engine package has its own ten benchmark gates B1–B10 in `docs/plan/26-chart-engine-design.md` §13. The backend metric surface is `docs/plan/20-architecture.md` §12.1, and the cross-stack budget table is §13.2.

What is *not* yet true at the start of S23, and is exactly E46's job:
1. The §4.3 stage breakdown exists as prose but is not emitted as machine-readable per-stage timings on every benchmark run, so a regression cannot be stage-attributed automatically (the profiling playbook's mandatory step 2).
2. Footprint cell text is the flagged largest CPU-side cost (§4.3, ≤4 ms slice; `26-chart-engine-design.md` §3.7 measures ~0.9 ms CPU batching at 12,500 glyphs but the product has since grown overlays), and has never had a dedicated optimisation pass.
3. The heatmap upload path (§4.2, `26-chart-engine-design.md` §3.8) is written to be constant-cost but has never been profiled under the real ring-wrap + priceOrigin-shift + coarse-ring-rollover combination.
4. Backend hot paths (book delta application, bar building, fan-out serialisation) have never been profiled with `py-spy`/`memray` against the full 10-symbol capacity scenario.
5. Nothing has been soaked for more than the 2 h / 24 h harness windows — the R5 exit criterion is a **72-hour** continuous-use soak with flat memory.
6. QuestDB replay scans (`bars_time`, `footprint_cells`, `orderbook_deltas`, `trades`) are un-tuned.
7. Startup (budget #10, ≤3 s cold → interactive workspace) and workspace-restore have no harness at all.
8. Budgets are *documented* required checks but only B1–B10 are actually wired; the rest are not CI-enforced, and there are no regression alarms on the soft budgets.

E46 closes all eight, and leaves the budgets self-defending.

Plan references:
- `docs/plan/30-release-roadmap.md` §3 (epic register: E46, R5, `area/chart-engine`+`area/backend-platform`, all modules, domains CHART+OBS, 55 pts), §9.2–§9.4 (R5 scope, exit criteria 1, quality gate "Perf"), §12 dependency graph (E44 → E46, E45 → E46, E46 → E48).
- `docs/plan/06-performance-and-load-standard.md` — the authoritative budget list; every ticket in this epic cites a numbered budget.
- `docs/plan/26-chart-engine-design.md` §3.7 (SDF text), §3.8 (heatmap streaming), §7 (memory budgets), §11 (degradation), §13 (B1–B10 gates).
- `docs/plan/20-architecture.md` §12.1 (metrics), §12.3 (tracing), §13.2 (budget table).
- `docs/plan/11-user-stories.md` §5 CHART (US-CHART-001, US-CHART-006, US-CHART-010) and §28 OBS (US-OBS-001, US-OBS-002, US-OBS-005, US-OBS-006).
- `docs/plan/14-screens-catalogue.md` SCR-046 (engine diagnostics overlay), SCR-118 (data & performance settings), SCR-143 (admin system health), SCR-147 (exchange connectivity & rate limits).
- `docs/plan/03-testing-strategy.md` (k6/Locust/bench layers), `docs/plan/05-accessibility-standard.md` (degradation indicator must not be colour-only).

## Scope / Deliverables
**In scope**
- **Instrumentation**: per-stage frame markers matching `06-performance-and-load-standard.md` §4.3 exported from the engine benchmark harness and from the live app at 2 Hz (SCR-046); OpenTelemetry span breakdown for the §5.1 WS tick→screen stages; the `fe_frame_time_ms` / `fe_dropped_frames_total` / `fe_ws_decode_ms` / `fe_gpu_memory_mb` pushed metrics in `20-architecture.md` §12.1 actually populated.
- **Frontend optimisation**: footprint SDF text path (`packages/chart-engine/src/text`), heatmap texture streaming path (`packages/chart-engine/src/layers/heatmap`), MemoryGovernor tuning, LOD/degradation verification.
- **Backend optimisation**: book delta application (M-book), bar builders, order-flow aggregation, WS fan-out serialisation/binary framing (`docs/plan/23-ws-protocol.md` §3.4), per-symbol CPU and RSS.
- **Storage**: QuestDB query tuning for replay scans over `bars_time`, `footprint_cells`, `orderbook_deltas`, `orderbook_snapshots`, `trades`, `heatmap_cells`; `engine_metrics` write path.
- **Budgets in CI**: all hard budgets from §2 promoted to required checks with the §7.4 ≤5 % gate, baseline-forward-only policy, ≥3-run median, and soft-budget alerting with the 3-consecutive-alert escalation.
- **Screens**: SCR-046 diagnostics overlay completed with the full §4.3 stage table + WS→pixel latency (US-OBS-002 "compact latency indicator"); SCR-118 "Run benchmark" + "recommended for this machine" preset.
- **Soaks**: 72 h continuous-use soak, full-capacity composite scenario (10 symbols / 5 accounts / 5 users, §9 last row), ingestion 24 h soak re-run on the GA candidate.
- **ADR-0016** recording the budget-enforcement model and the baseline policy.

**Out of scope**
- Accessibility remediation (E47) beyond asserting that the degradation indicator remains non-colour-only.
- Defect burn-down and design-QA sweep (E49).
- Documentation/runbook authoring (E48) beyond the perf-incidents log and ADR-0016.
- Any new user-facing feature, new chart type, new indicator or new order type.
- Horizontal scale-out, multi-tenant or mobile capacity work (explicitly excluded by `06-performance-and-load-standard.md` §10.3).

## Acceptance criteria
```gherkin
Scenario: Every hard budget is CI-enforced
  Given the GA candidate build
  When the performance CI job runs
  Then every hard budget in docs/plan/06-performance-and-load-standard.md §2 has a named check that passes
  And a deliberate 6% regression injected into any one of them fails the build

Scenario: A regression is stage-attributable without re-profiling
  Given a frame-time regression is detected by the engine harness
  When the harness report is opened
  Then it names which of the nine §4.3 stages exceeded its slice, with p50/p95/p99 per stage

Scenario: 72-hour soak is flat
  Given the GA candidate runs a realistic 4-pane workspace for 72 hours against a live-shaped tick generator
  Then frontend RSS stays within the documented variance band with no monotonic growth
  And backend RSS stays at or under 300MB per recorded symbol
  And p95 frame time at the end of the window is within 5% of the value at hour one

Scenario: The full-capacity composite scenario passes
  Given 10 symbols, 5 accounts and 5 users with 20 concurrent pane subscriptions for a sustained 2 hours
  Then all pass criteria in docs/plan/06-performance-and-load-standard.md §9's composite row hold simultaneously
  And no backend process OOMs or restarts

Scenario: Degradation still tells the truth
  Given the worst-case stress scenario drives the engine into the §4.4 degradation ladder
  Then the frame rate never drops below 30fps
  And the "reduced live detail" indicator is present and is not conveyed by colour alone
  And no order-line or position-overlay update is dropped
```

## Technical notes / design
Method is fixed by `06-performance-and-load-standard.md` §8 and is not negotiable per ticket: reproduce deterministically on the seeded fixture → stage-attribute → deep-dive with the named tool (`Performance.mark` + Spector.js + React Profiler frontend; `py-spy` + `memray` + spans backend) → fix → re-run the exact harness → record before/after in the PR body. Every optimisation ticket in this epic must carry its harness numbers in the PR description; "should be faster now" is an automatic review rejection.

Baselines live in the repo (`bench/baselines/*.json`) and move forward only via a reviewed "update performance baseline" PR that includes the harness output and a rationale (§7.4).

## Test plan
See per-ticket plans. Epic-level: the five acceptance scenarios above are each owned by a QA ticket (E46-Q01..Q04) and are re-run on the GA candidate as part of `q11 GA regression + 72h soak` (`docs/plan/30-release-roadmap.md` §10, S25wk2–S26).

## Security notes
Performance telemetry is a data-exfiltration and DoS surface: the diagnostics overlay and the SCR-118 benchmark expose GPU/driver strings and timing side-channels; the metrics endpoint must stay bound to the private network (US-OBS-001 NFR) with bounded cardinality; profiling artefacts (`py-spy` dumps, `memray` captures, heap snapshots) can contain order and account data and must be treated as confidential and never attached to a public issue. Covered by E46-X01 (STRIDE) and E46-X02 (review + abuse cases + SAST rules).

## Accessibility notes
Two UI surfaces (SCR-046, SCR-118) ship in this epic and both are WCAG 2.2 AA by default (`docs/plan/02-definition-of-ready-done.md` §8: no "internal tool" exception). The degradation indicator's colour-independence rule (`docs/plan/05-accessibility-standard.md`, `06-…` §4.4) is an acceptance criterion, not a nice-to-have. Optimisation must never be bought by desyncing or thinning the DOM-mirror (§4.3 allocates it 1 ms and `26-chart-engine-design.md` §12 forbids desync).

## Performance notes
This epic *is* the performance notes. The binding numbers: frame ≤16.6 ms p95 / 30 fps floor; WS tick→screen p95 <100 ms, p99 <250 ms; backend-internal fan-out ≤20 ms p95; order submit→ack p95 <300 ms demo with ≤50 ms backend-added; ingestion zero undetected loss; FE ≤1.5 GB per workspace; BE ≤300 MB per symbol; bundle ≤8 MB gzipped; cold start ≤3 s; REST read p95 <150 ms, write p95 <300 ms; backend CPU ≤0.5 vCPU/symbol; storage ≤0.75 GB/day/symbol; heatmap 100 ms cadence; replay 100× no desync.

## Observability
New/updated: per-stage frame histograms pushed as `fe_frame_time_ms{stage}`; `fe_dropped_frames_total`; `fe_ws_decode_ms`; `fe_gpu_memory_mb`; `engine_process_seconds{engine}` extended to every order-flow engine; `ws_fanout_latency_seconds` asserted in CI; `questdb_write_seconds` and a new replay-scan query histogram; a Grafana "Performance budgets" dashboard panel per §2 budget with the CI baseline drawn as a threshold line; alert rules for sustained budget breach feeding the existing Alertmanager route.

## Definition of Done
- [ ] Every child ticket Done or explicitly descoped with a recorded disposition.
- [ ] All hard budgets CI-enforced as required checks; 6 % injected-regression test proves the gate bites.
- [ ] 72 h soak green; full-capacity composite scenario green on the GA candidate.
- [ ] ADR-0016 merged; `docs/plan/06-performance-and-load-standard.md` updated where measured reality differed from the planned number (with the divergence explained, not silently rewritten).
- [ ] Coverage held: ≥85 % on backend/engine packages, ≥80 % frontend.
- [ ] a11y: axe-core green on SCR-046 and SCR-118; manual screen-reader pass on both; degradation indicator verified non-colour-only.
- [ ] Security: STRIDE finalised, findings triaged, Security engineer sign-off.
- [ ] QA: epic-level regression + exploratory pass recorded.
- [ ] Demoed to Owner at Sprint Review with before/after numbers per optimisation ticket.
- [ ] Perf-incidents log seeded and referenced from `docs/plan/07-release-and-prr.md`.

## Dependencies
- **E44** (live gating & environment separation) — the `env` label is on every metric (`20-architecture.md` §12.1) and budgets are measured per environment; measuring before the environment axis is final would produce baselines that have to be thrown away.
- **E45** (reconciliation & chaos) — the chaos harness is reused for the degradation and failover-under-load scenarios; soaks must run on a build whose failure handling is already correct, otherwise soak failures are chaos bugs, not perf bugs.
- **E11/E12/E18/E21/E26** supply the engine, series, footprint, heatmap and replay code being optimised; **E04** supplies the metrics pipeline being extended.
- **E46 → E48**: GA documentation depends on the final measured numbers.

## Branch
`feat/e46-perf-*` per child ticket (e.g. `feat/e46-perf-footprint-text`). PR size: optimisation PRs must stay ≤400 LOC diff and carry before/after harness output; instrumentation and CI-wiring PRs may be larger but must be reviewable in one sitting.

## References
- `docs/plan/06-performance-and-load-standard.md` (all sections)
- `docs/plan/26-chart-engine-design.md` §3.7, §3.8, §7, §11, §13, §14
- `docs/plan/20-architecture.md` §4.2, §12, §13.2
- `docs/plan/30-release-roadmap.md` §9
- `docs/plan/03-testing-strategy.md`, `docs/plan/05-accessibility-standard.md`, `docs/plan/04-security-program.md`
- `docs/plan/14-screens-catalogue.md` SCR-046, SCR-118, SCR-143, SCR-147
- `docs/plan/21-database-schema.md` §4 (QuestDB tables, `engine_metrics`)

## Child dependency graph
```mermaid
graph TD
    D01[E46-D01 Diagnostics overlay design] --> S01[E46-S01 SCR-046 overlay + latency indicator]
    D02[E46-D02 Perf settings design + handoff] --> S02[E46-S02 SCR-118 benchmark + preset]
    K01[E46-K01 Spike: profiling toolchain] --> T01[E46-T01 Stage instrumentation]
    T01 --> T02[E46-T02 Footprint text optimisation]
    T01 --> T03[E46-T03 Heatmap upload tuning]
    T01 --> S01
    K01 --> T04[E46-T04 Backend hot-path profiling]
    T04 --> T05[E46-T05 Fan-out serialisation]
    T04 --> T07[E46-T07 Backend memory & CPU]
    T02 --> T06[E46-T06 Frontend memory-leak hunt]
    T03 --> T06
    T04 --> T08[E46-T08 QuestDB replay scan tuning]
    T01 --> T09[E46-T09 Startup & workspace-restore]
    T02 --> T10[E46-T10 CI budget enforcement]
    T05 --> T10
    T07 --> T10
    T08 --> T10
    T09 --> T10
    T10 --> T11[E46-T11 ADR-0016 + perf-incidents log]
    T10 --> Q02[E46-Q02 72h soak + capacity composite]
    T06 --> Q02
    Q01[E46-Q01 Perf test plan & regression pack] --> Q02
    Q01 --> Q03[E46-Q03 Exploratory + degradation charter]
    S01 --> Q03
    S02 --> Q03
    Q02 --> Q04[E46-Q04 QA sign-off & GA perf evidence pack]
    Q03 --> Q04
    X01[E46-X01 STRIDE threat model] --> X02[E46-X02 Security review & abuse cases]
    S01 --> X02
    X02 --> Q04
```
"""

tickets.append(T("E46", "Epic", "Performance hardening & budget enforcement",
    ["type/feature", "area/chart-engine", "area/backend-platform", "priority/p1",
     "perf", "qa", "security", "design", "a11y"],
    "cross-cutting", "Sprint 23", "P1 High", "Architecture", "R2 Render performance",
    77, None, ["E44", "E45", "E11", "E12", "E18", "E21", "E26", "E04"], epic_body))

# ---------------------------------------------------------------- DESIGN
tickets.append(T("E46-D01", "Task",
    "Design the completed engine diagnostics overlay and the compact latency indicator",
    ["design", "ux-research", "type/design", "area/chart-engine", "priority/p2", "perf"],
    "web", "Sprint 21", "P2 Medium", "Product", "R2 Render performance", 3, "E46",
    ["E11", "E04"],
    """## Context
SCR-046 (`docs/plan/14-screens-catalogue.md` §SCR-046) is specified as a developer/owner overlay on `Ctrl+Shift+D` showing FPS, frame time p50/p95, draw calls, GPU memory, buffer uploads/s, WS message rate, dropped frames and a "copy diagnostics" button. E46 extends it with the **nine-stage §4.3 breakdown** and the **WS→pixel latency figure** that US-OBS-002 requires ("a compact latency indicator is available in the UI showing the current end-to-end figure"). That is a materially different information density from the original sketch, so it needs a hi-fi pass before E46-S01 is built in S23 — this ticket lands in S21, two sprints ahead, satisfying the design-ahead rule (`docs/plan/00-planning-brief.md`, `docs/plan/02-definition-of-ready-done.md` §3.1).

## Scope / Deliverables
- **Light UX research** (half-day, Owner + chart-engine lead): how the overlay is actually used during a regression hunt — which numbers are read first, what gets copied into a ticket. Written up as 5–8 findings that justify the information hierarchy.
- **Wireframe → hi-fi (Figma)** of SCR-046 with: the nine §4.3 stages as rows (input, data-window, candle geometry, footprint text, heatmap upload, pane redraw, overlays, DOM-mirror, composite) each with its budget slice, current p50/p95 and an over/under-budget state word; the headline FPS + frame p50/p95/p99; draw calls; GPU memory estimate; buffer uploads/s; WS message rate; dropped frames; visible bars; visible footprint cell count; **WS→pixel end-to-end latency** (p95, per `docs/plan/06-performance-and-load-standard.md` §5.1) with the stage that currently dominates named; copy-diagnostics control.
- **The compact latency indicator** as a separate, always-available element (US-OBS-002 scenario 3) for the main chrome — not the full overlay — with its own states (within budget / breaching / no data) and its placement decided against `docs/plan/14-screens-catalogue.md` SCR-010 chrome.
- **States**: collecting (first 2 s, no percentiles yet), healthy, one-stage-over-budget, multi-stage-over-budget, degraded-mode-active (mirrors §4.4 ladder step), engine in `degraded-2d`, no-WebGL.
- **Design-system contribution**: a `BudgetRow` variant of CMP-036 KeyValueRow carrying value + unit + budget + state word, proposed for `docs/plan/15-component-catalogue.md`; reuse of CMP-024 Sparkline, CMP-069 InfoPanel, CMP-178 SystemHealthTile rather than one-offs.
- **Motion spec**: values update at 2 Hz (SCR-046's stated sampling rate) with no animation on numeric change (flicker is worse than no motion here); threshold crossings get a single 150 ms state-colour transition with a `prefers-reduced-motion` variant that is instant.

## Out of scope
- SCR-118 settings design (E46-D02).
- Admin SCR-143/SCR-147 redesign — those are E42's screens and are consumed, not changed.
- Building anything (E46-S01).

## Acceptance criteria
```gherkin
Scenario: Every §4.3 stage is drawn with its budget
  When the hi-fi frames are reviewed against docs/plan/06-performance-and-load-standard.md §4.3
  Then all nine stages appear as rows, each with its documented budget slice and a measured value
  And no stage is represented by colour alone — each carries a state word

Scenario: The latency indicator satisfies US-OBS-002
  When the compact indicator frames are reviewed
  Then a current end-to-end WS→pixel figure is shown with units
  And a breaching state names the stage consuming the budget

Scenario: The overlay costs nothing it does not need
  Then the spec states the 2 Hz sampling rate and the ≤0.5ms/frame self-cost from SCR-046
  And the design contains no per-frame-updating element
```

## Technical notes / design
Information hierarchy is: headline verdict (in/out of budget) → the one stage responsible → everything else. The overlay is a text panel, not a canvas (SCR-046 a11y note), so it is plain DOM and can be read as a static table when pinned. Values are polite live-region updates, never assertive.

## Test plan
N/A (design artefact). Validation is the sign-off checklist below plus E46-Q03's design-QA comparison after E46-S01 ships.

## Security notes
The copy-diagnostics payload is specified here: GPU vendor/renderer strings, driver version, timings, settings — and **no** symbol, account, order or user identifier. That exclusion list is part of the design spec because it is easier to enforce in the spec than to remove later; E46-X02 verifies it in code.

## Accessibility notes
Panel is DOM text with a heading; every number carries a unit and a state word; updates are `aria-live="polite"`; the overlay is dismissable with `Escape` and its trigger is documented in the hotkey cheatsheet (SCR-119); contrast of the over/under-budget state colours verified at 4.5:1 against panel background per `docs/plan/05-accessibility-standard.md`.

## Performance notes
Design constraint, not just measurement: ≤0.5 ms/frame self-cost, 2 Hz sampling (SCR-046). Any drawn element that would require per-frame DOM work is rejected at design review.

## Observability
Analytics events retained from SCR-046: `diagnostics.overlay_toggled`, `diagnostics.snapshot_copied`.

## Definition of Done
- [ ] Research write-up attached with findings numbered and traceable to hierarchy decisions.
- [ ] Hi-fi frames for all seven states in Figma, linked from the ticket.
- [ ] SCR-046 design sign-off acceptance checklist in `docs/plan/14-screens-catalogue.md` fully satisfied, item by item, in a comment.
- [ ] `BudgetRow` proposal filed against the design system with a CMP id requested.
- [ ] Motion + reduced-motion variants specified.
- [ ] CDO or delegate sign-off recorded; Status Done ≥2 sprints before E46-S01 starts.

## Dependencies
Needs E11's engine telemetry surface and E04's metric names to label rows with real metric ids.

## Branch
`design/e46-diagnostics-overlay` (Figma-linked; repo changes limited to the screens-catalogue entry update). PR size: small.

## References
`docs/plan/14-screens-catalogue.md` SCR-046, SCR-010, SCR-118, SCR-119 · `docs/plan/06-performance-and-load-standard.md` §4.3, §5.1 · `docs/plan/11-user-stories.md` US-OBS-002 · `docs/plan/15-component-catalogue.md` CMP-024, CMP-036, CMP-069, CMP-178 · `docs/plan/05-accessibility-standard.md`
"""))

tickets.append(T("E46-D02", "Task",
    "Design SCR-118 benchmark flow, recommended preset, degradation indicator and handoff",
    ["design", "handoff", "design-qa", "a11y", "type/design", "area/chart-engine", "priority/p2"],
    "web", "Sprint 21", "P2 Medium", "Product", "R2 Render performance", 3, "E46",
    ["E46-D01"],
    """## Context
SCR-118 "Data & performance settings" (`docs/plan/14-screens-catalogue.md`) already specifies renderer choice, FPS cap, max bars in memory, heatmap trail ceiling, book depth default, coalescing, cache size and a **Run benchmark** action with a pass/fail against the minimum target and a "recommended for this machine" preset. E46 makes that real: the benchmark is the engine harness from `docs/plan/06-performance-and-load-standard.md` §7.1 run in-app on a synthetic footprint+heatmap scene, and the preset is derived from its result. This ticket produces the hi-fi for that flow, plus the **degradation indicator** that `06-…` §4.4 / `05-accessibility-standard.md` require whenever the engine sheds update frequency, plus the a11y review and the engineering handoff for the whole epic's UI surface.

## Scope / Deliverables
- **Hi-fi SCR-118** covering: idle, benchmark-running (progress + "this takes about 40 seconds, the chart will be busy"), results (per-scenario pass/fail against budget with measured numbers), results-below-target (what to change, with the specific controls highlighted), GPU-blacklisted, and reset-to-recommended.
- **"Recommended for this machine" preset**: how the derived values are presented (before → after diff table), what requires a panel rebuild (stated before applying, per the screen's performance note), and the confirm step.
- **Degradation indicator** hi-fi: the non-colour-only "reduced live detail" affordance for each of the four §4.4 ladder steps (heatmap cadence relaxed · footprint text LOD · pane redraw coalescing · background-pane detail capped), where it appears (pane badge + chrome), its accessible announcement text, and how the user returns to full detail. Reuses CMP-092 DegradedModeBanner and proposes the pane-level variant.
- **Accessibility design review** of SCR-046 + SCR-118 against `docs/plan/05-accessibility-standard.md`: focus order, grouped numeric controls with units and measured current values beside each target, live-region politeness (polite everywhere; the degradation indicator is polite too — it is informational, not an error), keyboard reachability of Run benchmark and Reset.
- **Engineering handoff package**: annotated frames, token map, frame-element → CMP-nnn prop mapping table, the benchmark state machine, and a recorded walkthrough with the implementing frontend engineers.

## Out of scope
- Implementing the benchmark (E46-S02) or the overlay (E46-S01).
- Changing the degradation *policy* — the ladder is fixed by `06-…` §4.4; this designs its expression only.
- Theme/contrast work for E47.

## Acceptance criteria
```gherkin
Scenario: Degradation is never colour-only
  When the four degradation-ladder states are reviewed
  Then each carries text and a shape/icon affordance in addition to any colour
  And each has a written screen-reader announcement string

Scenario: The benchmark tells the user what to do about a failure
  Given the benchmark result is below the minimum target
  Then the results frame names which budget failed, by how much, and which SCR-118 controls would help

Scenario: Handoff leaves no open question
  When the frontend engineers complete the walkthrough
  Then every frame element maps to a CMP-nnn prop in the mapping table
  And any unmapped element has a filed design-system ticket
```

## Technical notes / design
The benchmark must be interruptible and must state that the chart is unusable while it runs; the results are persisted for support (SCR-118 analytics note `performance.setting_changed` plus a diagnostics record). The preset diff is a table, not prose, so a user can see exactly what is about to change.

## Test plan
N/A (design artefact); verified by E46-Q03's design-QA pass and the axe-core run in E46-S02.

## Security notes
The stored benchmark result is support data: it may contain GPU/driver strings. The spec states it is stored locally and only leaves the machine via an explicit user action (consistent with US-OBS-007's "never uploaded automatically").

## Accessibility notes
This ticket *is* the a11y review for the epic's UI. Deliverables include focus-order diagrams for both screens and the announcement strings for benchmark start/finish and every degradation step.

## Performance notes
SCR-118 governs the performance budget itself; the design must show measured current value beside each target ("Chart FPS cap: 60. Measured: 59.") so the screen is self-evidencing.

## Observability
`performance.setting_changed {key, before, after}`; `benchmark.run_started` / `benchmark.run_completed {scenario, p95_ms, verdict}` proposed as analytics events.

## Definition of Done
- [ ] Hi-fi frames for every listed state, linked.
- [ ] SCR-118 design sign-off acceptance checklist satisfied item by item in a comment.
- [ ] Degradation indicator variants specified for all four ladder steps with announcement strings.
- [ ] a11y review written up; focus order diagrams attached.
- [ ] Handoff walkthrough held and recorded; mapping table complete.
- [ ] CDO or delegate sign-off; Status Done ≥2 sprints before E46-S02.

## Dependencies
Follows E46-D01 so the two surfaces share one visual language for budget/measured pairs.

## Branch
`design/e46-perf-settings`. PR size: small.

## References
`docs/plan/14-screens-catalogue.md` SCR-118, SCR-046, SCR-047 · `docs/plan/06-performance-and-load-standard.md` §4.4, §7.1 · `docs/plan/05-accessibility-standard.md` · `docs/plan/15-component-catalogue.md` CMP-004, CMP-010, CMP-036, CMP-065, CMP-086, CMP-092, CMP-178 · `docs/plan/26-chart-engine-design.md` §11
"""))

# ---------------------------------------------------------------- SPIKE
tickets.append(T("E46-K01", "Spike",
    "Spike: choose and prove the profiling toolchain for the R5 optimisation pass",
    ["type/spike", "perf", "area/chart-engine", "area/backend-platform", "priority/p1"],
    "cross-cutting", "Sprint 23", "P1 High", "Architecture", "R2 Render performance", 3, "E46",
    ["E44", "E45"],
    """## Context
`docs/plan/06-performance-and-load-standard.md` §8 names the tools (Chrome DevTools + `Performance.mark` correlation, Spector.js, React DevTools Profiler, `py-spy`, `memray`, OpenTelemetry spans) but nobody has yet proven that they work *together* on this stack — specifically: that `Performance.mark` data survives the OffscreenCanvas/worker boundary (`docs/plan/26-chart-engine-design.md` §6), that Spector.js can capture a worker-owned WebGL2 context, that `py-spy` is safe to attach to the asyncio supervisor described in `docs/plan/20-architecture.md` §4.1 without stalling ingestion, and that `memray` can run for the 72 h soak window without its own output becoming the disk problem. Getting this wrong wastes the whole S23–S25 optimisation window, so it is a timeboxed spike before any optimisation ticket starts.

## Scope / Deliverables
- Timebox: **3 days**, one frontend + one backend engineer.
- Answer, with recorded evidence: (1) Can per-stage `Performance.mark`/`measure` spans be emitted from the render worker and correlated with main-thread marks into one timeline? (2) Can Spector.js (or an equivalent) capture the worker context, and if not what is the fallback for GPU-side attribution of heatmap upload and footprint text draws? (3) Is `py-spy --nonblocking` overhead on the ingestion supervisor within the ≤1 % CPU measurement-overhead NFR of US-OBS-002? (4) Can `memray` run in a 72 h soak with bounded output, or is periodic sampling required? (5) Does backend span-id propagation into the WS envelope (`docs/plan/06-…` §7.2's stated architecture requirement, `docs/plan/23-ws-protocol.md` §3.1 envelope) already exist, and if not what is the minimal shape?
- Output: a comparison table, a throwaway prototype branch, and a written recommendation.
- **ADR**: findings recorded as an ADR entry (even "defer" is an ADR per `docs/plan/02-definition-of-ready-done.md` §5.2) — folded into ADR-0016 authored in E46-T11 if the decision is straightforward, or its own ADR if the toolchain choice is contested.

## Out of scope
Any production-shippable code — this spike is explicitly throwaway except for the instrumentation shape it recommends, which E46-T01 implements properly.

## Acceptance criteria
```gherkin
Scenario: Every question is answered with evidence
  When the spike closes
  Then each of the five questions has a recorded answer with a number, a screenshot or a trace file

Scenario: Overhead is quantified, not assumed
  Given py-spy is attached to the ingestion supervisor under the 10-symbol capacity load
  Then the measured CPU overhead is recorded and compared against the 1% NFR in US-OBS-002

Scenario: A negative result still decides something
  Given Spector.js cannot capture the worker context
  Then the recommendation names the concrete fallback for GPU-side attribution and files the follow-up ticket
```

## Technical notes / design
Worker-boundary correlation is the crux: `26-chart-engine-design.md` §6 puts the render loop in a worker with OffscreenCanvas, so main-thread-only profiling sees an opaque box. The likely shape is a shared monotonic clock origin (`performance.timeOrigin` reconciliation) plus structured stage records posted to the main thread on the existing stats channel at 2 Hz, rather than per-frame postMessage traffic — which is also what SCR-046 needs, so the spike deliberately prototypes the thing the product needs anyway.

## Test plan
Prototype measurements on the seeded benchmark fixture from `packages/fixtures`; backend measurements against the recorded Bybit fixture used by the ingestion soak harness. No CI wiring in this ticket.

## Security notes
Profiling captures can embed order/account data; the spike must state where captures are written, that the path is gitignored, and that captures are never attached to issues. Feeds E46-X01's STRIDE.

## Accessibility notes
N/A — no UI surface.

## Performance notes
The measurement apparatus must itself cost ≤1 % CPU (US-OBS-002 NFR) and ≤0.5 ms/frame for the in-app 2 Hz sampling (SCR-046).

## Observability
Recommends the concrete span/mark naming scheme that E46-T01 implements, aligned to the metric names in `docs/plan/20-architecture.md` §12.1.

## Definition of Done
- [ ] Five questions answered with recorded evidence.
- [ ] Comparison table + recommendation written in the ticket.
- [ ] ADR entry filed (own ADR or folded into ADR-0016 with the decision text drafted here).
- [ ] Follow-up tickets filed/updated (at minimum E46-T01's scope adjusted to the recommendation).
- [ ] Prototype branch left unmerged and marked throwaway.
- [ ] `docs/plan/32-risk-register.md` updated if a new risk surfaced (R1/R2 entries for chart-engine perf already exist and should be re-scored).
- [ ] Findings presented at Sprint Review.

## Dependencies
Runs on a post-E44/E45 build so the environment axis and failure handling are final.

## Branch
`spike/e46-profiling-toolchain`. Unmerged.

## References
`docs/plan/06-performance-and-load-standard.md` §7.2, §8 · `docs/plan/26-chart-engine-design.md` §6, §13 · `docs/plan/20-architecture.md` §4.1, §12.3 · `docs/plan/23-ws-protocol.md` §3.1 · `docs/plan/11-user-stories.md` US-OBS-002
"""))

json.dump(tickets, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(len(tickets), "written (part 1)")
