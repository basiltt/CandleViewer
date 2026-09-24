# Meta-issue #26 — round-10 update: `main` @ `19cb1f1` (unreleased 0.8.1)

**Round 10. Verified build:** `main` @ **`19cb1f1`** (merge of PR #211, commit `4dbf86e`).
`__version__` still reports `0.8.0` on this tree — **identify this build by commit, never by version string.** CPython 3.13.7, Windows 11, fresh venv, all repros run from a neutral working directory.

**GATE DECISION: ADOPT WITH CONSTRAINTS — decision-table row 8**, up from row 6 last round. Row 8 is "all Blocker and High closed, all Medium triaged, benchmark thresholds not all met": the constraints that remain are **architectural consequences of our own benchmarks**, not containment for library defects. Our round-9 report named row 8 as the honest ceiling for this library in our system. This release reaches it.

**Method:** 8 issue verifications re-run live; full regression sweep; complete test suite + coverage; diff review `f28719c..19cb1f1`; 8 battle tracks; 20 contract machines driven end-to-end **on both service spellings**; triage → dedupe → **independent adversarial refutation of every Blocker and High**. Nothing counted without a standalone repro on a clean interpreter, and every service/action check run with both `def` and `async def`.

---

## Headline

**This is the first round in ten where every fix the release claims landed on every axis it claimed.**

Rounds 6, 7, 8 and 9 each found at least one fix that held on one engine or one service spelling and not the other — our round-9 report called a third occurrence "a process signal rather than a bug pattern." Round 10 finds **zero**. The service-kind axis is flat across the entire corpus except for the one documented, intended divergence (a `def` service is non-preemptable, `production-characteristics.md` §2).

**Both round-9 Highs are closed, at the right sites:**

- **#203** gates `after` selection on `is_system_event`, the same test the `done`/`error` branch already used. The control that made it a High — a public `AfterEvent` firing a 60 s timer instantly at the **default** `strict=False` — is refused on both engines.
- **#204** moves invoke arming into the settle pass per SCXML §6.1 `statesToInvoke`, closing the roll-forward half **on both engines and both service kinds**: our `LD-01` repro goes 3 leaks → **0/6**, our B6–B10 `def` lane 51/52 → **52/52**, and `rollback_reinvoke_spin` on `SyncInterpreter` — which we had recorded as a permanent expected-failure — now passes 5/5.

We also completed the measurement we owed you from round 9: **3505 passed, 13 skipped, 0 failed, 566.57 s, coverage 92.78 %**, above your own 90 % floor and up from 92.70 % at `6db65d8`.

**Post-refutation the round leaves 0 Blocker · 0 High · 5 Medium · 7 Low.** The High row is empty for the first time.

## Disposition of the 8 issues

| Disposition | Issues |
|---|---|
| **FIXED — closing** (8) | #203, #204, #205, #206, #207, #208, #209, #210 |

No issue regressed, and no issue is partially fixed. Three carry follow-up notes on their own threads (#206's scope, #208's unreachable branch, #209's inert second shape and overstated general claim).

## A correction we owe you

We filed a **Blocker** internally this round against engine-event provenance — seven forgery vectors across `done`/`error`/`after`, in-process and via `restore_event`'s plaintext `"engine": true`. **We refuted it ourselves and have downgraded it to Low, and we are not filing it as a vulnerability.**

Every vector reproduces exactly as we found it. But they partition into two classes and neither crosses a trust boundary:

- **Class A** (`engine_after` import path, `type(held)(...)`, `pickle`, `deepcopy`, `_EngineAfter`, `_replace`) presumes attacker-controlled Python in-process. We ran the control: a plain registered action with **no forgery at all** writes context arbitrarily, and a live `Interpreter` exposes `_enter_states`/`_exit_states` directly. Forging an `AfterEvent` is strictly weaker than the premise — and a per-interpreter nonce, which is what we were going to ask for, would be readable by the same reach.
- **Class B** (forged `"engine": true` record) requires blob-write. Rather than accept `events.py:414`'s claim we tested it: **a hand-edited snapshot with no event forgery whatsoever** restores to an arbitrary state with arbitrary context. The flag adds zero capability over what the blob writer already holds.

Meanwhile the boundary `#195`/`#203` actually target — external name/shape confusion — **holds in every probe we could construct** under `strict: True` + `onUnhandled: "error"`. The design is documented verbatim at `docs/api/index.md:1185-1201`, including the `_replace`/`pickle`/`deepcopy` preservation.

What survives is hardening-grade and we are raising it as such: unprefixed `engine_*` factories in a public module, `restore_event` trusting a plaintext boolean where the docs should mandate signing the whole snapshot, and `_replace` re-typing a genuine event.

We also refuted, on the same standard, our own **High** against self-targeting `onDone` — a self-transition is **internal** by contract, XState v5 makes internal the default with `reenter: true` as the opt-in, and your docs say so three times including a troubleshooting entry naming this exact shape. With `"reenter": true` every lane re-arms correctly to `maxIterations + 2` and the `#207` stranded hook fires. Our probe's oracle was miscalibrated. The only residual is an **Info**: `validation.py:205` warns for an `always` self-target that cannot progress, but has no equivalent for an `onDone`/`on` self-target restart loop — a warning there would have saved us a round.

## What we are filing new

| ID | Sev | Title |
|---|---|---|
| R10-03 (#212) | Medium | `#206`'s chain charge is time-blind, so a `raise(delay=)` self-paced heartbeat dies at `maxIterations` beats regardless of period (behaviour break not named in the changelog) |
| R10-04 (#213) | Medium | An armed-but-unfired delayed self-`raise` has no snapshot representation and is silently lost on restore |
| R10-05 (#214) | Medium | The restore path bypasses `strict`, and `#203` now silently **drops** a pre-0.8.1 persisted `after` deadline (migration cliff) |
| R10-06 (#215) | Medium | `#209`'s "all three lanes agree at limits 1–25" is false on engine-work-only charts; the gap grows with the limit |
| R10-07 (#216) | Medium | Unknown top-level config keys accepted silently — a misspelled `strict`, `onUnhandled` or `actionErrorPolicy` downgrades to its permissive default with a green build |

Each has a standalone repro embedded in its issue body, stdlib + `xstate_statemachine` only, runnable from any working directory.

**Low, raised as hardening/diagnostics rather than defects:** engine-event provenance as type identity (above); call-site `QueueOverflowError` refusals bypassing `on_event_dropped` (99.3 % of shed invisible to a metrics pipeline); `SnapshotMidStepError` from an invoked child's entry action reporting `child=False`; the `+2` / `+3` changelog contradiction (**both are correct for their own shapes** — an event-entered state costs one lap less than an initial-state invoke; the changelog conflates them); `#208`'s illegal-configuration branch being unreachable because `_repair_configuration()` runs first; `after` not firing under `SimulatedClock.increment()` (**pre-existing, identical on `f28719c`, not caused by `#203`**); and the chain trip never reaching `on_error`/`interpreter.error`, with `last_error` **cleared on the `async def` lane and retained on `def`** — which means a supervisor sampling asynchronously misses the runaway on the recommended spelling.

## Before tagging 0.8.1

One blocking item and three we would like in the same release:

1. **Bump `__version__` to `0.8.1`** — it still reports `0.8.0`. Our pin stays on the commit + source hash until a tag exists whose `__version__` matches it. A release test asserting `__version__ == tag` would close this permanently.
2. Fix the `+2` / `+3` plateau contradiction (name the shape each figure belongs to).
3. Narrow or fix the `#209` lap-parity claim.
4. Name `#206` as a behaviour break for `raise(delay=)` periodic work, with `after` as the migration.

And one test-hygiene note: the `#209` pin sweeps two shapes, and **the `nested_invoke` one is inert** — it never exits its initial state, so it fires exactly 2 calls at every limit 1–25 and never trips. It agrees across lanes because a constant agrees with itself. The verdict stands on the other shape; the pin just claims more coverage than it has.

## Where this leaves us

Zero library defects across all 20 of our contract machines, on both engines and both service spellings. Zero Blockers. Zero Highs. A clean suite at 92.78 % coverage.

The only Blockers left anywhere in this ten-round study are **two of our own chart bugs**, and this round we proved they are ours by building the corrected charts and watching them pass on every engine and every spelling. The engine follows the chart in every cell.

**Trend, round 5 → round 10:**

| Round | Commit | Blocker | High | Medium | Low |
|---|---|---|---|---|---|
| 5 | `3ed3099` | 4 | 8 | 8 | 1 |
| 6 | `cec108b` | 2 | 2 | 7 | 9 |
| 7 | `221ce7c` | 2 | 4 | 6 | 8 |
| 8 | `6db65d8` | 1 | 3 | 7 | 4 |
| 9 | `f28719c` | 0 | 2 | 5 | 8 |
| **10** | **`19cb1f1`** | **0** | **0** | **5** | **7** |

**4 Blocker · 8 High at round 5 → 0 Blocker · 0 High at round 10.** Every
Blocker and every High of any kind belonging to the library is now closed;
this is the first round where the High row itself is empty.

## Full checklist, #27–#210, by status

Every issue we have ever filed against this library, round 1 through round 10.
`closed` means confirmed fixed and holding on this round's re-verification (or,
for issues predating round 6, never regressed on any later round's regression
sweep). Issues carrying a residual are cross-linked to the `R{n}-nn` finding
that narrows or continues them.

| Status | Issues |
|---|---|
| **closed** (round 1–3, #27–#98) | #27 #28 #29 #30 #31 #32 #33 #34 #35 #36 #37 #38 #39 #40 #41 #42 #43 #44 #45 #46 #47 #48 #49 #50 #51 #52 #53 #54 #55 #56 #57 #58 #59 #60 #75 #76 #77 #78 #79 #80 #84 #85 #86 #87 #88 #89 #90 #91 #92 #93 #94 #95 #96 #97 #98 |
| **closed** (round 4–5, #99–#145) | #99 #102 #103 #104 #105 #106 #107 #108 #109 #110 #111 #112 #113 #114 #115 #116 #117 #118 #119 #120 #121 #123 #124 #125 #126 #127 #128 #129 #130 #131 #132 #133 #134 #135 #136 #137 #138 #142 #143 #144 #145 |
| **closed** (round 6–7, #146–#178) | #146 #147 #148 #149 #150 #151 #152 #153 #154 #155 #156 #157 #158 #159 #160 #161 #162 #163 #164 #165 #166 #169 #170 #171 #172 #173 #176 #177 #178 |
| **closed** (round 8, #179–#191) | #179 #180 #182 #183 #184 #185 #187 #188 #189 #190 #191 |
| **closed** (round 9, #181 #186 #192 #194 #196 #198 #199 #200 #201) | #181 #186 #192 #194 #196 #198 (residual `R9-14`, Low) #199 (residual `R9-15`, Low) #200 #201 (residual `R9-09`, Medium/doc) |
| **closed** (round 10, #203–#210) | #203 (residual `R10-05` #214, Medium) · #204 (no residual) · #205 (residual, folded into hardening notes above) · #206 (residual `R10-03` #212, Medium) · #207 (two residuals, Low) · #208 (changelog overstatement, Low) · #209 (residual `R10-06` #215, Medium, plus inert-pin test-hygiene note) · #210 (residual, changelog plateau contradiction, Low) |
| **superseded/withdrawn/tracking** | #26 (this meta-issue) · #61–#74, #100–#101 (not part of our verified set) · #167, #168, #174, #175 (folded into round-8/9 dispositions, see `48-r8-findings-register.md` / `53-r9-findings-register.md`) · #193, #195, #197 (fully closed as of round 9/10, see rows above) |

**We never close or reopen upstream issues ourselves — every "closed" row
above reflects our own re-verification; the residual, where one exists, is
filed as a new `R10-nn` issue rather than a reopen.**

## Round 10 — new findings

| ID | Sev | Title |
|---|---|---|
| `R10-03` (#212) | Medium | `#206`'s chain charge is time-blind, so a `raise(delay=)` self-paced heartbeat dies at `maxIterations` beats regardless of period |
| `R10-04` (#213) | Medium | An armed-but-unfired delayed self-`raise` has no snapshot representation and is silently lost on restore |
| `R10-05` (#214) | Medium | The restore path bypasses `strict`, and `#203` now silently drops a pre-0.8.1 persisted `after` deadline (migration cliff) |
| `R10-06` (#215) | Medium | `#209`'s "all three lanes agree at limits 1–25" is false on engine-work-only charts; the gap grows with the limit |
| `R10-07` (#216) | Medium | Unknown top-level config keys accepted silently — a misspelled `strict`, `onUnhandled` or `actionErrorPolicy` downgrades to its permissive default with a green build |

## Our refuted / withdrawn claims

We would rather withdraw a finding loudly than leave a bad one on the record:

- **R10-01 downgraded, Blocker → Low.** Seven engine-event-provenance forgery
  vectors all reproduce, but they partition into in-process Python (strictly
  weaker than the premise: a plain registered action already writes context
  arbitrarily) and blob-write (a hand-edited snapshot with no event forgery at
  all already relocates the machine and rewrites context). Neither crosses a
  trust boundary; not filed as a vulnerability. See `refuted/R10-02-refuted.md`
  and the #203/#205 comments for the full reasoning.
- **R10-02 refuted outright, not filed.** A self-targeting `onDone` is an
  **internal** transition by contract; XState v5 makes internal the default
  for a self-transition, with `reenter: true` as the documented opt-in — named
  three times in the docs, including a troubleshooting entry for this exact
  shape. With `"reenter": true` every lane re-arms correctly to
  `maxIterations + 2` and the `#207` stranded-invocation hook fires as
  designed. Residual: an Info-level validator gap (`validation.py:205` warns
  for an `always` self-target that cannot progress, but has no equivalent
  warning for an `onDone`/`on` self-target restart loop). See
  `refuted/R10-02-refuted.md`.
- **R10-C1, R10-C2, R10-C4 — refuted as library defects, retained as our own
  catalogue items (C-04, C-07b, CV-C4x).** Each traced to a contract-modelling
  error or a documented, XState-v5-aligned policy on our side, not a library
  defect; see `manifest.json` → `refuted` for the per-item reasoning.
- **R10-C3 downgraded, High → Medium (ours).** `stale_lockout` is escapable
  via `RECONNECTED`, so the original High premise fails; retained as a lower
  severity contract defect in our own catalogue, not filed upstream.

## Shim retirement

With 0 Blocker, 0 High, and the library's own regression suite at 3505 passed
/ 0 failed / 92.78 % coverage, **Phase 3 of our compatibility-shim retirement
may begin.** Every remaining gate between us and a full, unshimmed adoption is
now one of our own architectural constraints (row 8's benchmark thresholds) —
none is a containment measure for a library defect.

## Release note — before tagging 0.8.1

We would pin a tag cut at `19cb1f1` as-is. None of the 5 Mediums filed this
round (`R10-03`–`R10-07`) are tag-blocking; each is a narrow, documented-scope
residual with a stated workaround. The one item we consider blocking before
the tag itself is bumping `__version__` to match — `19cb1f1` still reports
`0.8.0`, which is why every disposition in this document keys on the commit
hash rather than the version string. We ask that the release notes for 0.8.1
explicitly document `R10-05`'s restore-compatibility break: a pre-0.8.1
persisted `after` deadline is now silently dropped, not demoted, on restore
against this commit — anyone restoring an 0.8.0-era snapshot across the
upgrade should be warned in the same note that documents the `#203` fix.

Thank you for ten rounds of this. The fix-quality trend over the last three releases — root-cause fixes, both engines, both spellings, with pinned regression tests — is the reason we are able to move to row 8.
