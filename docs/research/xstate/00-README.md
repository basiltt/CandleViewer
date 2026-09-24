> **ADOPTED — pin `xstate-statemachine==0.9.1`.** Owner decision 2026-09-24: full adoption, no in-house shim,
> no dual-runtime harness, executed exclusively via `cv.statechart.factory`. `ADR-0016` is **Accepted**. See
> `docs/plan/29-statechart-adoption-plan.md` and `CONSTITUTION.md` C-2.22 for the binding rules.

> ## Round 14 — tag `v0.9.1` = `45bb7f3` (tree `main` @ `801eacd`), 2026-09-24 — **ADOPT WITH CONSTRAINTS — decision-table ROW 8 (up two from row 6)**
> 10 issues verified: **all ten closed (#239–#248)**, 0 partial, 0 not-fixed, the fifth consecutive clean round. Suite **3601 passed, 13 skipped, 92.93 %**. **0 true regressions.** The wheel equals the tag (42/42), sha256 `d832d4d9…2687162`, and the **PEP 740 attestation verifies OK**. **Library board: 0 Blocker · 0 High · 1 Medium** (R14-01: `re_mint()` type/src override re-targets a completion; downgraded from High because only in-process misuse reaches it; mitigated by `CV-C68`). Not row 9: BENCH-2 is 380.9 against 2,000 ev/s (architectural, ours), BENCH-1 was not re-measured, and BENCH-6 is met at p99 92.2 ms against 100. Still ours: the R14-03 chart fixes (3 Blockers) and B8 CD03 (High). **Pin: `xstate-statemachine==0.9.1`.** Full verdict: `79-r14-final-readiness-verdict.md`. Drafts (NOT posted): `issues/post-v0.9.1/`.

> ## Round 13 — tag `v0.9.0` = `91bd979` (tree `main` @ `e3a1f22`), 2026-09-23 — **ADOPT WITH CONSTRAINTS — decision-table ROW 6, and row 9 is now ONE ISSUE away**
> 11 issues verified: **all eleven FIXED (#225–#235), 0 partial, 0 not-fixed, 0 regressed-on-one-axis** — the **fourth consecutive round** where every fix landed on every axis it claimed, and the **first in thirteen rounds whose input set contained ZERO "fixed, but…" rows**. Two fixes (#231, #235) landed **stricter than the issue asked for**. **The headline is a correction to ourselves, not a finding against the library: BENCH-6 was never being measured with the right tool.** `bench_c_timers.py` does not reproduce upstream's "N busy machines" loaded-timer scenario, so five rounds of "174.4 ms, still missed" measured a question nobody asked. Re-run on **THEIR** `benchmarks/production_characteristics.py --quick` §2, ten runs on an idle host: **min 52.1 / p50 53.4 / p99 55.8 / max 55.8 ms against a 100 ms bar — every run under, ~44 ms headroom, spread 3.7 ms.** Round 12 read a median of ~110 ms on the same unchanged tool and three round-13 submissions disagreed with each other (71.0 / 87.5 / 97.9) — chased down to **host load, not library variance**. **So `CV-C12`, the `after` ban that has stood since round 4, RETIRES to `CV-C12′`** (coarse timeouts and ≥250 ms-tolerance deadlines permitted; hard deadlines and all algo timing stay on the external `MonotonicScheduler`), conditional on re-measuring on target hardware. **`CV-C64` also retires** — #225 replaced the inheritable ContextVar with task identity (`_action_tasks`), so a worker outliving its action and the `ensure_future` hand-out are ordinary external traffic (`worker_send='ok'`, `chain_trips == 0`) while the genuine in-step await is still refused with `ReentrantWaitError`; the prohibition drops to a lint. **And `CV-V08` retires: 0.9.0 IS on PyPI** — the environment briefing is stale. We unpacked the wheel and byte-compared **all 42 `.py` modules** against the tag: **0 differ, 0 missing**, sha256 `018505a1b5e7ef1d53c6a820aa680541e87bf2b5b7ad0069e13bae12256c7c0c`. **The published artefact is the reviewed artefact**, so the vendoring caveat carried since 0.8.0 is gone and the pin is a plain `xstate-statemachine==0.9.0` with a hash-checked lock. Three constraints retired in one round is the most this programme has ever returned to the library's credit.
>
> **The library board reads 0 Blocker · 1 High · 3 Medium · 6 Low.** The High row re-opens after one round empty, but not from damage: **`R13-01`** — `Interpreter.drain_pending()` (`interpreter.py:1715`) reads only `_event_queue`, never `_priority_queue` (`:374`), while the sibling `_snapshot_pending_events()` (`:1675`) deliberately includes the lane (#107). The two durability views of the same interpreter disagree and the one whose docstring promises **"every accepted-but-unprocessed event"** is the lossy one. The "harmless, they stay queued" defence fails: `_teardown()` calls `_priority_queue.clear()` (`:1635`), so the documented `drain_pending()` → persist → `stop()` recipe **permanently destroys** fired `after` timers, invoke completions and `send_priority()` traffic. Reproduced on a **live async interpreter, no snapshot, public API only**, and the issue body's repro was executed verbatim before filing (exit 0): `pending_events ['P1','P2','I1','I2']` vs `drain_pending ['I1','I2']`, lane empty after `stop()`. Pre-existing in the async engine — **#233 is what made it engine-dependent**, by correctly fixing the sync side. Held at High not Critical because the documented alternative (`get_persisted_snapshot()` then `stop()`) is correct. **`R13-02` (Medium)** is the other half of #230: `on_interpreter_start` **never fires on a restored interpreter**, on either engine, via either registration route, because both `start()` implementations `return self` from the resume branch (`interpreter.py:624`; `sync_interpreter.py:347`) **above** their plugin notification loop (`:663-665`; `:388`). `on_interpreter_stop` still fires, so a lifecycle plugin observes an **unbalanced stop-without-start** — spans leak, "actor came up" audit records vanish. Two earlier "that's documented resume semantics" arguments (`CV-V03`, and the `R13-07` framing) were **overturned this round on the documentation's own words**: `plugins.md:175` says the hook fires "when `start()` is called", and `start()` is the library's own documented way to resume a restored actor.
>
> **Suite 3577 passed, 13 skipped, 15 warnings, 597.15 s, coverage 92.86 %** (bar 90). **Zero library regressions** across a 175-check gate (136 PASS / 39 FAIL / **0 ERROR**) and a 534-script historical sweep with **0 timeouts**; the two `PASS→FAIL` movements are both stale repros asserting pre-0.9.0 behaviour, and 13 previously-failing artefacts now pass. **Row 9 (ADOPT, unconstrained) was genuinely in reach and is missed on exactly one row: `R13-01`.** Every benchmark threshold is met, every library Blocker we ever filed is closed, all Medium are triaged — a single upstream commit draining `_priority_queue` before the inbox would empty the High row and carry row 9 immediately. **Row 6 applies instead: ADOPT with constraints**, with `R13-01`'s mitigation mechanically enforced as **`CV-C65`** (persist via `get_persisted_snapshot()`, never `drain_pending()`; treat any drain result as a lower bound) plus a contract test.
>
> **The board has inverted, and that is the round's real finding.** The library carries **0 Blockers and 1 High**; **we** carry **3 Blockers and 1 High** — `R13-13`/`R13-18` (B16 parallel-region revocation and its missing re-enter audit), `R13-14` (B18: our opt-in root `onUnhandled:'error'` turns a guard-denied RELEASE into a permanently bricked kill switch), `R13-15`/`R13-16` (B11: a guard ranked ahead of its own action reads pre-action context, exactly as XState v5 and SCXML specify, and gap telemetry goes dark precisely while degraded). **Every one is config-only, every one has a fix proven green 11/11 on this exact build in both spellings, and in every case the engine is spec-correct and the defect is our chart.** Plus `R13-21`, a **harness error of ours that had been masking the #225 probes**: our `Stub.mk_a` wrapped every action in a plain `def`, which silently **drops the coroutine** an `async def` action returns — never awaited, never run, no error. Only `-W error::RuntimeWarning` surfaced it. New **`CV-C67`**: register coroutine functions directly, never behind a sync wrapper. Thirteen rounds in, **the remaining risk in this adoption is ours to discharge, and all of it is mechanical.**
> Full reasoning, the BENCH-6 distribution, the decision-table walk and the FINAL mandatory configuration: `74-r13-final-readiness-verdict.md`. Drafted (NOT posted) upstream comments and two new issues with verbatim-verified repros: `issues/post-v0.9.0/`.

> ## Round 12 — main @ `de2da4e` (pre-0.8.1), 2026-09-23 — **ADOPT WITH CONSTRAINTS — decision-table ROW 8 (UP TWO from row 6; level with round 10)**
> 5 issues verified: **all five FIXED (#218–#222), 0 partial, 0 not-fixed, 0 regressed-on-one-axis** — **the third consecutive round where every fix landed on every axis it claimed**, both engines and both service spellings, and the **first in which a majority (3 of 5) carries NO scope residual at all**. Post-refutation the **library** board is **0 Blocker · 0 High · 3 Medium · 6 Low** — **the High row is empty for the first time since round 10**. **Round 11's regression is fully reversed, and reversed AT THE MECHANISM:** R11-04 (the single open High, `_timer_handles` growing 1.00 handle per `raise(delay=)` beat for ever, **+455 MB / 24 s at 200 machines**) is closed by **#218** — a 200-beat heartbeat holds **peak 1 handle** on every engine/kind cell, a 500× arm/cancel storm peaks at **0** with no double-release, `stop()` releases, and the soak that read **+753 MB** last round now reads **RSS Δ 0.00 MB over 93,168 beats** at `handles_max_per_machine = 1`. **#219 is exact and correctly NARROW** — in-step self-await refused on **both** engines and `start()` returns (which also closes round-11's R11-06 *silent permanent* `start()` deadlock), cross-interpreter `wait=True` resolves in both directions, **100/100** concurrent deferred receipts resolve with no hang and no spurious refusal. **#220 is SOUND AND COMPLETE, both halves tested with POSITIVE CONTROLS** — **638/640** injected typos caught at up to **11/11** nesting levels with path-named did-you-means, **0 false positives** on 400 valid charts generated from the full documented grammar, `x-`/`meta`/`description`/`tags` accepted at every level. **#221 is exact — 640/640** property cases survive 1–4 restore→re-persist compaction hops **without `start()`** with `remaining_ms` and `send_id` **byte-identical at every hop**, then fire exactly once. **#222 is correct** — the latch survives benign events that erase `last_error`, `clear_chain_error()` clears it and keeps the count, `on_chain_budget_exceeded` fires exactly once per trip including settle-budget trips, and `chain_trips == 0` on every happy path across all 20 charts, both lanes. **THE MEASUREMENT DEBT SPLIT — one paid, one not.** **PAID: the full suite completed for the first time in four rounds — 3545 passed, 13 skipped, 0 failed, 92.87 % coverage, measured AT the commit under test**, so decision-table row 2 no longer rests on a one-commit-stale carry-over; hash-seed determinism **59/59 at `PYTHONHASHSEED=1` and 59/59 at `=2`**; the diff **weakens no test** (`+794/−1` lines, no `xfail`, no `skip`; the one test edit *strengthens* a #219 pin). **NOT PAID: BENCH-6 (loaded timer drift) is UNMEASURED for a FIFTH consecutive round** — `bench_c_timers` timed out again including on a reduced-parameter retry, and `bench_h_candleviewer_budgets` timed out with it, so **BENCH-1 and BENCH-2 are unmeasured too**. **ZERO true regressions** across **168 gate checks** (128 P / 40 F; **six new checks, all PASS**) and a **573-script sweep** (476 P / 94 F / 3 T) — the **sixth consecutive round**; all 11 PASS→not-PASS deltas re-run **×5 serially**, of which **nine are harness/contention false FAILs** and two are superseded oracles (`R11-09` by **#222**, which documents `last_error` as the per-step read it always was; `R11-07` now fails **precisely because the defect is gone**). **SUPERSEDED-BY-#219: ZERO scripts — and the absence is the finding.** A scan of all 573 scripts and every failure tail finds **no script that raises, catches or mentions `ReentrantWaitError`**; our ≈30 `wait=True` call sites all await from *outside* an action, and the three plausible determinism-track candidates were individually audited. **Did #219 require any change to OUR catalogue actions? NO — zero, verified POSITIVELY across 573 scripts and 20 charts, not assumed** — and that is **CV-C25 (no external `send()` from inside an action, since round 5) doing its job, i.e. anticipation, not luck**. **Did #220's recursion reject any of OUR catalogue JSON? NO — there is no rejection to adjudicate**: all **20/20** charts build clean, **0 warnings, both lanes**, with **both controls positive** (planted nested typos refused 40/40 path-named; a full valid-key grammar accepted with 0 findings) — which **retroactively establishes that nothing in B1–B20 was ever silently dropping an entry action or a transition**, validating the contract results of rounds 4–11. **Refutation moved every Blocker/High candidate DOWN and NONE UP, for the fifth round running:** two Blockers **REFUTED outright** (**R12-02** — the forged-`"version":2` upcast mint, killed by its own control: a plain v3 blob writing `configuration`/`context` verbatim reaches the **identical** outcome, and the proposed `minimum_version=3` mitigation refuses the forgery while leaving the trivial path open, **proving the trust boundary — not `upcast` — is load-bearing**; merged sources **D11-fuzz-1, D11-semantics-1 and R11-01 fall with it**; **R12-03** — engine-event provenance forgery, where **no vector uses only the public API**), one Blocker **DOWNGRADED to Low** (**R12-01** — the `engine` flag **is** consulted on the `scheduled_sends` path, so the forged record restores as a public `Event` with `e.data == {}` and the payload never arrives; only a narrow `_admit_restored`-bypass strict-parity gap survives). **Fourth consecutive round in which a provenance Blocker died on the same control probe.** **The row-deciding call, argued in the open: DE-L1/Q-1 — #219's guard rides an INHERITABLE `ContextVar`, so the DOCUMENTED `ensure_future` escape hatch is refused whenever the spawning action yields again, and a background worker born in an action is refused even 300 ms after the machine goes idle — resolves at MEDIUM, not High**, on four grounds: every refused shape has a deterministic documented alternative we already mandate, the failure is **loud and immediate** (every High in this study has been *silent*), it is **strictly safer than the silent `start()` deadlock it replaced**, and our corpus contains **zero** instances. **Row 9 is REFUSED explicitly and on the record: BENCH-6 is not *met*, it is *unmeasured*, and a row requiring all thresholds met cannot be reached by absence of evidence.** **ROW 8 MEANS WHAT IT MEANT IN ROUND 10: every remaining constraint is an architectural consequence of OUR OWN benchmarks, not containment for an open library defect.** **CONSTRAINTS — the first retirement in this study driven by a defect being FIXED AT THE MECHANISM: CV-C47 RETIRES** (both grounds closed — R10-03 by #212, **R11-04 by #218**) **and CV-C61 RETIRES with it**; the handle-count gauge **survives as telemetry** under CV-C28′ because it is what would detect a recurrence. **CV-C12 (`after` banned) STANDS UNCHANGED** — its ground is BENCH-6, and **#218 fixed a handle-RETENTION defect while saying nothing about DRIFT UNDER LOAD**; retiring it on #218's strength would answer a timing question with a memory measurement. **CV-C52 RE-LABELLED: `minimum_version=3` is HYGIENE, NOT A SECURITY CONTROL** (R12-02 proves it). **CV-C51 and CV-C59 become AGREEMENTS WITH THE RUNTIME rather than substitutes for it** — #219 and #222 now enforce what they assert. **NEW: CV-C63** (chain-trip durability is the wrapper's job — the latch is process-local and a restart silently resets "this machine discarded work" to zero) and **CV-C64** (no action may await *or hand out an `ensure_future` receipt for* a `send(wait=True)` on its own interpreter; **run this lint BEFORE upgrading past `c78ce99`** — #219 is a deliberate breaking change; covers the `def`-lane unawaited-`_Awaitable` shape too). **Net: 2 retired, 2 new, 62 standing — the count is flat and the CHARACTER changed.** **RELEASE READINESS: would we pin a tag cut at `de2da4e`? YES — unreservedly, with NOTHING required to land first. RECOMMENDATION: CUT AND TAG 0.8.1 AT THIS COMMIT.** One thing must ship **with** the tag: **bump `__version__` to 0.8.1 in the same commit** — wrong for **twelve consecutive rounds**, harmless while unreleased because we key on the commit, but a *released* build with a wrong version string is a **distributed** problem that cannot be re-cut quietly. Release notes must put **#219's breaking change at the TOP, not inside the fix list**. **What still blocks the order path is OURS, for the second round running:** **R12-13** (B16 — elevation outlives the session; 12/12 lanes fail; **fix CORRECTED this round — the root hoist alone fixes only 9/12 because the deeper `elevated.on.REVOKE` handler outranks the root arm, so the region-level handler must ALSO be deleted**), **R12-14** (B18 — one guard-denied `RELEASE` under `onUnhandled:"error"` **bricks the kill switch**; the next *authorised* release is accepted by `send()` and silently dropped; fix proven 6/6), both **Blocker, config-only, open SEVEN rounds**, plus **R12-15** (B19 — operator cannot clear a stale lockout; **High**, fix proven in both lanes). **Six open items and NOT ONE IS UPSTREAM** — the three chart defects, the unshipped linter/`tests/xstate_contract/` (G-P3-3, still the single gating condition), and the three unmeasured benchmarks. **Trajectory: 4 Blocker · 8 High (r5) → 0 · 2 (r9) → 0 · 0 (r10) → 0 · 1 (r11) → 0 · 0 (r12).** `run_gate.py` updated: **added `issues/verify-main-de2da4e` (kind `verifyM9`, 7 scripts, baseline 7/7 PASS — verified live, 6/6 rows green)**, plus an explicit **`RETIRED_OR_REWRITTEN`** register that prints on every run (the `_RETIRED_206` rename worked — round 12 spent **zero** triage on it). Verdict: `69-r12-final-readiness-verdict.md`; regression: `65-r12-regression.md`; suite+bench: `66-r12-suite-bench.md`; diff review: `67-r12-diff-review.md`; refutations: `65-r12-01-refutation.md`, `68-r12-14-refutation.md`; refuted records: `issues/post-de2da4e/refuted/`; drafts: `issues/post-de2da4e/` (**not posted**).

> ## Round 11 — main @ `c78ce99` (pre-0.8.1), 2026-09-22 — **ADOPT WITH CONSTRAINTS — decision-table ROW 6 (DOWN from row 8)**
> 5 issues verified: **all five FIXED (#212–#216), clean, 0 partial, 0 not-fixed, 0 regressed-on-one-axis** — **the second consecutive round where every fix landed on every axis it claimed**, both engines and both service spellings. Post-refutation: **0 Blocker · 1 High · 4 Medium · 5 Low**. **Refutation moved every Blocker/High candidate DOWN and none up, for the fourth round running:** of five candidates, **three were REFUTED outright** (**R11-01 Blocker→Low doc nit**, **R11-03 High→None**, **R11-05 High→none**), **one DOWNGRADED High→Low** (**R11-02**), and **one survived at High** (**R11-04**). **The two candidates the round's framing pointed at hardest — the security ones — are the two that did not survive contact with a control probe.** **ZERO true regressions** across the full gate (163 checks, exit 0) and a **527-script sweep**; the **single stable PASS→FAIL delta is OUR OWN test encoding the #206 rule that #212 deliberately reverses** (`206_delayed_selfsend_charged.py`, **retired from the gate**). **Round question 1 — did #212 re-open a bounded-cycle class? NO**, on three independent lines: a purpose-built collateral-unboundedness probe found no previously-bounded shape that became unbounded (both lanes, watchdogs); R11-05 is refuted because plain **`after:` at the same sub-ms delays behaves identically on the same charts** and has been exempt from `maxIterations` since long before #212 — the reversal opened **no escape**, it achieved **parity** with a path the budget never bounded by design; and the sweep is otherwise delta-free. **Round question 2 — did snapshot v3 / the v2-upcast-as-engine-minted rule re-open the #195/#203 forgery boundary? NO.** Both candidates were filed at Blocker/High and **both died on controls**: an attacker who can edit `"version"` can equally edit `state_ids` and **land in the target state with no event forgery at all**, `from_snapshot` is a **documented trusted-input boundary** (#205 — `machine_hash` is a fingerprint, *explicitly not a MAC*), and R11-03's control V1 — the only vector reachable from the **public API** — is **correctly refused with `UnknownEventError`**. **Third round running that a provenance Blocker was refuted by our own probe → adopted as a TRIAGE PRECONDITION: any blob-write finding must first be tested against "what does the same writer achieve with `state_ids`/`context` alone?"** **The one thing that costs a row: #212 opened no *semantic* hole but made a latent *resource* defect unbounded.** **R11-04** — `_timer_handles` retains **1.00 handle per `raise(delay=)` beat, for ever**, on both engines and both kinds (`_schedule_send` keys under the **machine** id; the only pruner pops by **state** id on state exit; the `after:` path keys by state id and is **flat**): **+455 MB / 24 s at 200 machines, strictly linear, no plateau**. Capped at ~12 entries before #212 only because #206's trip killed the cycle first. **No usage bounds it** — id reuse, explicit `cancel(sendId)`, 250 ms period and a never-exiting self-loop all measure 1.00/beat. **One line per engine to fix.** It is contained by **CV-C47** — a lint we wrote last round against a *different* finding — which is the entire difference between **row 6 (ADOPT)** and **row 7 (DEFER)**. **Row 8 → row 6 is a real regression**: last round's constraints were architectural consequences of our own benchmarks; one of them is now containment for an open library defect. **What landed, and it landed exactly:** #212's parity with `after:` is **measured, not asserted** (200 machines × 1 ms ping-pong / 10 s → **0 trips, 0 drops, 200/200 beating**; 2000/2000 livelock-fuzz cells clean; zero-delay cycles still trip); **#213's v3 round-trip is exact — 600/600** with the right `remaining_ms` (±0.5 ms) and `send_id`, firing **not early, not late, exactly once**; #214's strict-on-restore works for `pending_events` and its v2 upcast **closes round 10's R10-05b migration cliff**; #215's lap parity holds and 100 concurrent `start()`s settle in 0.01 s; **#216 is flawless where it looks** — 47/47, 120/120 and 200/200 mutations caught with a correct did-you-mean. **All four surviving Mediums are scope/composition gaps, not failures of the mechanism that shipped:** **R11-06** (#215's `_descent_done` gate — an entry action awaiting its own receipt hangs `start()` **forever, silently**, `last_error=None`/`running`/legal configuration; proven causal against a gate-pre-opening subclass with **library source untouched**), **R11-07** (#216 checks the **root dict only** while `KNOWN_MACHINE_KEYS` is overwhelmingly *state-level* names — **0/120 nested typos caught, and no WARNING either**; `{"entryy":…,"onn":…}` builds a clean machine with no entry actions and no transitions), **R11-08** (restore→re-persist **without `start()`** drops every armed self-send — #213's own failure one hop out, exactly what a journal-compaction job does), **R11-09** (a `RunawayChainError` trip reaches **only `last_error`** and **one benign event erases it**; 6/40 `def` and 8/40 `async` post-mortems on a **permanently inert** machine read healthy — it produced **99 false violations** in our own harness before we latched the read). **Contracts: 20/20 LIBRARY-GO, ZERO library defects across all four groups, both spellings — second consecutive round**; B1–B5 **356 checks / 0 FAIL**; **`strictConfig: true` now mandatory on all 20 machines, 0 unknown root keys** — but its value is ~95 % unrealised until R11-07's recursion lands, since our typo surface is ~200 state nodes. **What blocks B16/B18 is still OURS and now unambiguously so: C-04 and C-07b, open SIX rounds, both refuted as library defects, both fixable in config alone.** **Measurement debt is the largest open risk:** the full suite did **not** complete for the **third consecutive round** (~4 % reached, 0 failures) so **row 2 rests on round 10's one-commit-stale 92.78 %**, and **BENCH-6 is UNMEASURED FOR FOUR ROUNDS** while **CV-C12 (`after` banned) stands on it** — a constraint whose ground has not been re-measured cannot be retired. **CV-C48 and CV-C45's stripping clause RETIRE** (#214's upcast closed their ground); **CV-C49 REWRITTEN** (#213 persists the debt; R11-08 gives it the opposite hop); **CV-C47 STANDS, WIDENED, and is now LOAD-BEARING** — its R10-03 ground is gone and R11-04 replaced it, which is exactly how a constraint avoids rotting; **new CV-C51…CV-C62**. **`raise(delay=)` rules TIGHTEN rather than relax under #212** — the reversal that made it legal is the same reversal that made it leak. **Would we pin a tag cut at `c78ce99`? YES**, in preference to `0.8.0` and to `19cb1f1`, **with CV-C47/CV-C61 enforced in CI** — `19cb1f1` leaks too, merely capped because a different defect kills the cycle first. **Phase 3 CONTINUES**; the binding constraint is now unambiguously our own work (the CV-C5x build-out, C-04, C-07b), not the library. **Trajectory: 4 Blocker · 8 High (r5) → 0 · 2 (r9) → 0 · 0 (r10) → 0 · 1 (r11).** Verdict: `64-r11-final-readiness-verdict.md`; register: `63-r11-findings-register.md`; refutation: `64-r11-04-refutation.md`; refuted records: `issues/post-c78ce99/refuted/`; drafts: `issues/post-c78ce99/` (**not posted**).

> ## Round 10 — main @ `19cb1f1` (pre-0.8.1), 2026-09-22 — **ADOPT WITH CONSTRAINTS — decision-table ROW 8 (up from row 6)**
> 8 issues verified: **all eight FIXED, clean, 0 partial, 0 not-fixed.** **The first round in ten where every fix landed on every axis it claimed** — both engines, both service spellings, no "fixed on one axis only" residual anywhere in the corpus. Post-refutation: **0 Blocker · 0 High · 5 Medium · 7 Low** — **the High row is empty for the first time.** Refutation moved **all three** Blocker/High library candidates *down* and **none up** (**R10-01 Blocker→Low**, **R10-02 High→REFUTED outright**, **R10-03 High→Medium**); on the contract side **R10-C1 and R10-C2 are refuted as library defects**, **R10-C3 High→Medium**, **R10-C4 High→REFUTED (Low)**. Trajectory: **4 Blocker · 8 High at round 5 → 0 · 2 at round 9 → 0 · 0 now.** **Both round-9 Highs closed at the right sites:** **#203** gates `after` selection on `is_system_event` (`base_interpreter.py:4624`) — the discriminating control that made R9-02 a High, a public `AfterEvent` firing a 60 s timer instantly at the **default** `strict=False`, is refused on both engines; **#204** moves invoke arming into the settle pass per SCXML §6.1 `statesToInvoke`, closing the roll-forward half on **both engines and both kinds** (`LD-01` 3 leaks → **0/6**, B6–B10 `def` lane 51/52 → **52/52**, drives 13/14 → **14/14**, and `167 rollback_reinvoke_spin` — recorded last round as a permanent expected-FAIL — now **PASS ×5/5**). **The owed measurement is discharged:** the full suite finished after the bench agent's bound — **3505 passed, 13 skipped, 0 failed, 566.57 s, coverage 92.78 %** (`suite-19cb1f1.log`), above the library's own 90 % floor and up from 92.70 %; **decision-table row 2 is now not-triggered on measured evidence rather than inference**, which was round 9's single largest open risk. **The round's one correction: R10-01 was filed as a Blocker on seven engine-event forgery vectors and we refuted it ourselves** — every vector reproduces, but they partition into Class A (in-process Python, *strictly weaker than the premise*: a plain registered action writes context arbitrarily and a live `Interpreter` exposes `_enter_states`/`_exit_states`) and Class B (blob-write — we tested rather than accepted the claim, and **a hand-edited snapshot with no event forgery at all** restores to `{'z.late'}` with context `{'n':999}`); the boundary #195/#203 actually target holds in every probe. **R10-02 refuted outright:** a self-targeting `onDone` is an **internal** transition by contract (XState v5 default, `reenter:true` the opt-in, documented three times); with `"reenter": true` every lane re-arms to `maxIterations+2` and the #207 stranded hook fires. **Contracts: 20/20 clean on both spellings, ZERO library defects across all four groups** — a first. **CV-C46 and CV-C45's send-side clause RETIRE; CV-C32 falls back to a performance/liveness rule (re-grounded on R10-D2, not R9-04); new CV-C47…CV-C50 + CV-C4x.** **Phase-3 order-path shim retirement MAY BEGIN** — both gating Highs closed and Phase 3's coverage precondition met at 92.78 %; the remaining three acceptance conditions are **entirely ours** (five green nightlies, lint+tests, two-week canary). What blocks B16/B18 is still **ours** and now unambiguously so: **C-04 and C-07b, open five rounds, refuted as library defects this round by corrected charts that pass on both engines and both spellings.** Verdict: `59-r10-final-readiness-verdict.md`; register: `58-r10-findings-register.md`; refutations: `59-r10-01-refutation.md`, `59-r10-c3-refutation.md`, `59-r10-c4-refutation.md`, `55-r10-c2-refutation.md`, `issues/post-19cb1f1/refuted/`; drafts: `issues/post-19cb1f1/` (**not posted**).

> ## Round 9 — main @ `f28719c` (pre-0.8.1), 2026-09-22 — **ADOPT WITH CONSTRAINTS (all four families, order path included)**
> 12 issues verified: **11 fixed in code (9 clean, 2 narrower than claimed), 1 partial (#197), 0 not-fixed, 0 documentation-only.** Post-refutation: **0 Blocker · 2 High · 5 Medium · 8 Low** — refutation moved **3 of 5** Blocker/High candidates *down* (**R9-01 Blocker→Low**, **R9-03 High→REFUTED outright**, **R9-05 High→Medium**) and **none up**. Best position in nine rounds; the trajectory is **4 Blocker · 8 High at round 5 → 0 · 2 now**. **Round 8's sole Blocker R8-01 is closed:** #192 taught the priority lane's *drop* site the provenance rule its *charge* site already knew — self-issued sends charged, external ones shielded, verified on both engines and both service kinds and on the real B18 kill switch (**12/12 presses accepted, 0 shed, press pre-empts the chain**). That was the one thing round 8 said would flip the verdict, and it flipped it. **The round's one sentence: #195 built the right mechanism and applied it to two of the three event families it minted a class for** — `base_interpreter.py:4523` still selects `after` on the **public exported** `AfterEvent`, never on `_EngineAfter`, unlike the `DoneEvent`/`ErrorEvent` branch eight lines below (**R9-02**, one line). The two open Highs are **R9-02** and **R9-04** (a `def` service armed by a transition an `always` rolls *forward* is still submitted — 3/6 lanes leak — contradicting #193 and `production-characteristics.md:97` verbatim, while `test_always_rollforward_matches_sync` **pins the leaking behaviour**, so the green suite certifies the inverse of the published claim). **Both are mechanically contained by constraints we already lint** (CV-C45 widened, CV-C32 + new CV-C46), which is decision-table **row 6**, not row 7. **The service-kind axis is flat across every battle track for the first time** — round 8's parametrisation ask worked. Contracts: **20/20 build clean on both spellings**, B1–B5+B18 **138/138 both lanes**, B16–B20 all LIBRARY-GO; the only contract FAIL is R9-04. **Two corrections to our own reporting:** #195's send-side gate *does* refuse a hand-built `AfterEvent` under `strict` (our register overstated it — only the snapshot vector survives), and the `TestAsyncRollbackRearmCycleBounded` "regression" is **not one** (both lanes plateau at exactly `maxIterations`+2 = 1003; the test reads at 0.6 s when `def` converges at ~1.0 s). **Owed measurement:** the full coverage run did not finish inside the time bound — recorded as open, not as a pass. **CV-C43 and CV-C31″ retire; CV-C45 widened; new CV-C46.** What blocks B16/B18 is still **ours** (C-04, C-07b) — for the first time the binding constraint on our order path is our own catalogue, not the library. Verdict: `54-r9-final-readiness-verdict.md`; register: `53-r9-findings-register.md`; drafts: `issues/post-f28719c/` (**not posted**).

> ## Round 8 — main @ `6db65d8` (pre-0.8.1), 2026-09-21 — **DEFER (order path) · GO (non-order paths)**
> 16 issues verified: **15 fixed in code (10 clean, 5 narrower than claimed), 1 documentation-only (#174), 0 not-fixed** — the first round with no not-fixed row. Suite **3 457 passed** plus one load-sensitive flake, coverage **92.70 %**. **Zero true PASS→FAIL gate regressions** (the 2 deltas are *our* stale `machine_hash` fixtures, correctly superseded by #185). Post-refutation: **1 Blocker · 3 High · 7 Medium · 4 Low** — refutation moved **3 of 6** Blocker/High candidates *down* (R8-02 Blocker→High, R8-04 High→Medium, R8-06 High→Low), **none up**. Best position in eight rounds. **The round-7 ask landed and it worked:** `tests/test_round7_findings.py` now parametrises over `KINDS = ("def","async def")` and the async livelock fuzz went **58/120 RUNAWAY → 0/120**, a 500-config × 2 spellings × 2 engines sweep found **0 hangs / 0 silent runaways / 0 lap mismatches**, `maxIterations` is a real bound again and lane-independent (2/5/100 → 4/7/102 calls, `max+2` exactly, identical cell for cell), and the B18 kill-switch storm that hit **3 547 calls in 3.0 s** now plateaus at **1 002** with `last_error = RunawayChainError`. **Both round-7 Blockers are closed.** **The round's one sentence: the provenance rule #180 introduced was implemented on one side of the ledger** — `_deliver_priority` charges by *who issued* (`interpreter.py:2342-2389`) and sheds by *queue position* (`:1598`), so a priority event issued from an action livelocks unbounded and unobservably, while an external one at an already-tripped chain is silently destroyed (**R8-01**, the only Blocker, the regression surface of #180, **one function's worth of work**). Decision-table row 4 wins; row 6 (ADOPT WITH CONSTRAINTS) is **otherwise satisfied** — open-High is 3 against a bar of 5, each mechanically mitigated. **B16–B20 are now all LIBRARY-GO**, and what blocks B16/B18 is **ours** (C-04, C-07b). CV-C38/CV-C31′ retire; CV-C42 widened; **new CV-C43…CV-C45**. Verdict: `49-r8-final-readiness-verdict.md`; register: `48-r8-findings-register.md`; drafts: `issues/post-6db65d8/` (**not posted**).

> ## Round 7 — main @ `221ce7c` (pre-0.8.1), 2026-09-20 — **DEFER (order path) · GO (non-order paths)**
> 12 issues verified: **7 fixed, 2 partial (#167/#168 — one defect), 2 documentation-only (#122 correct-as-designed — we withdraw our own reopen; #174 open), 1 not-fixed (#175 Case D)**. Suite **3 418/0** plus one non-reproducible flake, coverage **92.64 %**; `interpreter.py` 89 % → **91 %**. **Zero true PASS→FAIL gate regressions**, but three regressions were introduced by this round's own fix work and the gate cannot see any of them. Post-refutation: **2 Blocker · 4 High · 6 Medium · 8 Low** — refutation moved 3 of 8 Blocker/High candidates *down*, none up, and **refuted one outright** (R7-04's budget-renewal cause was killed by our own follow-up evidence). **The round's one sentence: WHO issued an event has been replaced by WHEN it arrived** — self-generated work escapes the budget on the `async def` completion lane (R7-01: 28 108 service calls vs 23 for the identical chart with `def`, one variant settling into an **empty configuration** reporting success), while external work is charged on the priority lane (R7-02: 751 of 1 500 external sends dropped as `chain_budget`, control drops zero). Two lines in `interpreter.py`, opposite halves of one mistake, neither wrappable. Big win: the `send(wait=True)` hang is dead (6/6 → 0 on every ablation; 500 fuzzed cyclic configs, zero livelocks), the root snapshot refusal holds across 7 622 attempts from 8 windows, and the receipt matrix is injective — which **retires W-04a and CV-C37**. New CV-C38…CV-C42. **The highest-value upstream change is one line:** parametrise every service-invoking test over `def` / `async def` — six of our findings collapse into R7-01 and all six would have been caught. Verdict: `44-r7-final-readiness-verdict.md`; register: `43-r7-findings-register.md`; drafts: `issues/post-221ce7c/`.

> ## Round 6 — main @ `cec108b` (pre-0.8.1), 2026-09-20 — **DEFER (order path) · GO (non-order paths)**
> All 26 round-5 issues verified: **24 closed, 1 partial (#122), 1 not-fixed (#157, reopened narrower)**. Suite **3 399/0**, coverage **92.77 %** against the new 90 % floor (#163). 3 Medium regressions (`after` lateness, `stop()` receipts). Post-refutation: **2 Blocker · 2 High · 7 Medium · 9 Low** — refutation moved 6 of 10 Blocker/High candidates *down*, none up. **The round's one pattern: three of four candidate Blockers are "fixed on the engine the issue was filed against"** — `always`-into-completed-`invoke` hangs the async loop, `done.invoke.*` is exempt from the async chain budget (`interpreter.py:1427`), and `rollback` + `invoke.onDone` re-invokes ~1400×/s silently, all with the sync engine correct. **One upstream change closes all three.** Big win the other way: #142/#143 landed one legality predicate on **both** snapshot sides — torn parallel snapshots 27.4 % → **0 %** — which **retires CV-C30/CV-C27**, and #145 **retires CV-C31** (`"fail"` is safe again; `"rollback"` is now the dangerous one on the order path — CV-C31′). New CV-C35…C37. Verdict: `39-r6-final-readiness-verdict.md`; register: `38-r6-findings-register.md`; drafts: `issues/post-cec108b/`.

> ## Round 5 — main @ `3ed3099` (pre-0.8.1), 2026-09-19 — **DEFER (order path) · GO (non-order paths)**
> All 39 round-4 issues verified: 34 closed, 5 partial. No regressions; suite 3 322/0, cov 90 %. Battle re-run + 20 contract machines end-to-end found **4 Blocker · 8 High · 8 Medium · 1 Low** new library defects — three Blockers are the round-4 Blockers one layer deeper (any-leaf mid-step check misses parallel tears; no read-side legality check; nested-invoke livelock) plus `"fail"` policy reverting to source. Root need: **one configuration-legality invariant enforced on both snapshot sides**. Also 10 defects in **our own** catalogue JSON (OC-01 live `"*": defer` scaffolding disables `strict`). Verdict: `34-r5-final-readiness-verdict.md`; register: `33-r5-findings-register.md`.

> ## Round 4 — main @ `5e07ba8` (pre-0.8.1), 2026-09-18 — **DEFER (order path)**
> All 19 round-3 issues verified: 17 closed, 2 partial (#91, #99). No regressions; suite 3 276/0, cov 90 %.
> First deep battle-test (8 tracks, property/fuzz/soak/conformance) found **2 Blocker · 6 High · 18 Medium · 12 Low** post-refutation — headline: **R4-01 mid-macrostep snapshots restore as inert machines reporting healthy (45 % of interruption points)**, R4-04 non-terminating `start()`, R4-06 external events charged to chain budget, R4-07 `Receipt.deferred` id-keyed. Operative blocker is now upstream. Full verdict: `29-r4-final-verdict.md`; register: `30-r4-findings-register.md`.

# `xstate-statemachine` — evaluation summary for CandleViewer

## Verification of `main` @ `3c527b0` (unreleased 0.8.1) — 2026-09-18 — read this first

**This is the current position.** It supersedes the `5327ba6` section below,
which is retained as the previous baseline. Full verdict:
`26-verify-3c527b0-verdict.md`.

> **Identify this build by commit, never by version string.** `__version__`
> still reports `0.8.0` on commit `3c527b0` while `CHANGELOG.md` targets
> `0.8.1`. Every pin, gate baseline and CI assertion must key on the commit
> until the tag lands.

```
Gate run 2026-09-18 - xstate-statemachine main @ 3c527b0 (unreleased 0.8.1)
DECISION: DEFER (library-adoption half of ADR-0016 Part 3)
          -- CHANGED from ADOPT WITH CONSTRAINTS, CONDITIONAL at 5327ba6
          -- decision-table row 5: 7 High open (bar: <=5)
  verify (mandated config, blocking) : 33/34 pass (was 32/34 - LC-28 now PASS)
  verifyM                            : 12/15 pass (LC-07, N-3, N-8 residuals)
  repro  (defaults, informational)   : 13/34 pass
  probes                             : identical baseline, no new failures
  suite                              : 3242 passed, 13 skipped, 0 failed
  coverage                           : 90% (unchanged)
  benches                            : #43 children+1 task budget CONFIRMED
                                       (1.0 tasks/child, was 2.0);
                                       BENCH-1 armed ~2.03x (bar >=3.0x);
                                       BENCH-2, BENCH-6 still missed
  regressions                        : ONE - G-2 (provenance lost across a
                                       snapshot; the exemption rule now gives
                                       different answers either side of a restore)
  blockers open                      : none (LC-01, LC-03 FIXED-OPT-IN)
  high open                          : LC-07/#31, M-1, F-1, F-2, G-1, G-2, G-3
  new findings                       : 24 canonical (6 High, 11 Medium, 7 Low)
                                       -> 16 new issues, 8 ride-along comments
  constraints                        : CV-C01..CV-C22 (CV-C15 NARROWED;
                                       CV-C06 deferred_count clause WITHDRAWN
                                       as unsound; CV-C19..CV-C22 NEW)
  path forward                       : pre-release build. Fixing G-2 and G-3
                                       before 0.8.1 tags returns the count to
                                       5 High and row 6 applies again.
```

**What landed.** PR #83 is net-positive and **#43 is excellent**: the poll loop
is gone, the task budget is `children + 1` (1.0 tasks/child at n=2/10/50, was
2.0), `onDone` latency drops to 0.96 ms median, 1 000 spawn/complete cycles leak
nothing, and the exit-vs-completion race is handled under a ±2 ms scan. #79
makes a user event named `error.*`/`done.*` visible to `"*"`, trippable by
`onUnhandled` and rejected by `strict` — **case variants included**. #80's
`ErrorEvent` is a real ergonomics win. Suite 3 242/13/0 at 90% coverage.

**What broke.** Two features that shipped in the same release each met the
snapshot boundary without being taught about it. **G-2**: provenance is not
persisted, so a restored `escalate` event comes back as user traffic and fails a
machine configured `onUnhandled: "error"` — where the old name rule gave the
same answer either side of a restore. **G-3**: a pending `ErrorEvent` is
silently dropped by `get_persisted_snapshot()` because the inbox filter is
`isinstance(e, Event)` and `ErrorEvent` is a `NamedTuple`; a machine restores
believing the invoke never failed and no `onError` ever fires. **G-1**:
`Event.system` is a public, user-settable dataclass field that bypasses
`strict`, `onUnhandled` and `"*"` on both engines. **These are the two findings
with our name on them** — our order path is snapshot/restore-based by CV-C08.

**Why the decision moved.** Not a judgement call: the decision table is applied
in order and row 5 (`> 5 High open`) now matches on the merits — 7 open against
a bar of 5. It is a **pre-release build**; the correct response is to get G-2
and G-3 fixed before 0.8.1 tags, not to re-weight the findings. **ADR-0016 Part
1 and Part 2 (the in-house shim) are unaffected and remain the execution path.**

**M-1 still gates the order path, and its mitigation is gone.** The deferred
event's `wait=True` receipt still resolves `changed=False, error=None`, and the
`deferred_count` discriminator we specified as CV-C06's mitigation **reads `0`
at the caller's `await` point for both the deferred and the true-negative case**.
The clause is withdrawn as unsound and must be re-derived — either upstream
fixes the receipt, or `cv.statechart` obtains an out-of-band discriminator the
library does not currently expose.

**Constraint delta.** CV-C15 **narrowed** — the case-insensitivity requirement
on `E50-T05` retires, and the rule becomes "no event name with a prefix in
`ENGINE_EVENT_SHAPES`" (the only names `strict` still exempts by name). Three
new: **CV-C19** (never construct `Event(system=True)`; never trust library
provenance as a trust boundary), **CV-C20** (`cv.statechart.persistence` owns
the mailbox across a snapshot boundary — quiesce before snapshotting, reconcile
every `pending_invocations()` on restore), **CV-C21** (`onError` handlers branch
on `isinstance(event, ErrorEvent)` and read `event.error`), **CV-C22** (no
global `-W error::DeprecationWarning` in CI until G-4 is fixed).

**Postable artefacts:** `issues/post-3c527b0/` (16 issue comments, 16 new-issue
bodies, `meta-26.md`, `manifest.json`, `repro/`). **Nothing has been filed.**

---

## Verification of `main` @ `5327ba6` (pre-0.8.1) — 2026-09-18 — previous baseline

**Superseded by the `3c527b0` section above.** This section records the
verification pass against the previous `main` commit.

> **Identify this build by commit, never by version string.** `__version__`
> still reports `0.8.0` on commit `5327ba6` while `CHANGELOG.md` targets
> `0.8.1`. Every pin, gate baseline and CI assertion must key on the commit
> until the tag lands.

```
Gate run 2026-09-18 - xstate-statemachine main @ 5327ba6 (unreleased, pre-0.8.1)
DECISION: ADOPT WITH CONSTRAINTS, CONDITIONAL (unchanged in form from 0.8.0)
  verify (mandated config, blocking) : 32/34 pass - FAILs: #43, #60/LC-52
  repro  (defaults, informational)   : 13/34 pass
  probes                             : 43/51-equivalent, identical baseline
  adversarial                        : 57 purpose-built probes, 8 suites
  suite                              : 3234 passed, 13 skipped, 0 failed (was 3170)
  coverage                           : 90% (was 87% at 0.7.0)
  benches                            : BENCH-1 armed 2.43x (bar >=3.0x);
                                       BENCH-2, BENCH-6 still missed
  regressions                        : NONE
  blockers open                      : none (LC-01, LC-03 FIXED-OPT-IN)
  high open                          : LC-07/#31 (narrowed), M-1, F-1, F-2
  new defects                        : 13 (3 High, 6 Medium, 3 Low, 0 Blocker)
  constraints                        : CV-C01..CV-C18 (2 clauses RETIRED, 3 NEW)
  condition                          : E29-T10 linter + tests/xstate_contract/
                                       green. Nothing upstream blocks non-order
                                       paths. Order path also waits on M-1.
```

**What changed.** No regressions: every status delta moved in the fixing
direction, no test function was deleted and no skip/xfail was added across the
whole `v0.8.0..5327ba6` diff. The two 0.8.0-era High defects that had no
mitigation other than "don't do that" are genuinely fixed under adversarial
probing: `send(wait=True)` no longer hangs on a reused `Event` (#75, held at
500-way concurrency under three policies), and `SyncInterpreter` `after`
deadlines are reachable by `tick()` inside a running loop (#76). Nine issues are
now closable; six stay open, all narrowed.

**Two CandleViewer constraints retire outright** — the fresh-`Event` discipline
(CV-C06's reuse clause) and the gateway's duplicate event validation (CV-C14's
validation clause). The library now does that work itself.

**The catch, stated plainly.** The finding that governs the order path is
**M-1**: the two library features our order path is *mandated* to use together —
`onUnhandled: "defer"` (CV-C01) and `send(wait=True)` receipts (CV-C06) — compose
into a confident false negative. A deferred event's receipt resolves
`changed=False, error=None`: indistinguishable from "the machine looked at your
event and correctly did nothing", for an event that is parked and about to drive
its transition. Not a hang, not data loss — a gate that says *no* about an event
that is about to say *yes*, at exactly the moment the two settings are supposed
to produce a right answer.

**Nothing upstream blocks us any more.** The remaining condition is ours: MUST-09
requires the `E29-T10` linter (CV-LINT-XS1…XS12) and `tests/xstate_contract/` to
ship before the first statechart, because the two Blockers closed by opt-in
policy are closed only for a caller that sets the option. The order path
additionally waits on M-1 being fixed upstream or covered by the new CV-C06
`deferred_count` clause.

### Where to read what (this pass)

| Document | Contents |
|---|---|
| **`22-verify-main-verdict.md`** | **The verdict.** Per-open-issue dispositions, the 13 new defects, the decision-table walk, constraints CV-C01…CV-C18, the recomputed config block, and the release-readiness note for the library team. |
| `18-verify-main-gate.md` | Gate run, library suite, coverage, benchmarks, BENCH-1 recomputed with `rollback` armed |
| `19-verify-main-diff-review.md` | `v0.8.0..5327ba6` source diff review, F-1…F-11 |
| `21-verify-main-adversarial.md` | 57 hostile probes in 8 suites (`probes/main-5327ba6/`), M-1…M-6 |
| `issues/verify-main-5327ba6/*.result.md` | Per-issue re-verification, one file per LC/N id |
| `issues/comments-main-5327ba6/` | 16 verification comment drafts + the meta-issue update (**not filed**) |
| `issues/new-main/` | Eight new-issue drafts with runnable repros (**not filed**) |

---

## Re-evaluation: 0.8.0 "Fortify" (2026-09-17) — previous baseline

**The 0.7.0 study below is preserved as written and is now historical.** Its
recommendation (DEFER) was superseded by a full re-evaluation against
`xstate-statemachine` 0.8.0, commit `9bf6065`, which is in turn superseded as
the current position by the `main` @ `5327ba6` verification above.

```
Gate run 2026-09-17 - xstate-statemachine 0.8.0 (9bf6065)
DECISION: ADOPT WITH CONSTRAINTS, CONDITIONAL
  repros   : 12/34 pass unconditional; 9 verified fixed-but-opt-in; 13 stale/triaged; 0 unfixed
  probes   : 43/51 pass (was 41/51)
  benches  : 5/7 thresholds met (was 2/7) - BENCH-2, BENCH-6 still missed
  suite    : 3170 passed, 13 skipped, 0 failed
  blockers open: none, CONDITIONAL on the LC-01/LC-03 config being lint-enforced
  high open    : LC-07, LC-26, LC-38, LC-43
  new defects  : 17 (2 High, 9 Medium, 6 Low, 0 Blocker)
  constraints  : CV-C01..CV-C15
  condition    : E29-T10 linter + tests/xstate_contract/ green before the first
                 live-path statechart. Until then: DEFER on the order path.
```

**What changed.** 0.8.0 closed **all four filed Blockers** and 23 of 34 filed
issues at the default, with no configuration. Timer starvation improved 14.5x
(2530 ms -> 174.4 ms). Order-path headroom went from 1.81x to 3.17x. The library's
own suite grew from 2,805 to 3,170 tests. The two features we most needed -
`onUnhandled: "defer"` and the bounded inbox with `send(wait=True)` receipts -
scored **9/9** and **13/13** under deliberately hostile probing.

**The catch, stated plainly.** Two of the four Blockers (LC-01 action-raises,
LC-03 unhandled-events) are closed by a **per-machine policy whose default is
still the 0.7.x behaviour**. They are closed for a caller who sets the option and
open for one who does not. Because every Blocker in this register is a *silent*
failure, and an unenforced rule is not a rule, they count as closed only while the
mandated configuration is enforced by the machine-definition linter. That linter
has not shipped. The remaining gap is therefore **CandleViewer work, not upstream
work** - a genuinely different position from 0.7.0.

The mandated configuration also is not free: `actionErrorPolicy="rollback"` costs
**-22% throughput** while armed and idle, which pushes BENCH-1 back under its bar.

**New defects.** The adversarial and diff reviews found 17 findings not in the
0.7.0 register. The two High ones are both inside features this release added:
`send(event, wait=True)` **hangs forever** when the same `Event` instance is in
flight twice (receipts keyed on `id()`), and `SyncInterpreter` `after` deadlines
become unreachable by `tick()` when the interpreter is built inside a running
asyncio loop. Five are drafted as new upstream issues with runnable repros.

### Where to read what

| Document | Contents |
|---|---|
| **`17-reeval-0.8.0-verdict.md`** | **The verdict.** Per-issue table, counts, the decision-table walk, the mandatory machine configuration + CI lint rule, the 17 new defects, the updated constraints, and the upstream disposition. |
| `13-reeval-0.8.0-bench.md` | Benchmarks, the probe/repro gate run, and the new policy-cost measurement |
| `14-reeval-0.8.0-probes.md` | All 51 semantic probes, 0.7.0 vs 0.8.0, with baseline changes |
| `15-reeval-0.8.0-adversarial.md` | 11 purpose-built hostile probes (`probes/v080/`) and constraints C-1..C-11 |
| `16-reeval-0.8.0-diff-review.md` | Full `v0.7.0..v0.8.0` source diff review |
| `issues/verify-0.8.0/*.result.md` | Per-issue re-verification, one file per LC id |
| `issues/new-0.8.0/` | Five new issue drafts with runnable repros (**not filed**) |
| `issues/followups-0.8.0/` | Eleven follow-up comment drafts (**not filed**) |
| `12-challenge-register.md` | The register, now carrying a **0.8.0 status** column on all 62 rows |
| `20-adoption-gate.md` | The procedure, with 0.8.0 recorded as the new baseline |

---

## The 0.7.0 study (historical)

Everything below this line is the original 0.7.0 evaluation, unedited. Its
"Recommendation: DEFER" and "Gate status today" lines describe **0.7.0** and are
superseded by the box above.

# `xstate-statemachine` 0.7.0 — evaluation summary for CandleViewer

**Audience:** the owner. Read this file alone for the decision; everything else is evidence.

| | |
|---|---|
| **Library** | `basiltt/xstate-statemachine` 0.7.0 (commit `42612cf`), MIT, zero runtime dependencies |
| **Evaluated for** | CandleViewer (Bybit trading terminal): OMS/order lifecycle, emulated algos, rule runtime, replay |
| **Evaluated on** | Python 3.13.7, Windows, local clone installed `-e` |
| **Study date** | 2026-09-15 |
| **Recommendation** | **DEFER — adopt on a gate, not on a date** (§7) |
| **Gate status today** | 4 filed Blockers open, 20 High open, 34/34 repros still reproduce |

---

## 1. Library maturity — verbatim test results

The library's own suite, run twice on this machine:

```
=========== 2805 passed, 2 skipped, 1 warning in 569.61s (0:09:29) ============
=========== 2805 passed, 2 skipped, 1 warning in 581.07s (0:09:41) ============
```

Coverage, branch coverage on:

```
TOTAL: 6651 stmts, 697 miss, 2918 branch, 315 partial → 87% cover
```

The single warning is a deprecation notice in the CLI (`--style is deprecated,
use --template function-json instead`). Coverage lowlights, which matter because
they line up with what CandleViewer would lean on hardest:

| Module | Cover | Note |
|---|---|---|
| `cli/strategies/_shared.py` | 58% | codegen helpers |
| `cli/generator.py` | 63% | codegen internals |
| `cli/__main__.py` | 69% | CLI plumbing |
| `events.py` | 74% | small file |
| **`base_interpreter.py`** | **86%** | largest file (890 stmts); misses concentrated in **rollback, cancellation and error branches** |
| `interpreter.py` / `models.py` | 87% | |
| `sync_interpreter.py` | 91% | |

CI runs `black` + `flake8` (complexity limit 35) with `--cov-fail-under=86`.
There is **no mypy gate** despite the `Typed` classifier. The docs site is Jekyll
and its build is not tested in CI.

**Our own measurements on top of that:** 51 semantic probes (41 PASS / 10 non-PASS),
11 benchmark scripts, 8 adversarial scripts, and 34 standalone repro scripts —
all committed here and all re-runnable.

**The honest read.** 2,805 passing tests is genuinely strong process rigor for a
0.x pure-Python library, better than most OSS projects this size. But *2,805
passing tests coexist with all 34 defects in this register* — and both 0.6.0 and
0.7.0 shipped after the maintainer's own late-cycle "adversarial battle testing"
found release-blocking correctness bugs. That is a good signal about process and
a cautionary one about inferring safety from test counts. It is also precisely
why our gate is defined by repro scripts and not by a green suite.

---

## 2. What works well — and it is a lot

This is not a weak library. It is **correct where correctness is hardest**:

- **Invoke cancellation** — a state exit cleanly cancels in-flight invoked
  services; no orphan tasks (probes B4/B5).
- **Parallel and nested snapshot fidelity** — a 3-region parallel machine with a
  nested compound substate round-trips exactly (probe C4).
- **FIFO event ordering** — strictly preserved under load (bench `g7`).
- **History states** — shallow and deep history semantics are correct (B12–B14).
- **Determinism** — identical outcomes across 15 repeated runs (C8/C9/C17).
- **Actor teardown is clean** — **0.11 KB per actor** retained over 3,000
  spawn/stop cycles. No leak.
- **Memory is cheap** — a quiescent open order machine costs **1.08 KB**;
  500 resident orders cost **0.53 MB**; 10,000 live interpreters fit in ~1,055 MB.
- **Throughput is respectable** — ~30,000 ev/s single-interpreter, ~33 µs per
  transition including guard evaluation and two actions.
- **Hierarchy, parallel regions, guards, actions, `invoke`, `after`, history,
  and the SCXML-style algorithm** are all implemented faithfully and completely.
- **Zero runtime dependencies, MIT, 12,104 LOC** — small enough to read, vendor
  and fix ourselves if we ever had to.

### The one-sentence finding

> The library is **correct where correctness is hardest** and **wrong where
> wrongness is quietest**.

`LC-01`, `LC-02`, `LC-03`, `LC-07`, `LC-08` and `LC-36` are the same design
decision wearing six different outfits: **resolution and execution failures
degrade to silent no-ops instead of errors.** Invert that one philosophy — fail
loudly by default, opt into forgiveness — and most of this register evaporates.

---

## 3. Register statistics

Full register: `12-challenge-register.md` (62 deduplicated rows, each traced back
to its source probe/bench/study).

**By severity** — note the scale is *relative to a trading OMS*, not to the
library in general:

| Severity | Count | Meaning |
|---|---:|---|
| **Blocker** | 6 | Can cause financial loss or silent data corruption on the order path |
| **High** | 25 | Silent wrongness, or a hard architectural constraint forcing a design workaround |
| **Medium** | 18 | Surprising or costly; worked around at moderate expense |
| **Low** | 13 | Ergonomics, waste, maintainability |
| **Total** | **62** | |

**By type:**

| Type | Count |
|---|---:|
| Missing feature | 17 |
| Bug | 14 |
| Code quality | 8 |
| Performance | 7 |
| Semantic divergence from XState v5 | 5 |
| Improvement | 5 |
| Docs | 5 |
| Improvement (ecosystem) | 1 |

**Filing status:** 54 rows are marked for upstream filing. **34 have a standalone
issue file and a runnable repro** in `issues/` and `issues/repro/`; the remainder
are grouped under those (e.g. LC-04 under LC-02, LC-58/59/61 under LC-57).

**Duplicate check:** `gh issue list --state all` on the upstream repo returns
**exactly one issue ever filed** (#17, closed). Nothing here collides with an
existing report.

---

## 4. Top 10 blockers

Ordered by severity, then by how much each one costs us.

| # | ID | Sev | What happens | Why it is disqualifying for the order path |
|---|---|---|---|---|
| 1 | **LC-01** | Blocker | An action raises → the transition **still commits**. `third` action is skipped, but `entry_b` runs, the machine lands in `b`, `status == "running"`, nothing is raised, and `on_transition` fires **as a success**. Both engines. | We would durably persist a state that was never legitimately reached, and report it as healthy. This is the single worst finding. |
| 2 | **LC-03** | Blocker | Events with no handler in the current state are **silently discarded**. Probe C17: `send("NEW")` then three `PARTIAL`/`FILL` events all vanish — expected `filled==30`, observed `filled==0`. | Fills arriving a few ms early — routine on a live exchange feed — are dropped without a trace. Our position and the exchange's diverge silently. |
| 3 | **LC-02** | Blocker | An `always` transition with a self-target **deadlocks silently**: the guard is never re-evaluated, `is_running` stays `True`, nothing raised. Root cause is one line: `base_interpreter.py:1769` classifies *any* self-target as internal. | An iceberg slicer or retry loop parks forever while reporting healthy. Also causes LC-04 (self-transitions don't re-enter). |
| 4 | **LC-16** | Blocker | `sendTo` cannot address an actor by its `invoke` `id` or `systemId`; the event is silently dropped. A duplicate `systemId` silently replaces the previous actor. | Per-leg messaging in multi-leg algos cannot be addressed reliably. |
| 5 | **LC-43** | High | Cross-thread `send()` **silently loses every event** — returns an un-awaited coroutine with no error. | Any UI-thread or worker-thread submission is a no-op that looks fine. Trivially easy to write by accident. |
| 6 | **LC-26** | High | `after` timers degrade catastrophically under load: a 100 ms timer fires **~2.53 s late** (p95) with 500 busy interpreters — and the absolute error is *constant regardless of the requested delay*, the signature of event-loop starvation. | TWAP slicing and chase repricing drift by seconds exactly during a volatility burst, when it matters most. |
| 7 | **LC-08 + LC-07** | High | An unknown target is never validated and is a silent runtime no-op; a relative `.child` target resolves to nothing, silently. (An unknown *action* name correctly raises at `create_machine()` — targets simply were not given the same treatment.) | Compiled rule IR deploys clean and fails open. |
| 8 | **LC-09** | High | A guard that raises is swallowed as `False`, invisible to every observer. | A *crashing* risk check and a *failing* risk check are indistinguishable, and both fall through to the permissive branch of an `or`. |
| 9 | **LC-38** | High | `SyncInterpreter` is **not single-threaded**: `after` timers run on background threads and mutate context with no locks. | Undocumented data race in the engine we would otherwise pick for determinism. |
| 10 | **LC-48** | High | No error-observability hooks at all: no `on_transition_failed`, no `on_guard_error`, no unhandled-event signal. | Makes every item above *undetectable in production*. This is what turns bugs into silent bugs. |

Two further Blockers in the register (`LC-15` durable persistence of a failed
action's state, `LC-17` un-drained deferral buffer after a crash) are
**consequences of LC-01 and LC-03** in our architecture rather than separable
library defects; they close when those close.

**Performance findings that shape architecture rather than block it:**
- **Throughput is a fixed *global* budget** (~20–30k ev/s per event loop) shared
  by all interpreters, not per-machine capacity (LC-39). Scaling is by *process*.
- **The rule-per-symbol design does not work**: 2,000 ticks/s × 100 rules =
  200k evals/s needed; both engines deliver ~30k. Off by **6.3–6.9×** (LC-40).
  Statecharts must own rule *lifecycle* only, with a ≥99% pre-filter in front.
- **Order path p95 is 165 ms** against a 300 ms budget — only **1.81× headroom,
  before any network I/O**. And it is not transition cost (33 µs, 5,000× smaller);
  it is queueing delay behind other machines on the shared loop.

---

## 5. Upstream roadmap, in priority order

Ordered by **defects retired per unit of work**, not severity alone. This is what
we would contribute, in this sequence.

| # | Item | Fix | Unlocks |
|---|---|---|---|
| 1 | **LC-01** | `action_error_policy: continue \| rollback \| fail` | The rollback machinery **already exists** for transition failures (0.6.0 "Transition atomicity") — this reuses it. Also closes LC-11, and LC-15/LC-17 on our side. |
| 2 | **LC-03** | `on_unhandled: ignore \| defer \| error` | Retires our most invasive workaround (a `"*": defer` handler on *every* transient state plus a drain in every `entry`), and LC-17 + LC-18 with it. |
| 3 | **LC-02 + LC-04** | Treat an explicit self-target as external (XState v5); read `internal` as well as `reenter` | One-line root cause. Closes a silent deadlock *and* an XState divergence together. |
| 4 | **LC-08 + LC-07** | Validate targets at `create_machine()`, implement or reject leading-dot syntax | Cheap and self-contained. Turns two silent no-ops into build-time errors. |
| 5 | **LC-48** | `on_transition_failed`, `on_guard_error`, unhandled-event signal | Makes LC-01/LC-03/LC-09 **observable even before they are fixed** — valuable standalone. |
| 6 | **LC-43 + LC-41 + LC-42** | Thread-safe `send()`, queue-depth API + backpressure, request/response | Cross-thread silent loss is a correctness bug, not ergonomics. |
| 7 | **LC-26 + LC-27** | Timer scheduling under load; clock injection / virtual time | Hardest and most valuable for algos and replay. Clock injection alone would give us deterministic tests even if starvation remains. |
| 8 | **LC-53 + LC-39 + LC-44** | Document timer starvation, the `SyncInterpreter` threading model, the global throughput budget, and the pure API's "does not run actions" caveat | **Zero code risk, immediate value to every user.** We have the measurements. |
| 9 | **LC-06** | `strict_targets=True` by default | Behaviour change; worth a major-version note. |
| 10 | **LC-34 / LC-35** | Strict mode + typed context/events | Largest design surface; naturally last. |

If upstream lands only **#1, #2 and #3**, three of the four worst mitigations on
our side disappear and this becomes a straightforward Good-to-Excellent fit.

---

## 6. Project-health context

Not a defect, but it belongs in the decision: 14 stars, 1 fork, **one issue ever
filed**, ~11 releases in under a year (0.2.1 → 0.7.x), single maintainer, no known
independent production adoption.

We deliberately **downgraded** this from a top-tier risk. With 12,104 LOC, zero
runtime dependencies and MIT licensing, the library is *vendorable* — the risk is
a **testing obligation**, not an availability risk. Our mitigation is an exact pin
(`== 0.7.0` plus a wheel sha256), vendoring into `third_party/`, and a contract
suite that gates every version bump.

---

## 7. Recommendation

> ### DEFER — with a clear, mechanical path to ADOPT.

**Do not build CandleViewer's order path on 0.7.0 today.** Four filed Blockers are
open and every one of them fails *silently*; "we'll be careful" is not a control
that detects silence.

**Do not abandon the library either.** The fundamentals are good, the architecture
fits our four lifecycle families well, the failure mode is a single correctable
design philosophy rather than a rotten core, and the owner of this evaluation is
also the library's maintainer — which makes the fix path unusually short.

**The gate** (`20-adoption-gate.md`, tracked in
`issues/00-META-candleviewer-adoption-readiness.md`):

> **All Blocker and High items closed; all Medium items triaged.**
> Closed is proven by a repro script exiting 0 — never by a changelog entry.

Run `python gate/run_gate.py` against any new release; it prints a pass/fail table
and maps directly onto the ADOPT / ADOPT-with-constraints / DEFER decision table.

**Two things worth doing now, before any gate opens:**

1. **Ship the machine-definition linter and `tests/xstate_contract/` before the
   first CandleViewer statechart.** Every mitigation on our side fails silently if
   a developer forgets it. An unenforced rule is not a rule.
2. **Start upstream at roadmap #1–#3.** They are the highest-leverage fixes in the
   list, and #1 reuses machinery that already exists.

**Legitimate partial adoption while the gate is closed:** the replay/backtest path
and the rule runtime's *lifecycle* layer, where a silent no-op costs a wrong chart
rather than money — provided the contract suite is in place and the boundary is
written down explicitly.

---

## 8. How to file the issues

The issues are written but **have not been filed, and nothing has touched GitHub.**
Filing is a deliberate, owner-approved action.

**Artefacts:**

| Path | What |
|---|---|
| `issues/00-META-candleviewer-adoption-readiness.md` | The tracking meta-issue |
| `issues/LC-*.md` | 34 standalone issues, each with YAML front-matter (title, labels, severity, repro path, verification status) |
| `issues/repro/LC-*.py` | 34 runnable repros — **exit 1 while the defect is present, 0 once fixed** |
| `issues/file_issues.sh` | Generates the `gh` commands from that front-matter |

**Review the commands without creating anything:**

```bash
cd docs/research/xstate/issues
./file_issues.sh --dry-run          # prints 19 label + 35 issue commands, runs nothing
```

**File them, only when you decide to:**

```bash
./file_issues.sh --repo basiltt/xstate-statemachine
```

The script creates the 19 labels first (idempotent), then the 35 issues **in
dependency order** — meta-issue first so later issues link back to it, then the
root-cause defects (LC-01, LC-03, LC-02), then the validation cluster, then the
rest, matching the roadmap in §5. It requires an interactive confirmation of the
repo name, refuses to run twice (it writes a `.filed-issues` ledger), and pauses
2 s between calls to stay clear of secondary rate limits.

**After filing, by hand:** update the meta-issue checklist with the real issue
numbers, and offer the repro corpus as a PR under `tests/regression/candleviewer/`
marked `xfail(strict=True)` — so each one flips to a green test the moment its fix
lands.

---

## 9. Document map

| File | Contents |
|---|---|
| **`00-README.md`** | This summary |
| `01-library-core.md` | Source-level study of the two engines |
| `02-quality-and-tests.md` | Test suite, coverage, CI |
| `03-docs-examples-gaps.md` | Documentation gaps |
| `04-performance-concurrency.md` | Benchmarks `a`–`i`, all measurements |
| `05-semantics-probes.md` | 51 conformance probes vs XState v5 |
| `06-alternatives-ecosystem.md` | Alternatives and project health |
| `10-fit-analysis.md` | Fit against CandleViewer machines B1–B20 |
| `11-adversarial-review.md` | Adversarial review, MUST/MUST-NOT rules |
| **`12-challenge-register.md`** | **The 62-row consolidated register** |
| **`20-adoption-gate.md`** | **The re-analysis procedure and decision table** |
| `gate/run_gate.py` | Automated gate runner |
| `probes/`, `bench/`, `adversarial/`, `issues/repro/` | All executable evidence |
