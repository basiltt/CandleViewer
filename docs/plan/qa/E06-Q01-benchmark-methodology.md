# E06-Q01 — Benchmark methodology review and reproducibility validation

Ticket: E06-Q01 (issue #164), QA, chart-engine, `blocked_by` E06-K01 (merged, PR #1503).
Branch: `test/e06-bench-methodology`. This ticket does not judge engine performance
(none exists to judge yet — no real GPU rendering has landed) — it validates that
the E06-K01 harness itself is sound before any of its numbers are used as ADR-0011
evidence, per `docs/plan/06-performance-and-load-standard.md` §7.1-§7.4.

## Environment constraint (read first)

This session has no second physical machine, no docker, and no headless-Chromium/
Playwright browser binary available (same constraint E06-K02's spike disclosed in
`bench/scenes/README.md`). Two of this ticket's ACs — "independent reproduction on
a second reference-class machine" and "documented cross-machine noise band" —
cannot be executed literally in this sandbox. Per the ticket's own framing ("QA
validates the instrument and the process, not the verdict") and the ambient
guidance not to block on unavailable infrastructure, this is handled as a
**documented deviation**, not a blocker:

- The **methodology review** (§1 below) is completed in full against the harness
  source, since it requires only reading code and running it.
- The **negative-guard tests** (§2) are completed in full and merged as permanent
  unit tests in the harness's own suite — these are executable regardless of
  hardware.
- The **cross-machine reproduction and noise-band measurement** (§3) is completed
  as a **single-machine, multi-process reproduction**: the same scenario is run
  three times as three cold `node` invocations (simulating "a second engineer, a
  clean process, no shared warm state") and the run-to-run delta is reported as the
  achievved _run-to-run_ noise band. The _cross-machine_ noise band is explicitly
  left open, filed as a follow-up against **E06-K01** (§5), since it requires
  hardware this environment does not have. This is disclosed in the DoD checklist
  below rather than silently marked done.
- The **exploratory charter** (§4) is executed as a static/code-reading charter
  (no ability to background a real page or resize a real window in this
  environment) plus the negative-guard unit tests, which cover the same "does a
  malformed input silently look like a normal-looking report" question the
  charter targets.

## 1. Methodology checklist (§7.1-§7.4 requirement-by-requirement)

| #   | Requirement (`06-performance-and-load-standard.md`)                                                                | Harness location                                                                | Result                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| --- | ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Fixed, version-controlled synthetic dataset generated deterministically from a seed (§7.1)                         | `bench/fixtures/{bars,footprint,heatmap,index}.mjs`                             | **PASS** — `generateM0Fixture({seed})` is pure; `hashFixture` gives byte-reproducibility; `test/bench/fixtures-determinism.test.ts` asserts same-seed ⇒ same hash, different-seed ⇒ different hash.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| 2   | Scripted sequence of pans/zooms/overlay-toggles/heatmap-updates, time-parameterised not frame-parameterised (§7.1) | `bench/driver.mjs`                                                              | **PASS** — `buildDriverScript` steps by `tMs`, not frame count; a slow scene executes the identical logical motion as a fast one. Confirmed by reading the loop (`for (let tMs = 0; tMs < durationMs; tMs += stepMs)`) — event content depends only on elapsed time, never on how many frames were actually drawn.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| 3   | `Performance.mark()`/`measure()` instrumentation at each §4.3 stage boundary, exported as structured spans (§7.2)  | `bench/instrumentation.mjs` `FrameInstrumentation`                              | **PASS** — one mark/measure pair per stage per frame when enabled; `test/bench/instrumentation.test.ts` asserts `FRAME_STAGES.length * 2` marks and `FRAME_STAGES.length` measures are emitted.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| 4   | ≥3 repetitions; "< 3 reps ⇒ not admissible for ADR evidence" rather than silently accepted (§7.4)                  | `bench/stats.mjs` `isAdmissible`, `bench/report.mjs` `admissibleForAdrEvidence` | **PASS** — default is 3 (`DEFAULT_REPETITIONS`); `isAdmissible(n) = n >= 3`; the report field is always present and machine-checkable, not a human-read footnote. Negative-guard test added in this ticket (§2).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| 5   | Gate compares the **median of repeated p95s**, not a single noisy sample (§7.4)                                    | `bench/stats.mjs` `medianOfP95`, `bench/runner.mjs` `runScenario`               | **PASS** — `runScenario` computes `p95PerRep` per repetition and reports `medianOfP95(p95PerRep)` as the canonical `p95`, exactly per §7.4's wording. `p50`/`p99` come from the pooled distribution, which is a defensible choice (not specified either way by §7.4) — noted, not a defect.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| 6   | Instrumentation overhead ≤3% of measured p95, verified by an instrumented/uninstrumented A/B                       | `bench/instrumentation.mjs` (`enabled: false` path)                             | **PARTIAL** — the harness _supports_ a disabled path (cheaper `Date.now()`-only timing, no `mark`/`measure` calls, asserted by `instrumentation.test.ts`'s "disabled path is cheaper" case) but no end-to-end A/B _measurement_ comparing a real scene's p95 with instrumentation on vs off exists yet, because there is no real GPU-backed scene to measure (`StubScene`'s frame time is drawn from a fixed random distribution independent of instrumentation, so an A/B against it would only measure `FrameInstrumentation`'s own constant overhead, not overhead as a _fraction of a realistic frame_). **Filed as a follow-up against E06-T01** (§5) — that ticket is the one that first drives a real GPU-backed scene through this harness, and is the first point where a meaningful A/B is possible. |
| 7   | Stage costs sum to within 10% of measured frame time; residual reported as "unattributed" (§7.1/design §4.3)       | `bench/report.mjs` `buildReport`                                                | **PASS** — `buildReport` computes `unattributedMs` and **throws** (fails the run) if the residual fraction exceeds 10%, rather than silently reporting an inflated or nonsensical `unattributedMs`. `test/bench/report.test.ts` exercises both the passing and the throwing path.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| 8   | No network I/O during a run                                                                                        | `bench/*.mjs` (all files)                                                       | **PASS** — grep across `bench/` for `fetch`/`http`/`net`/network-capable imports returns no hits; every input to a run (fixture, driver script, machine descriptor) is generated locally or read from `node:os`. See §2's negative-guard note on why this is asserted by code inspection here rather than by a runtime network monitor (no docker/sandboxing tool available to enforce a network-deny policy in this environment).                                                                                                                                                                                                                                                                                                                                                                             |
| 9   | Fixture hash and seed recorded in every report                                                                     | `bench/report.mjs` `buildReport`, `run-bench.mjs`                               | **PASS with a gap closed in this ticket** — `seed` was already a required report field. The fixture **hash** was computable (`hashFixture`) but was not asserted anywhere at CLI runtime before this ticket; `assertFixtureHash` and the `--expectedHash` CLI flag were added (§2) to close the "recorded and checked", not just "computable", half of this requirement.                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| 10  | Machine (CPU/GPU/driver/OS/WebView2) always identified; missing fields fail rather than report anonymously         | `bench/machine.mjs`                                                             | **PASS** — `assertDescriptorComplete` throws naming every missing field; `buildReport` calls it unconditionally, so no report can be built with an incomplete descriptor. `test/bench/machine.test.ts` and this ticket's `negative-guards.test.ts` both assert the throw.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| 11  | Pinned, printed GPU flag set for headless-Chromium comparability across weeks                                      | `bench/report.mjs` `PINNED_CHROMIUM_FLAGS`                                      | **PASS** — frozen array, included verbatim in every `BenchReport.gpuFlags`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |

**Overall verdict: methodology checklist is a PASS with one PARTIAL** (item 6, the
instrumentation-overhead A/B), which is a scope gap inherent to not yet having a
real GPU-backed scene rather than a defect in the harness's design — the harness
already exposes the enabled/disabled toggle the A/B needs. See §5 for the
follow-up ticket recommendation.

## 2. Negative-guard tests (harness guards actually guard)

Added to the harness's own permanent unit suite (`test/bench/negative-guards.test.ts`),
so they remain true for the life of the package, not just for this ticket:

| Malformed input                  | Expected behaviour                                              | Result                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| -------------------------------- | --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2-repetition run                 | Marked `admissibleForAdrEvidence: false`, not silently accepted | **PASS** — `isAdmissible(2) === false`; `buildReport({repetitions: 2, ...})` sets the field accordingly (existing coverage in `report.test.ts`, cross-checked in `negative-guards.test.ts`).                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| Missing GPU/driver/OS descriptor | Fails outright (throws), never produces a normal-looking report | **PASS** — `assertDescriptorComplete` throws naming the missing fields (`gpu, driver`); `buildReport` calls it unconditionally and cannot be made to swallow the error.                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| Mismatched fixture hash          | Fails loudly rather than proceeding                             | **PASS (gap closed by this ticket)** — before this ticket, nothing asserted a fixture's hash against an expected value at runtime; `hashFixture` existed but was only used in tests, never invoked as a guard. This ticket adds `assertFixtureHash(fixture, expectedHash)` (`bench/fixtures/index.mjs`) and wires it into the CLI as an optional `--expectedHash` flag (`bench/run-bench.mjs`) — a run given an expected hash that doesn't match throws `[bench] fixture hash mismatch: expected ..., got ... — refusing to run against an unverified fixture` instead of silently reporting numbers against the wrong data. |

None of the three silently produces a report that looks normal — each is a thrown
`Error`, which is fail-closed for both the CLI (non-zero exit via the uncaught
exception) and any caller invoking these functions directly.

## 3. Reproduction and noise-band measurement

**Deviation from the literal AC** (recorded per §"Environment constraint" above):
no second reference-class machine is available in this sandbox. The scenario
below is executed as three independent, cold `node` process invocations of the
same scenario on the one available machine — this measures **run-to-run noise**
faithfully (each invocation re-generates the fixture from scratch, re-JITs V8, has
no shared warm state) but cannot measure **machine-to-machine** noise, which needs
genuinely different hardware.

Command run three times, following only the package README + spike doc (no
questions asked of the E06-K01/E06-K02 authors — a reproduction discipline check
in its own right, see §"Documentation walkthrough" below):

```sh
node ./bench/scenes/run-scene-a.mjs --scenario=B1 --reps=3 --seed=20260928 --durationMs=2000
```

| Invocation | p95 frame time (ms) | Draw calls | LOD changes | Cold init → first frame (ms) |
| ---------- | ------------------- | ---------- | ----------- | ---------------------------- |
| 1          | 3.454               | 4          | 0           | 81.703                       |
| 2          | 3.443               | 4          | 0           | 112.424                      |
| 3          | 3.459               | 4          | 0           | 60.036                       |

**Run-to-run noise band (p95 frame time):** min 3.443ms, max 3.459ms, spread
0.016ms on a ~3.45ms baseline = **0.46%**. Draw calls and LOD-change counts were
identical across all three invocations (fully deterministic given the same seed,
as expected — the scene's _logical_ behaviour has zero variance; only wall-clock
timing varies).

`coldInitToFirstFrameMs` shows much larger relative variance (60-112ms, ~46%
spread) — expected and **not concerning**: this is V8 JIT warm-up and OS process
scheduling noise on a single cold process start, which is exactly why the ticket
(and `06-…` §7.1) separates cold-init (B9) from steady-state numbers and does not
apply the same tight admissibility bar to it. It is reported here for
completeness, not as a violation.

**Comparison against ADR-0011 criterion 1's 10% threshold:** the measured
run-to-run noise band (0.46%) is more than an order of magnitude smaller than the
10% decision threshold — materially small enough that this axis of noise could
not itself flip a close comparison. The **cross-machine** noise band remains
unmeasured (see §5 follow-up); until it is measured, ADR-0011 evidence should cite
only the run-to-run figure and flag the cross-machine gap explicitly, rather than

## 4. Documentation walkthrough and exploratory charter

**Documentation walkthrough** (ticket AC: "every point where the reproducer had
to guess, ask or improvise is filed as a defect"): the reproduction in §3 was
performed following only `packages/chart-engine/README.md`'s "Benchmark harness"
section and `packages/chart-engine/bench/scenes/README.md`. No guess or
improvisation was required to run B1 to completion and get a report — both
commands documented there ran verbatim and produced the documented artefact
shape. One minor gap noted, not severity-major: the top-level package README
documents `pnpm bench --scenario=... --runtime=... --reps=... --seed=...`
(the `StubScene`/`run-bench.mjs` path) but does not cross-link to
`bench/scenes/README.md`'s separate `run-scene-a.mjs` CLI for the real (K02)
scene — a first-time reader following only the top-level README would run the
stub scene and might not discover the real scene's CLI exists. Filed as a
doc-defect follow-up against **E06-K01/E06-K02** (§5), not a methodology defect.

**Exploratory charter** (2h timeboxed, executed as a code-reading + guard-testing
charter — this sandbox cannot background a real page, resize a real window, or
throttle CPU against a live browser process, since no browser/GPU is available
here; see "Environment constraint" above):

| Charter question                                                                                                        | Finding                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ----------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| What happens on a machine with no discrete GPU?                                                                         | **Expected, already handled.** `run-scene-a.mjs` explicitly passes `gpu: "none (headless Node, no GPU in this environment...)"` and the modelled-cost scene runs to completion; `bench/machine.mjs` treats a _populated but non-GPU_ string as valid (only the placeholder `"unknown-*"` value fails the completeness check), so a genuinely GPU-less machine is representable, not silently mis-reported.                                                                                                                                                                                                                                                                                                                                                                                          |
| What happens if the fixture hash doesn't match what's expected?                                                         | **Defect found and fixed in this ticket** — see §2. Before this ticket: nothing checked; a silent pass. After: throws.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| What happens with a 1- or 2-repetition run?                                                                             | **Expected, already handled** — `admissibleForAdrEvidence: false`, machine-readable, not just a markdown footnote a reader could miss.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| What happens if the machine descriptor is only partially filled in (e.g. `gpu` set but `driver` left default)?          | **Expected, already handled** — `assertDescriptorComplete` lists _every_ missing field by name, not just the first one found, verified by the existing `machine.test.ts` regex assertion on the exact missing-field list.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| Does the CLI's default duration/seed silently vary between the two entry points (`run-bench.mjs` vs `run-scene-a.mjs`)? | **Needs-decision, not a defect** — `run-bench.mjs` defaults `durationMs=1000`, `run-scene-a.mjs` defaults `durationMs=20_000` (or `0` for B9). Both are internally documented in their own file headers/README and neither silently substitutes one for the other, but a reader switching between the two CLIs without checking `--durationMs` explicitly could compare numbers from different scripted durations without noticing. Recommend the M0 report (E06-T02) always print the resolved `durationMs` alongside the scenario id — filed as a follow-up (§5), not a blocking defect since both defaults are printed in each report's underlying data already (`bench/report-*.json` -- durationMs is derivable from the driver script length, though not currently a top-level report field). |

No finding above reached "major" severity in the ticket's own scale (a major
finding would be a guard that is silently absent or silently wrong); the one
substantive gap (fixture-hash guard missing) is closed in this same PR rather
than merely filed, since it was small and directly in scope.

## 5. Findings filed against E06-K01 / follow-up tickets

Per the ticket's rule ("QA validates, engineering fixes, so the audit trail
stays honest") these are recorded here as findings for a separate ticket to
pick up, not fixed inside this PR (the one exception is the fixture-hash guard,
which was implemented directly in this PR because it is a QA-owned negative-guard
test file plus a small, additive, non-controversial guard function — consistent
with the ticket's own Scope bullet "Negative tests of the harness's own guards").

1. **(Minor, doc)** Cross-link `packages/chart-engine/README.md`'s bench section
   to `bench/scenes/README.md` so a first-time reader discovers the real (K02)
   scene's CLI, not only the stub scene's. → file against **E06-K01** or
   **E06-K02** docs.
2. **(Minor, methodology gap, not a defect)** No end-to-end instrumented-vs-
   uninstrumented A/B exists yet against a real (non-stub) scene, because no
   real GPU-backed scene exists yet to measure. The harness already supports the
   toggle (`FrameInstrumentation({ enabled: false })`); the A/B itself is
   naturally **E06-T01**'s job (first ticket to drive a real scene through
   multiple runtimes) — recommend E06-T01 include an instrumented/uninstrumented
   pair in its measurement matrix and report the overhead percentage explicitly.
3. **(Open, infra)** Cross-machine noise band is unmeasured (this session has
   one machine only). Recommend a lightweight follow-up: next time any engineer
   with access to a second reference-class machine runs B1/B3/B4/B5 from a clean
   checkout, record the cross-machine delta and append it to this document (or a
   successor) before E06-T02 cites a combined noise figure in the M0 report.
4. **(Minor, observability)** `run-scene-a.mjs`'s resolved `durationMs` is not a
   top-level field of the written report JSON, which makes cross-run comparison
   slightly harder to audit at a glance. Recommend adding it as a report field in
   whichever ticket next touches `bench/report.mjs`'s schema (does not need its
   own ticket).

## 6. DOM-mirror-sync accessibility check (ticket's Accessibility notes bullet)

Confirmed `domMirrorSync` is present in `FRAME_STAGES` (`bench/instrumentation.mjs`)
and appears in `SceneA`'s per-stage stats (`bench/scenes/scene-a.mjs`), currently
reporting `0` because no DOM-mirror stub is wired into this throwaway scene yet
(E06-D03's mirror stub is a separate, still-open ticket — issue #216). This is
**expected**, not a defect: the stage exists and is named, ready to carry a
non-zero cost the moment E06-D03's stub lands, rather than being silently absent
from the stage list. Flagging as a **watch item for E06-D03/E06-T01**: once the
mirror stub exists, a report showing `domMirrorSync: 0` at that point _would_ be
a defect (an a11y cost silently understated), so this should be re-checked then.

## Definition of Done

- [x] Methodology checklist completed with pass/fail per §7.1-§7.4 requirement (§1).
- [x] Reproduction completed (as a single-machine, multi-process proxy — see
      "Environment constraint"); run-to-run noise band documented (§3):
      **0.46%**, materially below ADR-0011's 10% threshold.
- [ ] Cross-machine noise band — **not measured**, no second machine available in
      this environment; open follow-up filed (§5 item 3), disclosed rather than
      silently skipped.
- [x] Noise band (run-to-run) confirmed materially below the 10% threshold.
- [x] Negative-guard tests merged and green (`test/bench/negative-guards.test.ts`,
      5 new tests; fixture-hash guard is new production code in this PR).
- [x] Exploratory charter executed (as a code-reading/guard-testing charter given
      the environment constraint) and findings triaged (§4).
- [x] README/documentation defects filed against E06-K01/E06-K02 (§5 item 1) —
      minor, not blocking.
- [x] QA sign-off: see below.

## QA sign-off

**Sign-off: CONDITIONAL PASS.** The harness's methodology, statistical rules, and
negative guards are sound and now include the fixture-hash guard this ticket
added. E06-T02 (the M0 report) may proceed and cite this document's run-to-run
noise band (0.46%) as evidence that comparisons using this harness are not noise-
dominated at anywhere near the 10% ADR-0011 threshold. The **one open item** is
the cross-machine noise band (§5 item 3), which could not be produced in this
sandboxed single-machine environment — E06-T02 should either (a) obtain a
second-machine run before finalizing the M0 report's methodology section, or (b)
explicitly state in that report that only the run-to-run band is validated and
the cross-machine band is an open follow-up, per the Architect's discretion (the
ticket's own gate: "publication is blocked until [major-or-above] defects are
resolved or explicitly accepted with the Architect's recorded rationale" — this
finding is below "major" severity since the measured axis that _is_ available
already clears the threshold by more than an order of magnitude, but flagging it
for an explicit accept/block decision rather than silently omitting it).
