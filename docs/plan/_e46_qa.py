# -*- coding: utf-8 -*-
"""E46 part 5: QA tickets."""
from _e46_lib import T

tickets = []

tickets.append(T("E46-Q01", "Task",
    "Write the E46 performance test plan, harness scripts and regression pack",
    ["type/test", "qa", "perf", "area/chart-engine", "area/backend-platform", "priority/p1"],
    "cross-cutting", "Sprint 23", "P1 High", "Test", "R2 Render performance", 5, "E46",
    ["E46-K01", "E45", "E03"],
    """## Context
`docs/plan/03-testing-strategy.md` puts load/performance in its own pyramid layer (k6/Locust for API and WS fan-out, engine FPS benchmarks, ingestion soak) and `docs/plan/06-performance-and-load-standard.md` §7 defines the harness, §9 the consolidated load scenarios and §9's table the pass criteria. What does not exist is a single executable statement of *how E46 is verified*: the scenarios are spread across a standard document, the engine gates B1–B10 live in `docs/plan/26-chart-engine-design.md` §13, and the chaos scenarios belong to E45's harness. An epic whose entire deliverable is "the numbers are true and stay true" cannot be signed off from three separate documents and a verbal understanding.

This ticket is the QA foundation of the epic and is deliberately sequenced first (Sprint 23, alongside the instrumentation tasks): every optimisation ticket (T02, T03, T05, T07, T08, T09) must prove itself against scripts that already exist and are already agreed, otherwise each engineer invents their own measurement and the before/after numbers in their PRs are not comparable to each other or to CI.

## Scope / Deliverables
- **Black-box performance test plan** covering the two story groups of this epic (SCR-046 diagnostics / SCR-118 benchmark) and the ten optimisation and enforcement tasks, with one numbered test case per budget in `06-performance-and-load-standard.md` §2 — 15 budgets, 15 cases, each stating: preconditions, load scenario (§3.2 nominal / realistic-peak / worst-case), measurement method, pass criterion, and which ticket owns a failure.
- **k6 scripts** (`tests/load/`) for budget #13 (REST read p95 <150 ms, write p95 <300 ms) and for the WS fan-out path of budget #6, parameterised by the §3.2 load scenarios, driven against the staging backend.
- **Locust scenario** for the §9 "Full capacity" composite row: 10 symbols, 5 accounts, 5 users, 20 concurrent pane subscriptions, sustained — the scenario E46-Q02 executes.
- **Engine benchmark regression pack**: a runner that executes B1–B10 from `docs/plan/26-chart-engine-design.md` §13 plus the §4.3 stage-attribution report from E46-T01, ≥3 runs with the median taken (per §7.4), emitting the versioned JSON report that E46-T10's CI gate consumes.
- **Ingestion soak script** re-usable for the 24 h budget-#5 zero-loss run, driven from recorded Bybit fixtures (no live exchange dependency in CI).
- **Seeded, deterministic fixtures**: a named fixture set in `packages/fixtures` (recorded Bybit tick/book data for a volatile symbol-day plus a quiet symbol-day), pinned by hash, so "reproduce deterministically" (the profiling playbook's §8 step 1) is a real instruction and not a hope.
- **Injected-regression test**: a deliberate, parameterised slowdown harness (the mechanism E46-T10's "6 % regression fails the build" acceptance criterion and E46-T01's stage-attribution criterion both rely on) so the gates can be proven to bite rather than assumed to.
- **Traceability table** mapping each of the 15 budgets → test case id → owning ticket → CI job, added to the test plan, so E46-Q04's sign-off is a checklist rather than a judgement call.
- **Test-data and environment notes**: reference hardware per §3.1, what CI's runner differs by, and the explicit rule that CI-runner numbers are compared against CI-runner baselines only (never against the reference-hardware figures).

## Out of scope
- Executing the long-running soaks (E46-Q02) and the exploratory charter (E46-Q03).
- Wiring the gates into CI as required checks (E46-T10) — this ticket produces the scripts, T10 makes them blocking.
- Chaos/failover scenario authoring — owned by E45; this plan *references* E45's harness for the degradation-under-failure cases rather than duplicating it.
- a11y auditing of SCR-046/SCR-118 (covered by E46-Q03's audit step and by E47 for the standing audit).
- Security testing (E46-X02).

## Acceptance criteria
```gherkin
Scenario: Every budget has exactly one owning test case
  Given the E46 performance test plan
  Then each of the 15 budgets in docs/plan/06-performance-and-load-standard.md §2 maps to exactly one numbered test case
  And each case names its load scenario, measurement method, pass criterion and owning ticket
  And no budget is unmapped and no case maps to two budgets

Scenario: The scripts run unattended and deterministically
  Given the fixture set pinned by hash
  When the engine regression pack is run twice on the same commit and the same machine
  Then the median p95 frame time of the two runs differs by less than 3%
  And both runs emit a schema-valid report

Scenario: The injected-regression harness proves a gate bites
  Given a 6% slowdown is injected into the footprint text stage
  When the regression pack runs
  Then the report fails, and it names footprint_text as the failing stage

Scenario: The k6 REST script measures the right thing
  Given the k6 read-endpoint script runs against staging at realistic-peak load
  Then it reports p95 for each endpoint class separately
  And it excludes exchange round-trip time from the write-endpoint measurement, per budget #13's definition

Scenario: A flaky measurement is caught, not averaged away
  Given one of three runs differs from the median by more than 20%
  Then the pack reports the run-to-run variance and marks the result low-confidence rather than silently reporting the median
```

## Technical notes / design
Median-of-≥3 with reported variance is mandated by §7.4; a single run is never a result. The pack reports p50/p95/p99 *and* the spread, because a stable-but-slow number and an unstable-but-fast-on-average number need different responses.

The injected-regression harness is a test-only wrapper that inserts a calibrated busy-wait into a named stage; it lives behind a build flag that cannot be set in a release build, and there is a test asserting the flag is absent from the production bundle — a deliberate slowdown mechanism shipping to users would be an own goal.

Fixture pinning: fixtures are content-addressed and the hash is asserted at the start of every run; a fixture change that is not accompanied by a deliberate baseline reset is a hard error, because it silently invalidates every stored baseline.

CI-runner variance is expected to exceed reference-hardware variance; the plan states the CI tolerance band explicitly and E46-T10 uses that band, not a number copied from §2.

## Test plan
Meta: the scripts themselves are tested — each k6/Locust script has a smoke mode asserting it produces a schema-valid report against a stub; the regression pack has a self-test running against a fixed synthetic engine stub with known timings and asserting the reported percentiles match the known values.

## Security notes
Load scripts hold demo-environment credentials only; they must read them from the environment, never from a committed file, and the repo's secret scanning covers `tests/load/`. Fixtures are recorded market data (public) — but any fixture recorded from an authenticated stream must be scrubbed of account identifiers before committing, and the plan states that rule. Load scripts must never be pointable at the live environment: the target base URL is validated against an allow-list that excludes live, per the environment separation established in E44.

## Accessibility notes
N/A for the scripts themselves. The plan includes the a11y test cases for SCR-046 and SCR-118 by reference to E46-S01/S02 rather than restating them.

## Performance notes
The harness overhead must be accounted for and stated, not ignored: the plan records the measured cost of instrumentation (from E46-T01) so that a "pass" is understood as pass-with-instrumentation, and states that release builds strip it.

## Observability
Regression-pack reports are archived as CI artefacts with commit, runner, GPU string and fixture hash, so any historical number can be re-explained months later. Baseline files live in `bench/baselines/`.

## Definition of Done
- [ ] All five Gherkin scenarios verified.
- [ ] Test plan merged under `docs/plan/` or `tests/` with the 15-budget traceability table complete.
- [ ] k6, Locust, engine regression pack, ingestion soak and injected-regression harness all runnable by a single documented command each.
- [ ] Fixture set committed, hash-pinned and documented.
- [ ] Self-tests for the scripts green in CI.
- [ ] Handover walkthrough with the engineers owning T02/T03/T05/T07/T08/T09 so every optimisation PR uses these scripts.
- [ ] Reviewed by the Architect and one backend + one frontend lead.

## Dependencies
- **E46-K01** — the toolchain decision determines what the pack measures and how.
- **E45** — chaos harness reused for degradation-under-failure cases.
- **E03** (or whichever epic owns the CI/test infrastructure) for the runner and artefact storage.

## Branch
`chore/e46-perf-test-plan`. PR size: plan doc and scripts in separate PRs.

## References
`docs/plan/03-testing-strategy.md` · `docs/plan/06-performance-and-load-standard.md` §2, §3.1, §3.2, §7, §8, §9 · `docs/plan/26-chart-engine-design.md` §13 · `docs/plan/02-definition-of-ready-done.md` §3.2, §4.2 · `docs/plan/11-user-stories.md` US-OBS-002, US-OBS-006
"""))

tickets.append(T("E46-Q02", "Task",
    "Execute the 72-hour soak and the full-capacity composite load scenario on the GA candidate",
    ["type/test", "qa", "perf", "area/chart-engine", "area/backend-platform", "priority/p0"],
    "cross-cutting", "Sprint 25", "P0 Critical", "Test", "R3 Real-time cost", 8, "E46",
    ["E46-Q01", "E46-T06", "E46-T07", "E46-T10"],
    """## Context
`docs/plan/30-release-roadmap.md` §9.3 makes a **72-hour continuous-use soak with flat memory** an explicit R5 exit criterion, and `docs/plan/06-performance-and-load-standard.md` §9's consolidated scenario table ends with a composite row — 10 symbols, 5 accounts, 5 users, 20 concurrent pane subscriptions, sustained — whose pass criteria must all hold *simultaneously*. Neither has ever been run: the existing harness windows are 2 h (frontend memory, budget #7) and 24 h (ingestion, budget #5).

This is the ticket where the epic's claims meet reality. Every optimisation in E46 is validated in a short window against a seeded fixture; a 72-hour run against a live-shaped generator is the only thing that catches the failure modes that matter most in a trading terminal — slow leaks, fragmentation, texture-atlas growth, unbounded caches, ring buffers that wrap wrong on day three, a QuestDB partition rollover that stalls, a reconnect path that leaks a subscription each time.

It is P0 because a GA that has never been left running over a weekend is not a GA for a tool whose user leaves it running over the weekend.

## Scope / Deliverables
- **72 h continuous-use soak**: a realistic 4-pane workspace (candles + footprint + heatmap + CVD) on the GA candidate build, driven by a live-shaped tick generator (or a long-loop replay of recorded fixtures with timestamps rebased so the app sees continuous live-shaped data, not a loop boundary every hour), with periodic realistic user interaction (pan, zoom, symbol switch, layout switch, replay session, order-ticket open/close on demo) scripted so the run exercises more than an idle window.
- **Sampling regime**: frontend RSS and GPU memory, backend RSS per symbol, JS heap, `fe_frame_time_ms{stage}` p50/p95, `fe_dropped_frames_total`, `ws_fanout_latency_seconds`, `event_loop_lag_seconds`, QuestDB on-disk growth, open file descriptors and socket counts — sampled at a fixed interval for the whole window, archived as a CI/release artefact.
- **Full-capacity composite scenario**: the §9 composite row executed for a sustained 2 h via E46-Q01's Locust scenario, with *all* its pass criteria asserted simultaneously (frame budget, WS→screen latency, backend fan-out, REST latency, per-symbol CPU and RSS, zero ingestion loss).
- **Ingestion 24 h soak re-run** on the GA candidate for budget #5 (zero undetected loss), since the earlier run predates E46's backend changes.
- **Replay soak** at 100× on a recorded 24 h symbol-day for budget #15 (crash-free, no desync).
- **Analysis and verdict**: a written report per run — leak verdict (monotonic growth vs bounded variance, with the statistical test used stated, not eyeballed from a graph), budget-by-budget pass/fail, and for any failure a filed Bug with the profiling artefacts attached and an owning ticket.
- **Restart-free assertion**: no backend process OOM, crash or supervisor restart during any window; the run is invalidated (not silently restarted) if one occurs.

## Out of scope
- Fixing what the soak finds — failures are filed as Bugs against E46-T06 (frontend memory) / E46-T07 (backend memory & CPU) / the owning epic, and re-run; this ticket executes and adjudicates.
- Chaos injection during the soak — E45 owns failure drills; the soak is a *steady-state* test and deliberately keeps its variables few. A separate short chaos-under-load pass is E46-Q03's charter.
- Live-environment execution — soaks run against demo/staging per the environment separation from E44.

## Acceptance criteria
```gherkin
Scenario: Frontend memory is flat over 72 hours
  Given the GA candidate runs the scripted 4-pane workspace for 72 hours
  Then resident memory stays within the documented variance band with no monotonic upward trend
  And it never exceeds the 1.5GB ceiling of budget #7
  And GPU memory at hour 72 is within the same band as at hour 2

Scenario: Frame time has not drifted
  Given the same 72-hour run
  Then p95 frame time measured in the final hour is within 5% of the value measured in the first full hour
  And no stage from the §4.3 breakdown has grown beyond its slice over the window

Scenario: Backend is flat and within budget
  Given the same window with 10 recorded symbols
  Then backend RSS per symbol stays at or below 300MB (budget #8)
  And per-symbol CPU stays at or below 0.5 vCPU sustained (budget #11)
  And no process OOMs, crashes or is restarted by the supervisor

Scenario: The composite capacity scenario passes as a whole
  Given 10 symbols, 5 accounts, 5 users and 20 concurrent pane subscriptions sustained for 2 hours
  Then every pass criterion in the composite row of docs/plan/06-performance-and-load-standard.md §9 holds simultaneously
  And a failure of any single criterion fails the scenario, even if the others pass

Scenario: Ingestion loses nothing in 24 hours
  Given the ingestion soak runs for 24 hours per symbol on the GA candidate
  Then the message-loss counter is zero
  And every detected gap has a corresponding recorded gap entry

Scenario: A leak is caught rather than explained away
  Given resident memory grows by a sustained amount across the window
  Then the run is failed
  And a heap or allocation capture is taken at the point of growth and attached to a filed Bug
  And the run is not marked pass on the grounds that the ceiling was never reached

Scenario: Replay at 100x survives
  Given a recorded 24-hour symbol-day is replayed at 100x
  Then playback completes without crash and without desync between panes
  And the 30fps floor is never breached
```

## Technical notes / design
"Flat" needs a definition, or it becomes an argument: the verdict uses a linear regression over the RSS samples of the final 48 h, and fails if the fitted slope implies growth beyond the documented variance band extrapolated over a further week. Sawtooth from GC is expected and is not growth; the regression is run on the post-GC minima envelope, not the raw samples. State the method in the report.

The tick generator must be live-shaped, not uniform: bursts, quiet periods and at least one synthetic volatility event per 24 h (5× message rate for 60 s, per §3.2's worst-case definition), otherwise the soak measures an unrealistically kind workload.

Loop-boundary artefacts are the classic false negative and false positive of long soaks: if replay looping is used, timestamps are rebased and continuity is asserted, and any metric discontinuity at a loop boundary invalidates the window.

Run scheduling: the 72 h window must be started early enough in Sprint 25 to allow one full re-run after a failure. Plan for two windows, not one; a single 72 h run late in the sprint is a plan with no failure budget.

## Test plan
This ticket *is* a test execution. Its own correctness controls: the sampling agent is verified against a process with a known synthetic leak before the real run (proving the harness detects growth); the composite scenario is smoke-run for 10 minutes before the 2 h execution; artefact archival is verified before the long window starts, so a 72 h run is never lost to a full disk or an unwritten artefact path.

## Security notes
Soak artefacts (heap snapshots, `memray` captures, `py-spy` dumps, log bundles) may contain order, account and symbol data from the demo environment and are classified Confidential per `docs/plan/04-security-program.md`; they are stored in the release artefact store with access control, never attached to a public issue, and are subject to a stated retention. Demo credentials used by the driver come from the environment. The run must not be pointed at live (E44 environment separation; the target allow-list from E46-Q01 applies).

## Accessibility notes
N/A — no UI surface introduced. The scripted interaction should include at least one keyboard-driven navigation cycle so that the keyboard path is exercised under sustained load too.

## Performance notes
Budgets asserted: #1, #2, #3, #5, #6, #7, #8, #11, #13, #14, #15. This ticket is the single largest evidence producer for E46-Q04's sign-off pack and for the R5 exit criterion in `docs/plan/30-release-roadmap.md` §9.3.

## Observability
The run exercises and validates the whole metric surface added by E46-T01 and E46-T04; any metric that turns out to be missing, wrong or unbounded in cardinality over a 72 h window is itself a finding and is filed.

## Definition of Done
- [ ] All seven Gherkin scenarios adjudicated with archived evidence.
- [ ] 72 h soak report, composite scenario report, ingestion soak report and replay soak report written, reviewed and attached to the release artefacts.
- [ ] Leak verdict states its statistical method and its variance band.
- [ ] Every failure filed as a Bug with owner, priority and profiling artefacts; re-run performed after fixes.
- [ ] Harness self-verification (synthetic leak detected) recorded before the real run.
- [ ] Results reconciled with `docs/plan/06-performance-and-load-standard.md` — any measured divergence from a planned number is raised for E46-T11's doc update rather than quietly ignored.
- [ ] Sign-off comment from QA lead; results presented to the Owner.

## Dependencies
- **E46-Q01** supplies the scenarios, scripts and fixtures.
- **E46-T06** and **E46-T07** must land first — soaking a build with known unfixed leaks wastes a 72 h window.
- **E46-T10** must be in place so the soak runs on a build whose short-window budgets already pass; a soak is not the place to discover a 16 ms frame budget failure.

## Branch
`chore/e46-soak-execution` for any harness fixes; the execution itself produces artefacts and reports, not code.

## References
`docs/plan/30-release-roadmap.md` §9.3 (R5 exit criteria), §10 · `docs/plan/06-performance-and-load-standard.md` §2, §3.2, §9, §10 · `docs/plan/03-testing-strategy.md` · `docs/plan/11-user-stories.md` US-OBS-002, US-OBS-006, US-REC-004 · `docs/plan/21-database-schema.md` §4 · `docs/plan/04-security-program.md`
"""))

tickets.append(T("E46-Q03", "Task",
    "Run the exploratory performance charter, degradation-ladder verification and a11y audit of SCR-046/SCR-118",
    ["type/test", "qa", "perf", "a11y", "area/chart-engine", "priority/p2"],
    "cross-cutting", "Sprint 25", "P2 Medium", "Test", "R2 Render performance", 5, "E46",
    ["E46-Q01", "E46-S01", "E46-S02"],
    """## Context
Scripted load tests measure what someone thought to measure. `docs/plan/03-testing-strategy.md` pairs them with exploratory testing for exactly that reason, and the performance failures that actually reach users are usually the ones no script models: switching layouts twenty times in a minute, dragging a drawing while replay runs at 50×, opening the DOM heatmap on five symbols and then minimising the window, a monitor hot-unplug, a laptop suspend/resume, an Electron window moved between a high-DPI and a low-DPI display.

This ticket also owns two things that are performance-adjacent but user-facing: proving the `docs/plan/06-performance-and-load-standard.md` §4.4 **degradation ladder** behaves as documented — including the non-negotiable rules that frames never drop below 30 fps, that trading-critical overlays are *never* shed, and that the "reduced live detail" indicator is not colour-only — and auditing the two screens this epic ships (SCR-046, SCR-118) against WCAG 2.2 AA.

## Scope / Deliverables
- **Exploratory charters** (time-boxed, session-based, each with a written debrief): (1) *layout and window churn* — rapid layout/workspace switching, floating-window creation and destruction, monitor changes, DPI changes, minimise/restore, suspend/resume; (2) *interaction under load* — drawing, crosshair, order-ticket use while at realistic-peak load and during replay at high speed; (3) *the long tail of symbols* — switching symbols rapidly, subscribing/unsubscribing, symbols with sparse history, a symbol with extreme footprint density; (4) *recovery* — behaviour after WebGL context loss, after backend restart, after a network drop over Tailscale, each while under load; (5) *settings extremes* — every SCR-118 control at both ends of its range, including combinations the recommended presets never produce.
- **Degradation-ladder verification**: drive the engine into each of the four §4.4 rungs deliberately, in order, and assert documented behaviour at each — heatmap cadence relaxing toward 250 ms, footprint text LOD hiding, redraw coalescing, and the focused-pane-only fallback — plus the three "never acceptable" invariants (no sub-30 fps, no dropped order-line/position overlay updates, no DOM-mirror desync).
- **Chaos-under-load pass**: reuse E45's chaos harness for WS disconnect, exchange 5xx and rate-limit 10018 *while at realistic-peak load*, verifying that failure handling does not itself blow the frame or latency budget (E45 proves correctness; this proves correctness-under-load).
- **a11y audit** of SCR-046 and SCR-118: axe-core automated pass, manual screen-reader passes (one Windows/NVDA, one macOS/VoiceOver if available, otherwise one screen reader with the deviation recorded), keyboard-only traversal, focus order and visible focus, contrast verification of every tone used for budget states, and specific verification that no performance state is communicated by colour alone anywhere in the epic's surface.
- **Findings**: every finding filed as a Bug with a reproduction, a severity and an owner; the charters' debriefs retained as release artefacts.

## Out of scope
- The long soaks and the composite capacity scenario (E46-Q02).
- The standing, product-wide a11y audit and remediation (E47) — this ticket audits only the two screens E46 ships.
- Authoring chaos scenarios (E45 owns them).
- Security abuse cases (E46-X02).

## Acceptance criteria
```gherkin
Scenario: Every charter is executed and debriefed
  Given the five exploratory charters
  Then each has a time-boxed session with a written debrief listing what was covered, what was found and what was not reached
  And every finding is filed with a reproduction and a severity

Scenario: The degradation ladder engages in the documented order
  Given load is increased progressively toward the worst-case scenario of §3.2
  Then heatmap cadence relaxes first, then footprint text LOD engages, then redraw coalescing, then the focused-pane-only fallback
  And no later rung engages before an earlier one

Scenario: The floor holds
  Given the worst-case stress scenario including a 5x message-rate burst
  Then the frame rate never drops below 30fps
  And no order-line or position-overlay update is dropped at any rung
  And the DOM-mirror never desyncs from what is rendered

Scenario: Degradation is announced non-visually
  Given the focused-pane-only fallback has engaged
  Then a "reduced live detail" indicator is present
  And it is conveyed by text, not by colour alone
  And a screen reader announces the state change politely

Scenario: Failure handling does not break the budget
  Given the market WS is dropped while the system is at realistic-peak load
  Then reconnection, resubscription and book resync complete per US-OBS-006
  And during recovery the frame rate stays above the 30fps floor
  And WS-to-screen latency returns within budget #3 once resync completes

Scenario: Both new screens pass the a11y audit
  Given SCR-046 and SCR-118 on the GA candidate
  Then axe-core reports no violations
  And every control is reachable and operable by keyboard alone
  And a manual screen-reader pass confirms labels, units, measured values and state changes are announced
  And all contrast ratios meet WCAG 2.2 AA

Scenario: A found defect is not lost
  Given an exploratory session finds an intermittent stutter that cannot be reproduced on demand
  Then it is filed with the captured diagnostics snapshot and the conditions observed
  And it is triaged rather than closed as unreproducible without investigation
```

## Technical notes / design
Session-based test management: each charter gets a stated mission, a time box (90 minutes), a tester, and a debrief covering coverage / findings / obstacles / next session. Charters are not scripts — a step-by-step charter is a test case that has been mislabelled.

Driving the degradation ladder deliberately needs a hook: use the SCR-118 controls plus a synthetic load injector to raise pane count, depth and message rate independently, so each rung can be reached in isolation rather than only under an avalanche where the order is unobservable.

The copy-diagnostics snapshot from SCR-046 (E46-S01) is the standard attachment for every finding filed by this ticket — that is what it was built for, and using it here validates it.

Intermittent findings are the norm in performance exploratory work. The rule is: captured and triaged, never dismissed. A finding with a diagnostics snapshot and stated conditions is actionable even without a deterministic repro.

## Test plan
This ticket is test execution. Evidence: five debriefs, one degradation-verification report with a table of rung → observed behaviour → verdict, one chaos-under-load report, one a11y audit report per screen with axe output and manual pass notes.

## Security notes
Exploratory sessions run against the demo environment only. Diagnostics snapshots attached to findings must be the redacted snapshot produced by SCR-046, not a raw state dump; if a tester finds that the snapshot contains anything sensitive, that is itself a security finding and is routed to E46-X02 rather than filed as a normal Bug. Screen recordings from sessions can capture account balances and order data and are handled as Confidential.

## Accessibility notes
This ticket contains the epic's a11y audit; the standards applied are `docs/plan/05-accessibility-standard.md` and WCAG 2.2 AA. Particular attention: the colour-independence rule as it applies to every threshold/tone in SCR-046, SCR-118 and the degradation indicator; polite (never assertive) live regions for values that update at 2 Hz; the pinned-overlay static-table reading mode; `aria-busy` during the SCR-118 benchmark; and keyboard access to `Ctrl+Shift+D` for users who cannot chord (command-palette route).

## Performance notes
Asserts budget #2 (30 fps floor, degraded mode), budget #14 (heatmap cadence, including its documented relaxation), budget #15 (replay), and the §4.4 ladder's invariants. Also verifies that the diagnostics overlay's own ≤0.5 ms/frame budget holds during the charters, since the overlay is open for much of the session.

## Observability
Findings reference the metric values observed at the time from the E46-T01/T04 surface; where a finding cannot be explained by the existing metrics, the gap is filed as an observability improvement rather than left as a mystery.

## Definition of Done
- [ ] All seven Gherkin scenarios adjudicated.
- [ ] Five charter debriefs written and retained.
- [ ] Degradation-ladder verification table complete, with the three "never acceptable" invariants explicitly signed off.
- [ ] Chaos-under-load report complete.
- [ ] a11y audit reports for SCR-046 and SCR-118, axe output attached, manual screen-reader pass recorded (with the deviation noted if only one screen reader was available).
- [ ] Every finding filed, triaged, severity-assigned and owner-assigned; P0/P1 findings fixed and re-verified before GA.
- [ ] QA lead sign-off comment.

## Dependencies
- **E46-Q01** for scenarios, injectors and fixtures.
- **E46-S01** and **E46-S02** must be built — two of the audit targets are those screens, and the diagnostics snapshot is the evidence mechanism.
- **E45** chaos harness reused for the chaos-under-load pass.

## Branch
`chore/e46-exploratory-and-a11y-audit` for any harness/test-hook additions.

## References
`docs/plan/03-testing-strategy.md` · `docs/plan/05-accessibility-standard.md` · `docs/plan/06-performance-and-load-standard.md` §3.2, §4.4, §2 budgets #2/#14/#15 · `docs/plan/14-screens-catalogue.md` SCR-046, SCR-118 · `docs/plan/11-user-stories.md` US-OBS-002, US-OBS-006, US-SET-008, US-DOM-005 · `docs/plan/02-definition-of-ready-done.md` §3.2
"""))

tickets.append(T("E46-Q04", "Task",
    "Assemble the GA performance evidence pack and give epic-level QA sign-off",
    ["type/test", "qa", "perf", "priority/p1", "area/chart-engine", "area/backend-platform"],
    "cross-cutting", "Sprint 26", "P1 High", "QA", "R2 Render performance", 3, "E46",
    ["E46-Q02", "E46-Q03", "E46-T10", "E46-T11", "E46-X02"],
    """## Context
`docs/plan/07-release-and-prr.md` gates each release behind a production-readiness review, and `docs/plan/30-release-roadmap.md` §9.4 lists "Perf" as an R5 quality gate. `docs/plan/02-definition-of-ready-done.md` §2.2 requires epic-level QA sign-off — *"an Epic-level regression/exploratory pass executed and recorded, not just child-ticket QA"* — and epic-level acceptance criteria verified end to end rather than per child.

E46 produces a large amount of evidence across many tickets: harness reports, soak reports, k6/Locust runs, the degradation verification table, a11y audits, the CI gate configuration and the security review. This ticket makes that evidence a single reviewable artefact for the PRR, checks it for gaps against the 15 budgets, and closes the epic.

It is deliberately small in points and late in the train: it produces no new measurement, it adjudicates.

## Scope / Deliverables
- **Performance evidence pack** (one document plus linked artefacts) containing, per budget from `docs/plan/06-performance-and-load-standard.md` §2: the target, the measured value on the GA candidate, the measurement method and date, the environment (reference hardware vs CI runner), the owning test case from E46-Q01's traceability table, and a verdict.
- **Gap analysis**: any budget without a GA-candidate measurement is listed explicitly as a gap with a disposition (measured late / waived with Owner sign-off / descoped), because an unmeasured budget silently presented as green is the failure mode this pack exists to prevent.
- **CI gate inventory**: the list of required checks E46-T10 established, with evidence that the injected-regression test proves each bites, and the named owner for each gate.
- **Baseline snapshot**: the `bench/baselines/` contents at GA, tagged with the release, so post-GA drift is measurable against a known point.
- **Open-risk statement**: remaining performance risks carried into GA, each with a mitigation, a trigger and an owner — fed into `docs/plan/32-risk-register.md` and the perf-incidents log created by E46-T11.
- **Epic-level acceptance verification**: each of the five epic acceptance scenarios in E46's body adjudicated with a pointer to its evidence.
- **QA sign-off comment** on the epic recording pass/fail per scenario, plus the explicit list of deviations (any scenario verified manually rather than automatically, with a follow-up ticket filed to automate it, per `02-definition-of-ready-done.md` §3.2).
- **PRR input**: the pack submitted as the performance section of the R5 production-readiness review.

## Out of scope
- Running any new test (Q02/Q03 own execution; if a gap requires a new measurement, this ticket files it back to them rather than absorbing it).
- Fixing defects.
- Documentation and runbooks beyond the pack itself (E48).

## Acceptance criteria
```gherkin
Scenario: Every budget is accounted for
  Given the GA performance evidence pack
  Then each of the 15 budgets in docs/plan/06-performance-and-load-standard.md §2 has a measured value, a method, an environment and a verdict
  And any budget without a GA-candidate measurement is listed as an explicit gap with a named disposition

Scenario: The gates are proven, not assumed
  Given the CI gate inventory
  Then each required performance check has evidence that an injected regression fails it
  And each has a named owner

Scenario: Epic acceptance is adjudicated end to end
  Given E46's five epic-level acceptance scenarios
  Then each is marked pass or fail with a direct link to the evidence that decided it
  And a fail blocks the epic from Done

Scenario: A waived budget is visible, not hidden
  Given one budget cannot be measured on reference hardware before GA
  Then it appears in the pack as waived with the Owner's recorded sign-off and a follow-up ticket
  And it is not presented as green

Scenario: Sign-off records its deviations
  Given the QA sign-off comment
  Then it lists every scenario verified manually rather than automatically
  And each has a filed follow-up ticket to automate it
```

## Technical notes / design
The pack is assembled from artefacts, not re-typed from memory: every number in it links to the archived report that produced it (commit, runner, fixture hash). A number in the pack that cannot be traced to an artefact is treated as absent.

Structure mirrors §2's table so a reviewer can diff the pack against the standard line by line; this is deliberate, because the reviewer's job at the PRR is to find the row that is quietly missing.

## Test plan
Verification is by review: the pack is reviewed by the Architect, the frontend and backend leads, and the Security engineer (for the artefact-handling and telemetry-exposure statements). The traceability table from E46-Q01 is the checklist used.

## Security notes
The pack aggregates artefacts that individually may be Confidential (profiling captures, soak logs with demo order data). The pack itself must contain only measured numbers and links, so that the pack can circulate at the PRR while the underlying artefacts stay access-controlled. This split is stated explicitly in the pack's header. E46-X02's review outcome and residual-risk acceptances are summarised (not reproduced in full) in the open-risk statement.

## Accessibility notes
The a11y audit outcomes from E46-Q03 are included as a section of the pack, so that the PRR sees performance and accessibility evidence together rather than treating a11y as a separate afterthought. N/A otherwise — no UI surface.

## Performance notes
This ticket asserts nothing new; it is the consolidated statement of every budget's GA state, and is the input to the R5 exit criterion in `docs/plan/30-release-roadmap.md` §9.3 and the PRR gate in `docs/plan/07-release-and-prr.md`.

## Observability
The baseline snapshot and the gate inventory are the mechanism by which post-GA performance regressions remain detectable; the pack names where they live and who watches them.

## Definition of Done
- [ ] All five Gherkin scenarios satisfied.
- [ ] Evidence pack merged/archived and linked from the R5 PRR record.
- [ ] Gap analysis complete with a disposition per gap; no silent gaps.
- [ ] Baseline snapshot tagged with the release.
- [ ] Open risks transferred to `docs/plan/32-risk-register.md` and the perf-incidents log.
- [ ] QA sign-off comment posted on the epic with pass/fail per epic-level scenario and its deviations.
- [ ] Reviewed by Architect, frontend lead, backend lead and Security engineer.
- [ ] Owner acceptance recorded at Sprint Review.

## Dependencies
- **E46-Q02** and **E46-Q03** supply the measurements and findings.
- **E46-T10** supplies the gate inventory.
- **E46-T11** supplies ADR-0016 and the perf-incidents log referenced by the open-risk statement.
- **E46-X02** supplies the security review outcome.

## Branch
`docs/e46-ga-performance-evidence`. Docs-only PR.

## References
`docs/plan/07-release-and-prr.md` · `docs/plan/30-release-roadmap.md` §9.3, §9.4 · `docs/plan/06-performance-and-load-standard.md` §2, §7.4 · `docs/plan/02-definition-of-ready-done.md` §2.2, §3.2 · `docs/plan/32-risk-register.md` · `docs/plan/03-testing-strategy.md`
"""))
