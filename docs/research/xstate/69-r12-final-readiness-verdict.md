# 69 — Round-12 FINAL readiness verdict: `xstate-statemachine` main @ `de2da4e` (unreleased 0.8.1)

Date: 2026-09-23. Round 12. Prior decision (round 11, `c78ce99`): **ADOPT WITH CONSTRAINTS, decision-table row 6**.

**Identify this build by commit, never by version string.** `__version__` still reports `0.8.0` on `de2da4e` (merge of PR #223, `fix/0.8.1-round11`) while `CHANGELOG.md [Unreleased]` targets 0.8.1. Twelfth consecutive round. Every pin, CI assertion and gate baseline keys on the commit.

Method: 5 issue verifications (#218–#222) re-run live (`issues/verify-main-de2da4e/`); full regression sweep — gate (168 checks) plus a **573-script** sweep, every delta re-confirmed **×5 serially** (`65-r12-regression.md`); complete suite + benchmarks (`66-r12-suite-bench.md`, `suite-de2da4e.log`); diff review `c78ce99..de2da4e` (`67-r12-diff-review.md`); 8 battle tracks plus 20 contract machines on both service spellings (`battle-de2da4e/`); triage → dedupe → **independent adversarial refutation of every Blocker and High**, applied below.

**Financial-OMS standard applied throughout:** nothing counted without a standalone repro on a clean interpreter from neutral cwd `C:/Users/basil`, stdlib + `xstate_statemachine` only, and **every service/action check run with both `def` and `async def`**, polled to convergence.

**One behaviour change honoured throughout:** #219 makes an in-step `send(..., wait=True)` on an action's own interpreter raise `ReentrantWaitError` instead of deadlocking. That is a **breaking change for user actions**, and this round treats it as one.

---

## 0. The answer

### Are the reported issues genuinely closed?

**Yes — all five (#218, #219, #220, #221, #222), on both engines and both service spellings.** This is the **third consecutive round** in which every fix the release claims verifies clean, and it is the strongest of the three by measurement strength rather than by count.

- **#218 is exact.** A 200-beat `raise(delay=)` heartbeat holds **at most one** timer handle on every engine/kind cell; a 500× arm/cancel storm peaks at 0 handles with no double-release; cancel-after-fire is a clean no-op; and the round-11 soak that read **+455 MB / 24 s at 200 machines** now reads **RSS Δ 0.00 MB over 93,168 beats**, `handles_max_per_machine = 1`. The round-11 High is gone at the mechanism, not merely under the lint.
- **#219 is exact and correctly *narrow*.** The in-step await is refused on both engines; cross-interpreter `wait=True` (child→parent and parent→child) still resolves; 100/100 concurrent deferred receipts resolve with no hang and no spurious refusal. The refusal is in-step only, as the changelog claims.
- **#220 is sound and complete on the corpus we care about.** 178/178 and 400/400 valid charts generated from the full documented grammar build with **zero false positives** under `strict_config=True`; 638/640 nested typo injections caught with a path-named did-you-mean at up to **11/11 nesting levels**; `x-` / `meta` / `description` / `tags` accepted at every level.
- **#221 is exact.** 600/600 and 640/640 property cases survive 1–4 `from_snapshot` → `get_persisted_snapshot` compaction hops **without `start()`** with `remaining_ms` and `send_id` byte-identical at every hop, then fire exactly once — not early, not twice, no duplication once `start()` consumes the parked list.
- **#222 is correct.** Trip → `chain_trips=1`, `last_chain_error` latched and surviving benign events that erase `last_error`; `clear_chain_error()` clears the latch and keeps the count; `on_chain_budget_exceeded` fires exactly once per trip including settle-budget trips; identical on both engines and both kinds.

Two of the five carry a **scope residual** rather than a defect in what they fixed: #219's guard is implemented on an **inheritable `ContextVar`**, so the documented `ensure_future` escape hatch is timing-dependent (**DE-L1 / Q-1**, the round's one surviving library High); and #220 does not recurse into an **inline-machine `invoke.src`** (Q-5, Low). #222's latch is **not persisted** (Q-7 / D12-security-1, Low) — consistent with its documented purpose as a live-supervisor signal, but a real operational hole for restart-from-snapshot.

### Is the library fully battle-tested?

**More so than in any prior round, and for the first time the two standing measurement debts have split — one is paid, one is not.**

Paid: **the full suite completed for the first time in four rounds** — `3545 passed, 13 skipped, 0 failed, 92.87 % coverage` (gate floor 90 %), from a genuinely complete run. Decision-table **row 2 now rests on a measurement taken at the commit under test**, not on a one-commit-stale carry-over. Hash-seed determinism: rounds 9+10+11 pins, **59/59 under `PYTHONHASHSEED=1` and 59/59 under `=2`**.

Not paid: **BENCH-6 (loaded timer drift) is unmeasured for a fifth consecutive round.** `bench_c_timers` timed out again, including on a reduced-parameter retry, and `bench_h_candleviewer_budgets` (Budgets 1/2/3) timed out with it, so **BENCH-1 and BENCH-2 are also unmeasured this round**. `bench_a_throughput` and `bench_j_policies` completed and track round 11 within a few percent. This is recorded as an honest hole, not papered over, and it is the single reason the gate cannot reach row 9.

Eight battle tracks ran, five of them with an **empty new-defect register** — the concurrency track's first in its history. 20 contract machines were driven end to end on both spellings with a snapshot/restore round-trip at every quiescence point.

### Is it good to proceed?

**Yes — and the gate recovers the row it lost. Round 12 is ADOPT WITH CONSTRAINTS, decision-table ROW 8**, up two rows from round 11's row 6 and matching round 10's position.

Post-refutation the round closes at **0 Blocker · 1 High · 3 Medium · 6 Low** on the **library** board. The row-6→row-8 question is whether the High row is empty, and it turns on one item: **DE-L1/Q-1** — #219's `ContextVar`-based guard refusing the very escape hatch the changelog documents. **Refutation resolves it at Medium, not High** (§5): every shape it refuses has a deterministic, documented alternative that we already mandate (CV-C25 — no external `send()` from inside an action), the refusal is **loud and immediate** rather than silent, it is **strictly safer than the `c78ce99` behaviour it replaced** (a permanent silent `start()` deadlock, R11-06), and our 573-script corpus contains **zero** instances of the refused shape. A loud false refusal of a pattern our architecture already bans is a Medium API-ergonomics defect, not a High.

With the High row empty and all Mediums triaged, **row 8 fires** — "all Blocker and High closed; all Medium triaged; BENCH-1/2/6 not all met". Row 9 is refused, explicitly and on the record: **BENCH-6 is not *met*, it is *unmeasured*, for the fifth round running**, and a row that requires all thresholds met cannot be reached by absence of evidence.

**Round 11's regression is fully reversed, and reversed at the mechanism.** R11-04 was the single open High and CV-C47 was its containment; #218 closes it at the source (0.00 MB over 93 k beats). Row 8 means what it meant in round 10: **every remaining constraint is an architectural consequence of our own benchmarks, not containment for an open library defect.**

**Refutation moved every Blocker/High candidate DOWN and none up, for the fifth round running.** Five candidates went to independent refutation: two Blockers **refuted outright** (R12-02, R12-03), one Blocker **downgraded to Low** (R12-01), and the two that survived at **Blocker** (R12-13, R12-14) and **High** (R12-15) are **OURS — catalogue-JSON defects, fixable in config alone, with no library-readiness impact**. For the second round running, **the binding constraint on our order path is our own catalogue, not the library.**

### Did #219 (`ReentrantWaitError`) require any change to OUR catalogue actions?

**No — zero changes, and this was checked positively rather than assumed.**

A full scan of the **573-script corpus** and of every failure tail in `gate/r12_regression_raw.json` finds **no script that raises, catches or mentions `ReentrantWaitError`**, and no failure attributable to an action awaiting `send(..., wait=True)` on its own interpreter. The ≈30 scripts that use `wait=True` (`N-01`, `R4-07`, `R7-03`, `R8-07`, and the determinism track's `d1_replay.py`, `d2_receipt_deferred.py`, `f5_nested_parallel_snapshot_refusal.py`) all await the receipt from the **harness driving the interpreter from outside a running step** — the shape #219 explicitly keeps legal — and every one passes. The contracts track audited the catalogue's action bodies directly (`f7_r11.py` 5/5, `d5_reentrant.py`, `e6_round11.py` 8/8 per lane): **no B1–B20 action performs an in-step self-await.**

**Why it cost us nothing is not luck, it is CV-C25.** We have banned external `send()` from inside an action since round 5 — the gateway queue is the only path — and CV-C51 (round 11) bans an entry/exit action awaiting its own receipt outright. #219 makes a rule we already lint into a library-enforced error. **The correct reading is that our constraint set anticipated this change, not that we dodged it.** New **CV-C64** promotes the audit to a standing pre-upgrade lint so the next adopter of this codebase does not have to rediscover it.

For adopters generally this is a **real** breaking change and we say so in the postables: the in-step await was the natural way to write "act, then confirm", and any user action that did it now raises where it previously hung. Our corpus simply never wrote that shape.

### Did #220's recursive check reject any of OUR catalogue JSON — false positive, or our defect?

**Neither — there is no rejection to adjudicate. All 20 catalogue charts build clean at every nesting level, with zero warnings, on both lanes.**

This was the round's biggest exposure and it was tested as such. #220 turned unknown-key checking from a root-dict scan into a full recursion, so a chart that built clean at `c78ce99` could be refused at `de2da4e`. Results:

| Corpus | Result under recursive `strictConfig` |
|---|---|
| B1–B5 + B16–B20 (`f0_build.py`, `d0_build.py`) | **11/11 and 20/20 clean per lane, 0 warnings** |
| B6–B10 (`e0_build.py`) | **5/5 clean**, 45/45 policy read-back per lane |
| B11–B15 (`d1_build.py`) | **5/5 clean, 0 warnings, both lanes** |
| Full 54-chart `*.machine.json` sweep (`p3`, `n_persist_keys.py` N4) | **54/54 clean** |

**The control is positive, not merely an absence.** For each chart a typo was planted at a *nested* site — `entyr` / `onn` in a child state, a bad key in a transition body, a bad key in an `invoke` — and a refusal required: **20/20 negative controls refused on B11–B15, 15/15 on B6–B10, 5/5 on B16–B20**, each naming the path (`session.auth: 'entyr' (did you mean 'entry'?)`). And the false-positive control is equally positive: a full valid-key grammar exercising every documented key at every level, including `x-` / `meta` / `description` / `tags`, raises **zero** findings (0/120, 0/178, 10/10).

So the answer to the framing question — false positive vs our defect — is that **both hypotheses are refuted by measurement**: #220 has no false positive on our corpus, and our corpus had no nested typo for it to find. Concretely, **nothing in B1–B20 was silently dropping an entry action or a transition at `c78ce99`** — which is the fact that could not be established before #220 existed, and is the most valuable thing this fix bought us.

One residual bounds the claim: **Q-5** — #220 does not recurse into an **inline-machine `invoke.src`**. No catalogue chart uses an inline invoked machine today, so the gap is latent for us; **CV-C57 (the wrapper's own recursive check) stands and is re-grounded on it** rather than retiring into #220.

---

## 1. Disposition of the five issues

Legend: **FIXED** (verified clean on every axis claimed) · **PARTIAL** · **NOT FIXED** · **RESIDUAL** (the fix lands, an adjacent scope does not).

| # | Claim | Verdict | Evidence — both engines + both service kinds, standalone from neutral cwd |
|---|---|---|---|
| **#218** | A delayed self-send releases its clock handle when it fires or is cancelled. | **FIXED — exact, no residual** | 200-beat `raise(delay=)` heartbeat: **peak 1 handle** on all three engine/kind cells (`w_handles_cancel.py` W1, `f2` §B). 500× superseding re-arms of one send id: peak 1 handle, exactly 1 fire. 500× arm/cancel storm: `fired=0`, `peak_handles=0`, `armed=0`, **no double-release crash**. `STOP` releases it. Soak: **200 machines × 10 s = 93,168 beats, `handles_max_per_machine = 1`, RSS Δ 0.00 MB** (round 11 read **+753 MB** on the identical script). A 200-machine / 150-s soak sits at **1.00 handles per machine**. The round-11 repro, unmodified, now exits 0. |
| **#219** | An action awaiting `send(..., wait=True)` on its own interpreter raises `ReentrantWaitError`, not a deadlock; the sync engine refuses for parity. | **FIXED — with a residual in the documented escape hatch (DE-L1 / Q-1)** | Full matrix (`r_reentrant_latch.py` R1–R7, `f2` §A, `p4`): self-await → `ReentrantWaitError` and **`start()` returns**; post-start action, `after`-fired clock handler and the **sync engine** all refuse identically (parity holds); cross-interpreter `wait=True` in **both** directions → OK, correctly not refused; **100/100** concurrent deferred `ensure_future` receipts resolve, no hang, no spurious refusal. Round-11's R11-06 silent `start()` deadlock is **FIXED** by this. **Residual:** the guard keys on an inheritable `ContextVar` — see §2(d), **DE-L1**. |
| **#220** | Unknown-key checking recurses into every state, transition and invoke, with per-level known sets and path-named findings. | **FIXED — with one scope residual (Q-5)** | **Sound:** 178/178 and 400/400 valid charts from the full documented grammar build with **0 false positives** under `strict_config=True`; `x-`/`meta`/`description`/`tags` accepted at every level (10/10, 0/120). **Complete:** 638/640 single-typo injections caught at a random nesting level and object kind, each naming the path; 240/240 nested typos at state/transition/invoke level (were **0/0 caught** at `c78ce99`); reaches **11/11** nesting levels, `missed: []`; 13/13 typo cells across root/state/transition/invoke on the security track; 54/54 catalogue charts clean. The round-11 repro `x8` now raises naming `nk.a: 'Entry'`. **Residual:** does not recurse into an inline-machine `invoke.src` (Q-5, Low). |
| **#221** | Parked v3 `scheduled_sends` are re-emitted verbatim until `start()` consumes them. | **FIXED — exact, no residual** | 600/600 (300 × 2 kinds) and 640/640 property cases survive a random chain of **1–4 `from_snapshot` → `get_persisted_snapshot` hops without `start()`**, with `remaining_ms` and `send_id` **byte-identical at every hop**, then fire exactly once after the remainder — not early, not twice. **No duplication** once `start()` consumes the parked list (before/after/again = 1/1/1). Sync engine identical. Contract lane: verbatim over 2 compaction hops with a **20,000 ms remainder honoured**. The union of restored + armed self-sends survives a no-start re-persist; double-hop idempotent; `remaining_ms` counts **down**, not reset. |
| **#222** | Chain-budget trips are sticky: `chain_trips`, `last_chain_error`, `clear_chain_error()`, `PluginBase.on_chain_budget_exceeded`. | **FIXED — new API correct; legacy `last_error` unchanged by design** | Trip → `chain_trips=1`, `last_chain_error` latched and **surviving 5–10 benign events** that erase `last_error`, plus 5 heartbeat beats; `clear_chain_error()` clears the latch and **keeps the count**; a second trip → `chain_trips=2`; `on_chain_budget_exceeded` fires **exactly twice for two trips**, settle-budget trips included; `on_event_dropped(reason='chain_budget')` **precedes** it and both fire exactly once per trip. Identical on both engines and both kinds. `chain_trips == 0` on every happy path across **all 20 contract charts, both lanes** (54/54 cells on B11–B15 alone). **Residual:** the latch is **process-local — not a snapshot field** (`snapshot_has_chain_key = []`, `restored_chain_trips = 0`), filed Low as **D12-security-1 / Q-7** and carried as **CV-C63**. |

**Disposition: 5 FIXED · 0 PARTIAL · 0 NOT-FIXED · 0 regressed-on-one-axis.**

**The service-kind axis is flat across the entire corpus for the third consecutive round** — with exactly one recorded exception, and it is a genuine behavioural difference rather than a harness artefact: a **`def` action** calling `send(..., wait=True)` receives the `_Awaitable` guard **unawaited** — no error, no warning, no usable receipt (it cannot await, so nothing hangs). Carried as a lint observation under **CV-C64**, not filed as a library defect.

Three of the five (#218, #221, #222) are **exact with no scope residual at all** — the first time in this study that a majority of a fix set has been residual-free. The two residuals that do exist are both *adjacent-scope* rather than failures of the shipped mechanism: the same pattern rounds 10 and 11 recorded, now at half the rate.

---

## 2. Regressions

Four categories, kept strictly separate, because conflating them is how a superseded test becomes a permanent blocking FAIL.

### (a) TRUE regressions — **ZERO**

Across the full gate (**168 checks**, 128 PASS / 40 FAIL vs `c78ce99`'s 124/39) and a **573-script sweep** (476 PASS / 94 FAIL / 3 TIMEOUT), **not one stable PASS→FAIL delta is a true regression.** Comparing only the 525 scripts present in both rounds: **11 PASS→not-PASS, 1 not-PASS→PASS**. Every one of the 11 was re-run **×5 serially** from the neutral cwd (`gate/r12_flaky.py`) under standing rule `R11-H-1`; **nine are harness/contention false FAILs** (5/5 or 4/5 PASS serially), and the remaining two are the superseded cases below.

Gate deltas: **six new checks, all PASS** (`212`, `213`, `214`, `215`, `215#2`, `216`); **one retirement** that doc 64 §2(b) had already scheduled; **two genuine improvements** (`LC-39 throughput global budget` FAIL→PASS, `150_send_threadsafe_budgeted` FAIL→PASS); **two load-sensitive reds** (`167 rollback_reinvoke_spin`, `LC-45 hot path alloc + info logging`) that are allocation / wall-clock threshold checks run on a loaded box, and which the gate itself flags for triage.

Exit code 1 in both rounds: the gate deliberately keeps a standing red set of carried findings, so a non-zero exit is the expected steady state, not a round-12 event.

**Methodological finding, recorded for the third round and now escalated to a binding action.** The parallel sweep produced **11 false FAILs at 10 workers** against round 11's **4 at 6 workers** — the error scales with worker count. `R11-H-1` is restated in §10 as binding: the timing-sensitive subset runs **serially**, or the parallel driver is retired. It now costs more triage than it saves. Separately, six corpus scripts reach into private internals (`i._priority_queue`, `i._timer_handles`) and are a standing source of false signal; §10 schedules their rewrite against public API.

### (b) SUPERSEDED-BY-#219 — **ZERO scripts**

Stated positively, because the absence is itself the finding. A full scan of all 573 scripts and of every failure tail in `gate/r12_regression_raw.json` finds **no script that raises, catches or mentions `ReentrantWaitError`**, and no failure attributable to the in-step self-await. Our ≈30 `wait=True` call sites (`N-01`, `R4-07`, `R7-03`, `R8-07`, …) all await from **outside** an action — the shape #219 keeps legal — and every one passes. The three determinism-track scripts that were the plausible candidates (`d1_replay.py`, `d2_receipt_deferred.py`, `f5_nested_parallel_snapshot_refusal.py`) were individually audited: **none triggers the new refusal**; in all three the `wait=True` call is the harness driving the interpreter from outside a running step.

**#219's new refusal breaks none of our corpus and none of our catalogue** (§0). It is nonetheless a genuine breaking change for adopters at large, and the postables say so in those words.

### (c) SUPERSEDED-BY-#222 — **one script**

| Script | ×5 serial | Disposition |
|---|---|---|
| `issues/post-c78ce99/new/repro/R11-09_chain_trip_erased_by_next_event.py` | **5/5 FAIL** | **SUPERSEDED-BY-#222 — REWRITE, do not count as FAIL.** It asserts `last_error` still names `RunawayChainError` after one benign event, and still reports `REPRODUCED: True` on all three lanes. That is now **by design**: #222 documents `last_error` as the per-step read it always was and moves stickiness to `chain_trips` / `last_chain_error` / `on_chain_budget_exceeded`. **The script tests an oracle the release deliberately retired.** Rewritten against the latch (§10). |

Plus one **stale repro, fix confirmed** — the same surface failure, a different cause:

| Script | ×5 serial | Disposition |
|---|---|---|
| `issues/post-c78ce99/new/repro/R11-07_nested_config_typos_silent.py` | **5/5 FAIL** | **Fix confirmed; repro now stale.** It builds `{"states": {"a": {"entyr": ..., "onn": ...}}}` expecting silence; `de2da4e` raises `InvalidConfigError: typo.a: 'entyr' (did you mean 'entry'?), 'onn' (did you mean 'on'?)` — exactly #220's path-named finding. **It exits non-zero precisely because the defect is gone.** Rewritten as a pin (§10). |

And one carried from round 11: `_RETIRED_206_delayed_selfsend_charged.py` — **SUPERSEDED-BY-#212**, now carrying `_RETIRED_` in the filename so no future round counts it. **The rename worked**: round 12 spent zero triage on it. That is the concrete payoff of doc 64 §2(b)'s retirement discipline, and the argument for applying it again here.

### (d) Library regressions — **ONE, new at this commit**

| ID | Kind | What it is |
|---|---|---|
| **DE-L1 / Q-1** (filed High → **Medium** after refutation, §5) | API ergonomics / new behaviour | **#219's guard is built on an inheritable `ContextVar`.** `_ACTIVE_ACTION_OWNER` is set for the duration of `_run_user_action` (`interpreter.py:2256`), but `asyncio.ensure_future` / `create_task` **copy the current context**, so a task spawned inside an action keeps `_ACTIVE_ACTION_OWNER is self` **for its whole life** — long after the action returned and the run loop went idle. The guard (`interpreter.py:1144`) therefore cannot distinguish "in-step" from "descended from a step", and refuses two shapes in which **no deadlock is possible**: (1) a background worker born in an entry action that sends 300 ms after the machine went idle, and (2) **the documented escape hatch itself**, whenever the action does any further awaiting after handing the receipt out. The pinned test passes only because its action returns immediately, so the wrapper task never runs before the loop drains the event — **the idiom's safety is scheduling luck, not a property of the API.** Reproduced standalone, both shapes, both lanes. Suggested narrower predicate: gate on the interpreter actually being mid-step (a plain instance flag around the synchronous action call), not on an inheritable `ContextVar` — the right tool for #105's provenance question and the wrong one for #219's liveness question. |

**Round 11's two library regressions are both closed at this commit:** R11-04 (unbounded `_timer_handles`) by #218 — measured on the container, not inferred — and R11-06 (#215's silent `start()` deadlock) by #219, which converts it into a loud immediate error. **One net-new regression was introduced and two were retired; the board improves by one.**

No *semantic* regression exists: no previously-correct behaviour became incorrect. DE-L1 makes a previously-working pattern raise, which is what makes it a regression at all — but the pattern it breaks is one **our own CV-C25 has banned since round 5**.

---

## 3. Scorecard

| Axis | Round 11 (`c78ce99`) | **Round 12 (`de2da4e`)** | Direction |
|---|---|---|---|
| Issues verified | 5 | **5** | = |
| FIXED / partial / not-fixed | 5 / 0 / 0 | **5 / 0 / 0** | = (third consecutive clean set) |
| Fixes with **no** scope residual | 1 of 5 | **3 of 5** | ▲ best in the series |
| Upstream suite | **not completed** (~4 % reached) | **3545 passed, 13 skipped, 0 failed, 752 s** | ▲ **completed — first time in 4 rounds** |
| Coverage | 92.78 % (one commit stale) | **92.87 %, measured at the commit under test** | ▲ measured, not carried |
| Hash-seed determinism | 65/65 (seeds 1, 2) | **59/59 (seeds 1, 2)** | = |
| Gate checks | 163 (124 P / 39 F) | **168 (128 P / 40 F)** | ▲ 6 new checks, all PASS |
| Script sweep | 527 (444 P / 83 F / 0 T) | **573 (476 P / 94 F / 3 T)** | ▲ 47 new scripts |
| **TRUE regressions** | **0** | **0** | = (sixth round running) |
| Library regressions new at commit | 2 (1 resource, 1 liveness) | **1 (API ergonomics)** | ▲ and both prior ones closed |
| Battle tracks | 8 | **8**, five with an **empty** new-defect register | ▲ |
| Contract charts building clean | 20/20 (root-only strict) | **20/20 under recursive strict, 0 warnings, both lanes** | ▲ materially stronger claim |
| Blocker (library) | 0 | **0** | = (fourth round running) |
| High (library) | 1 (R11-04) | **0** | ▲ **row-deciding** |
| Medium (library) | 4 | **3** | ▲ |
| Low (library) | 5 | **6** | ▼ |
| Blocker/High candidates moved **down** by refutation | 4 of 5 | **3 of 5 refuted or downgraded; 2 survived, both OURS** | = fifth round running, **none moved up** |
| **Blockers of any kind** | 2 (C-04, C-07b — ours) | **2 (R12-13, R12-14 — ours; merged forms of C-04 / C-07b)** | = **seventh round open** |
| BENCH-1 / BENCH-2 | last measured round 10 | **unmeasured (script timeout)** | ▼ |
| **BENCH-6** | unmeasured (4 rounds) | **unmeasured (5 rounds)** | ▼ **the standing debt** |
| `bench_a` throughput | baseline | 13.4–15.8 k ev/s burst · 122 k raw sends/s · p50 96.5 µs lockstep — within 5–10 % | = |
| `bench_j` policies | baseline | rollback 0.703× · defer 0.769× · both 0.631× | = (0.631× now read low twice — **treat as the real number**, superseding round 11's "re-check" flag) |
| **Decision-table row** | **6** | **8** | ▲▲ **up two — back to round 10's position** |

---

## 4. Contracts — both service kinds, `strictConfig` results, C-04 / C-07b status

**20 contract machines, driven end to end, twice each** (pass 1 every service `async def`, pass 2 every service plain `def`), under the mandatory config, with `SimulatedClock`, a bounded `OverflowPolicy.RAISE` inbox (`max_queue_size=64`), a `CvErrorHooks`-equivalent `PluginBase` stub now also implementing **`on_chain_budget_exceeded`** (#222), `minimum_version=3` on every restore, and a **snapshot/restore round-trip at every quiescence point**. Library source never modified. Contract JSON carried byte-identical from `battle-c78ce99/contracts/`; `strictConfig` injected by the harness so the corpus stays byte-stable across rounds.

### 4.1 Results, both lanes

| Board | Script | async lane | def lane |
|---|---|---|---|
| Build gate, 10 charts, recursive `strictConfig` | `f0_build.py` | **11/11** | 11/11 |
| B1 Order | `f1_b1.py` | **34/34** | 34/34 |
| B2 TradeGroup | `f2_b2.py` | **23/23** | 23/23 |
| B3 TradeGroupLeg | `f3_b3.py` | **21/21** | 21/21 |
| B4 OCO + B5 Iceberg | `f4_b45.py` | **34/34** | 34/34 |
| B18 `send_priority` / `always` | `f5_b18.py` | **5/5** | 5/5 |
| Async↔Sync parity (B1/B3/B4/B18) | `f6_parity.py` | **39/39** | 39/39 |
| #219 reentrant-wait + **action audit** | `f7_r11.py` | **5/5** | 5/5 |
| #218 / #221 / #222 | `f8_r11b.py` | **10/10** | 10/10 |
| **C-04 / C-07b config-only fix proof** | `f9_c04_c07b.py` | **6/6** | 6/6 |
| B16/B17 invariants | `fA_b16_b17.py` | 11/14 — **3 FAIL = C-04 / C-04b / C-04c** | same 3 |
| Sharp edges | `fC_sharp.py` | **13/13** | 13/13 |
| B6–B10 build + policy read-back | `e0_build.py` | **45/45** | 45/45 |
| B6–B10 invariants + scenarios | `e1_invariants.py` | **52/52** | **52/52** |
| B6–B10 mandated drives | `e2_drives.py` | **14/14** | 14/14 |
| B6–B10 #207 storm + #204 no-arm | `e3_sharp.py` | **14/14** | 14/14 |
| B6–B10 #212/#213 timers, both engines | `e4_timers.py` | **10/10** | 10/10 |
| B6–B10 sync parity | `e5_parity.py` | **20/20** | 20/20 |
| B6–B10 round-11 obligations | `e6_round11.py` | **8/8** | 8/8 |
| B11–B15 build / invariants / parity | `d1_build.py`, `d2_inv.py` | **5/5 clean · 27/27** | **27/27** |
| B16–B20 build, recursive strict | `d0_build.py` | **20/20 clean** | 20/20 |
| B16/B17 invariants | `d1_b16_b17.py` | 11/14 — **3 FAIL = C-04 / C-04b / C-04c** | same 3 |
| B18/B19/B20 invariants + 3 mandated drives | `d2_b18_b20.py` | 26/27 — **1 FAIL = C-06 (→ R12-15)** | same 1 |
| Sharp edges (C-07b, #207, #204, sync parity) | `d3_sharp.py` | **13/13** | 13/13 |
| Timer/restore axis (#212/#213/#128/#214/#205) | `d4_timers.py` | **10/10** | 10/10 |
| Round-11 axis (#218/#219/#221/#222) | `d5_r11.py` | **13/13** | **12/13** — the one `def`-lane cell, DE-L1 |

**`chain_trips == 0` on every happy path, all 20 charts, both lanes.** Snapshot/restore at every crashpoint MATCHes on states *and* context, with **0 spurious `SnapshotMidStepError`**.

**LIBRARY defects across the entire contract corpus: 1 (DE-L1, Medium).** Every other failure on the board is ours.

### 4.2 `strictConfig` under #220 — the round's biggest exposure, and it is clean

#220 turned unknown-key checking from a root-dict scan into a full recursion, so a chart that built clean at `c78ce99` could be refused at `de2da4e`. The instruction was to adjudicate any rejection as either a #220 false positive or an our-contract defect. **There is no rejection to adjudicate.**

| Corpus | Under recursive `strictConfig` |
|---|---|
| B1–B5 + B16–B20 | **11/11 and 20/20 clean per lane, 0 warnings** |
| B6–B10 | **5/5 clean** — zero `InvalidConfigError`, zero `ImplementationMissingError` |
| B11–B15 | **5/5 clean, 0 warnings, both lanes** |
| Full 54-chart `*.machine.json` sweep | **54/54 clean** |

**Both controls are positive, not absences.**

- *Negative control (does it fire when it should?)* — a typo planted at a **nested** site on every chart is refused every time: **20/20** on B11–B15, **15/15** on B6–B10, **5/5** on B16–B20, plus the root-typo control (`actionErrorPolicyy`) refused on all five B16–B20 as in round 10. Messages name the path: `session.auth: 'entyr' (did you mean 'entry'?), 'onn' (did you mean 'on'?)`, with all findings in one `InvalidConfigError`.
- *False-positive control (does it stay quiet when it should?)* — a full valid-key grammar exercising every documented key at every level, including `x-` / `meta` / `description` / `tags`: **0 findings** (0/120, 0/178, 10/10 accepted).

**The load-bearing conclusion:** nothing in B1–B20 was silently dropping an entry action or a transition at `c78ce99`. That fact could not be established before #220 existed, and it is the most valuable thing this fix bought us — it retroactively validates every contract result from rounds 4–11.

`"strictConfig": true` was added to the five control charts this round, adopting CV-C49; the JSON is otherwise unchanged and **no JSON edit was required by `de2da4e`** (B6–B10 sha1 first-12 unchanged: B6 `97f57ff035de`, B7 `38ddf600a6f2`, B8 `03586b051082`, B9 `04b1d029b493`, B10 `f0a0aa4824cd`).

### 4.3 C-04 and C-07b — status after seven rounds

Both remain **OPEN, OURS, and Blocker for the order path**. Both are **config-only** fixes. Both have been refuted as library defects — repeatedly, and again this round. They are the **only Blockers of any kind on this twelve-round board.**

**C-04 → merged and re-confirmed as R12-13 (Blocker).** Reproduced deterministically across **24 lanes** (both engines, `def` and `async def`, 4 kill events, standalone from neutral cwd, polled to convergence): the catalogue fails **12/12** — `LOGOUT` / `IDLE_DEADLINE` / `ABSOLUTE_DEADLINE` leave `["session.auth.revoked", "session.elevation.elevated"]`, and `REVOKE` lands in `normal` where a later `STEP_UP_OK` **re-elevates a dead session**. Every refutation line fails: engine dispatch is spec-correct (XState v5 / SCXML select transitions per parallel region independently, so a region with no handler does not move, and our own `onUnhandled: defer` swallows it), no trust boundary is crossed, no clock or timer is involved so it is not a measurement artefact, and it is the **merged form** of C-04 / CV-C04 / CD-02, not a new duplicate.

> **Correction to the prescribed fix, and it matters.** The root hoist to a final `elevation.dead` state fixes only **9 of 12** lanes, because the deeper `elevated.on.REVOKE` handler **outranks the root arm**. The **region-level `REVOKE` handler must also be deleted.** Any earlier write-up of the C-04 remedy that omits this is wrong by three lanes; E50-T43's acceptance criteria are amended accordingly (§10).

**C-07b → merged and re-confirmed as R12-14 (Blocker).** Re-reproduced on `de2da4e`, standalone, neutral cwd, both kinds: a **guard-denied** `RELEASE` under root `onUnhandled: "error"` makes the machine fatal (`status='error'`, `UnhandledEventError`), and the subsequent **authorised** `RELEASE` is accepted by `send()` but dropped, leaving `final = ['kill_switch.engaged']` — `bricked: true`. All refutation lines fail: the behaviour is **documented** (opt-in `onUnhandled:'error'` plus CHANGELOG #153 `guard_denied`), which is exactly what makes it ours; XState v5 / SCXML treat a guard-denied event as simply untaken and have **no fatal-unhandled mode**, so upstream semantics argue *against* our configuration rather than endorsing it; it is a deliberate merge of C-07b / CV-C07b / CD-03; polled to convergence, exit 0, no artefact; no trust boundary crossed. **Blocker for B18 on the order path — one wrong press permanently wedges the kill switch.** The config-only fix (`onUnhandled: 'defer'` plus an ordered **unguarded auditing `RELEASE` fall-through**) is proven: `f9_c04_c07b.py` **6/6**, `fC_sharp.py` **13/13**, `d3_sharp.py` 13/13. **Open seven rounds, still unlanded in `ka_killswitch` (E50-T43).**

**C-06 → merged and confirmed as R12-15 (High).** Sole FAIL in `d2_b18_b20.py` / `fB_b18_b20.py`: `[async] B19/INV-b2 operator can clear stale_lockout`, `st=stale_lockout`, `unh=[[OPERATOR_RESOLVED, deferred]]`. Root cause is **our** `B19.machine.json`: `stale_lockout.on` has only `RECONNECTED`, while `divergent` has an `OPERATOR_RESOLVED` arm; under `onUnhandled: "defer"` the operator event parks forever, so a venue that never reconnects leaves the account `account_locked` / `critical` **until process restart**. Not refutable — library behaviour matches XState v5 / SCXML event selection, no API misuse, sync lane identical, pure config we authored. Fix verified standalone (`refutations/r12-15-b19-operator-clear.py`): adding `stale_lockout.on.OPERATOR_RESOLVED → idle` with `unlock_account` yields `stale_lockout → idle` in **both** lanes.

C-04b and C-04c remain **Medium, ours, unchanged** (B16).

---

## 5. Surviving defects, by final severity after refutation

Two boards, kept separate on purpose. **Only the library board governs the gate row.**

### 5.1 LIBRARY board — **0 Blocker · 0 High · 3 Medium · 6 Low**

| ID | Severity | What it is | Disposition |
|---|---|---|---|
| **DE-L1 / Q-1** | **Medium** (filed High — **downgraded by refutation**, below) | #219's guard rides an inheritable `ContextVar`, so the **documented `ensure_future` escape hatch** is refused whenever the spawning action does any further awaiting, and a background worker born in an action is refused **300 ms after the machine went idle**. Both shapes reproduce standalone, both lanes; the `def` lane differs from the `async` lane here. | **FILE UPSTREAM** (new issue, standalone repro in the body). Contained by **CV-C25 + CV-C51 + new CV-C64**. |
| **Q-5** | Low | #220 does **not** recurse into an inline-machine `invoke.src`. Latent for us — no catalogue chart uses an inline invoked machine — but it is the one hole left in an otherwise complete recursion. | **FILE UPSTREAM** (note on the #220 thread). **CV-C57 stands, re-grounded on this** rather than retiring into #220. |
| **R12-01 residual** | Low | `_rearm_restored_self_sends` never calls `_admit_restored`, so `strict: True` is enforced on restored `pending_events` but **silently bypassed** for restored `scheduled_sends` (`last_error` stays `None`). A #214 parity / observability gap — **not** an escalation (see the refutation). | **FILE UPSTREAM** (one-line fix: route through `_admit_restored`). Contained by **CV-C54** (count reconciliation) + **CV-C53** (MAC'd journal). |
| **D12-security-1 / Q-7** | Low | `chain_trips` / `last_chain_error` are **not snapshot fields**, so restart-from-snapshot erases the evidence that the prior process discarded work. Consistent with the documented purpose (a live-supervisor signal) and with the v3 layout as specified — an operational hole, not a broken promise. | **Note on the #222 thread.** Contained by **new CV-C63** (the wrapper latches both into its own envelope before persisting). |
| **Q-8** | Low | `__version__` reports `0.8.0` on an `[Unreleased] — targeting 0.8.1` tree, **twelve rounds running**. Any gate keyed on the version string mis-identifies this build. | **Note on the release thread.** Contained by keying every pin on the commit (binding rule since round 6). |
| **CV-C63′ observation** | Low | A **`def`** action calling `send(..., wait=True)` receives the `_Awaitable` guard unawaited — no error, no warning, no usable receipt. Nothing hangs (it cannot await), but the call is silently useless. | **Note on the #219 thread.** Contained by **CV-C64**. |
| **D11-security-4** (carried) | Low | `on_invalid_event` is structurally unreachable on a restore refusal — `_admit_restored` runs inside `from_snapshot`, strictly before the caller can `use(plugin)`; `from_snapshot` takes no `plugins=` argument. Still present, unchanged. | Carried. Contained by **CV-C60** (read `last_error` immediately after `from_snapshot`, before `start()`). |
| **D11-security-5** (carried) | Low | Priority lane not honoured on sync restore. Surface unchanged this round; **not re-run** — recorded as carried-unverified, not as passed. | Carried. Contained by **CV-C42** (no `priority=True` anywhere). |
| **D11-security-6 / R11-W-3** (carried) | Low | `SimulatedClock` fires neither `after` nor restored `scheduled_sends` on this build. Surface unchanged; **not re-run**. | Carried. **R11-W-3 stands**: deadline properties are verified against the real clock. |

Plus the two **Medium** carried items that were already triaged and remain so: **R11-02(c)** (`lane` is forgeable on async and unenforceable on sync → CV-C42) and **R11-10** (restore refusal unobservable → CV-C60). Both were triaged in round 11 and neither changed at this commit — which is what row 8 requires of a Medium: triaged, not necessarily closed.

**Blocker row: empty for the fourth consecutive round. High row: empty for the first time since round 10.**

### 5.2 Why DE-L1 is a Medium, not a High — the row-deciding call, on the record

This is the single judgement that separates row 6 from row 8, so it is written out in full and it is written to be attacked.

The filed severity was **High** (`67-r12-diff-review.md` Q-1), on the reasoning that the docs explicitly sanction handing the receipt out and awaiting it later, and this refuses exactly that, non-deterministically. That reasoning is **correct as far as it goes**, and the defect is real and should be fixed upstream. Four independent lines nonetheless put it at Medium:

1. **Every refused shape has a deterministic, documented alternative that we already mandate.** The refusal is escapable by construction: spawn the helper with a **fresh context** (`contextvars.Context().run(...)`) — measured **OK, `changed=True`**, both shapes — or, as our architecture already requires, do not send from inside an action at all. **CV-C25 has banned external `send()` from inside an action since round 5**; **CV-C51** (round 11) bans an entry/exit action awaiting its own receipt outright. A defect that only bites code our own linter rejects is, for us, an ergonomics defect.
2. **The failure is loud and immediate, not silent.** Every High in this study's history has been a *silent* failure — a dropped deadline, an erased trip record, a leak with no plateau, a hang with `last_error = None`. `ReentrantWaitError` raises at the call site with the interpreter id and the event type in the message. A loud refusal is discoverable in the first test run; a silent one reaches production.
3. **It is strictly safer than the behaviour it replaced.** At `c78ce99` the same code path was **R11-06**: a permanent, silent `start()` deadlock with `last_error = None`, `status = running` and a legal configuration — a round-11 Medium that took a custom gate-pre-opening subclass to diagnose. #219 converts a silent permanent hang into a loud immediate exception, and over-refuses at the margin. **Scoring the improvement as a High while its strictly-worse predecessor was a Medium would be incoherent.**
4. **Zero instances in 573 scripts and 20 contract charts.** Not an argument that the defect is unreal — an argument about *our* exposure, which is what this gate measures. §2(b) establishes the absence positively, by scan and by targeted audit of the three plausible candidates, not by assumption.

**What would move it back to High:** evidence of a shape with **no** fresh-context or gateway alternative, or a catalogue action that genuinely needs to both emit and confirm within one step. Neither exists today. The postable files it at the severity *upstream* should act on — it breaks their own documented idiom — while our board carries it at Medium with three enforcing constraints. **Those are different questions and this document answers both.**

### 5.3 OUR-CONTRACT board — **2 Blocker · 1 High · 2 Medium**

Zero library-readiness impact. This board does **not** enter the decision table; it gates the canary (§10).

| ID | Severity | Chart | Status |
|---|---|---|---|
| **R12-13** (merges C-04 / CV-C04 / CD-02) | **Blocker** | B16 session/elevation | CONFIRMED, 12/12 lanes fail. Config-only. **Fix corrected this round** — the region-level `REVOKE` handler must also be deleted (§4.3). Open 7 rounds. |
| **R12-14** (merges C-07b / CV-C07b / CD-03) | **Blocker** | B18 kill switch | CONFIRMED, `bricked: true` both kinds. Config-only, fix proven 6/6 and 13/13. Open 7 rounds, unlanded (E50-T43). |
| **R12-15** (merges C-06 / CD-04) | **High** | B19 account lockout | CONFIRMED. Config-only, fix proven standalone in both lanes. Unrecoverable operational lockout as drafted. |
| C-04b | Medium | B16 | Unchanged, both lanes. |
| C-04c | Medium | B16 | Unchanged, both lanes. |

### 5.4 Refuted this round — three, all moving DOWN

| ID | Filed | Verdict | Why |
|---|---|---|---|
| **R12-01** | Blocker | **DOWNGRADE → Low** | The `engine` flag **is** consulted on the `scheduled_sends` path: `restore_event → _restore(..., trusted=record.get("engine") is True)`. The forged record restores as a **public `Event` with `e.data == {}`** — the `{'filled': 999999}` payload never arrives (verified both kinds, polled to convergence). Only *adding* `"engine": true` mints `_EngineDone`, and that is identically reachable via `pending_events` (#195) inside the documented `from_snapshot` trust boundary (#205: the snapshot is TRUSTED INPUT; `machine_hash` is a fingerprint, **not a MAC**; a forger already controls `configuration` / `context` outright). XState v5 restores persisted snapshots verbatim too. **Surviving narrower defect:** the `_admit_restored` bypass → strict-parity/observability gap, **Low** (§5.1). |
| **R12-02** | Blocker | **REFUTED** | Reproduced exactly — a forged `"version": 2` blob gets `engine: true` stamped by `persistence.upcast` and drives an `after`/`onDone` transition v3 would refuse. **But it is no escalation:** a plain v3 blob with no forged record, writing `configuration` / `context` verbatim, reaches the **identical** observable outcome. The proposed mitigation `minimum_version=3` refuses the v2 forgery yet leaves the equivalent v3 verbatim write untouched — **proving the trust boundary, not `upcast`, is load-bearing**. The behaviour is deliberate (#214: demoting would silently drop genuine 0.8.0-era `after` deadlines under #203's gate). Same accepted pattern as R10-01 / R11-01. Merged sources D11-fuzz-1, D11-semantics-1 and R11-01 **fall with it**. Residual non-defect: adoption guidance must say **`minimum_version=3` is hygiene, not a security control** (§7). |
| **R12-03** | Blocker | **REFUTED (Info)** | Re-ran at `de2da4e` plus a new vector matrix. **No forgery vector uses only the public API**: each requires importing a private `_`-prefixed name, poking the private `_provenance` slot on a frozen dataclass, already holding an engine-minted event (`_replace` retype — reachable only from code running *inside* the machine's own actions, which can already transition it arbitrarily), unpickling attacker-controlled bytes (equivalent to arbitrary code execution), or the documented `restore_event({"engine": true})` boundary. Public-API paths behave correctly: `is_system_event(DoneEvent(...))` is **False**, and a forged snapshot record without the flag restores as user traffic. Subclass preservation across `_replace` / pickle / deepcopy is **documented intent** (`events.py` #195 block; `_EngineMark.__reduce__` / `__deepcopy__`) so persisted inboxes keep provenance. XState v5 provides no stronger guarantee. Residual Info-level hardening option: override `_replace` on the private subclasses to return the public class. |

**Fifth consecutive round in which every Blocker/High candidate moved DOWN and none moved up.** Fourth consecutive round in which a provenance Blocker died on its own control probe. **Standing amendment 18 — "test every blob-write finding against the `state_ids`-only control BEFORE triage" — has now paid for itself four times, and R12-02 is its cleanest kill yet**, because the control and the exploit were run side by side and reached the same state.

The two candidates that **survived** at Blocker (R12-13, R12-14) and High (R12-15) are **ours** — catalogue JSON, fixable in config alone, no library-readiness impact. **For the second round running, the binding constraint on our order path is our own catalogue, not the library.**

---

## 6. GATE DECISION — the decision table of `20-adoption-gate.md` §7, walked in order

The first matching row wins. Every row is answered from a measurement taken at `de2da4e`, not carried.

| # | Condition | This round | Result |
|---|---|---|---|
| 1 | Any `ERROR` row in the gate output | **No.** 168 checks, 128 PASS / 40 FAIL, zero `ERROR` rows. The 40 FAILs are the standing carried-red set plus two load-sensitive thresholds, each triaged in writing (§2(a)). Exit code 1 is this gate's designed steady state. | **does not fire** |
| 2 | Library suite fails, or coverage drops below 86 % | **No — and for the first time in four rounds this is measured, not carried.** `suite-de2da4e.log`, complete: **3545 passed, 13 skipped, 0 failed**, 752 s; **total coverage 92.87 %** against the project's own 90 % floor and this row's 86 % bar. Per-module: `validation.py` 99 %, `sync_interpreter.py` 97 %, `persistence.py` 95 %, `interpreter.py` 92 %, `models.py` 88 %. The diff **weakens no test** — the delta is `+794 / −1` lines, all in the new `tests/test_round11_findings.py`; no `xfail`, no `skip`. | **does not fire** |
| 3 | Snapshot format changed while LC-21 is open | **No.** Layout v3 landed at `c78ce99` and is **unchanged** at `de2da4e`; #221 changes *when* parked records are re-emitted, not the layout. LC-21 is closed anyway — the envelope carries `version` (#205) and we pin `minimum_version=3` (CV-C52). | **does not fire** |
| 4 | Any filed **Blocker** repro still exits 1 (LC-01, LC-02, LC-03, LC-16) | **No.** All four closed and pinned; `verifyM`–`verifyM8` green on them. The two open Blockers on any board are **R12-13 / R12-14 — ours, our catalogue JSON, config-only** — and this row reads the *filed library* Blocker set. | **does not fire** |
| 5 | All Blockers closed; **> 5 High** open | **No.** Library High count is **0**. | **does not fire** |
| 6 | All Blockers closed; **1–5 High** open, each mechanically mitigated with a passing test; all Medium triaged | **Does not fire — the High row is empty.** This is last round's row, and the item that put us here (R11-04) is **closed at the mechanism** by #218: 93,168 beats, `handles_max_per_machine = 1`, **RSS Δ 0.00 MB**. The one candidate that could have held this row open — DE-L1 — is resolved at **Medium** by refutation on four independent grounds (§5.2). | **does not fire** |
| 7 | All Blockers closed; **1–5 High** open **without** enforced mitigations | **No.** High count is 0. | **does not fire** |
| 8 | **All Blocker and High closed; all Medium triaged; BENCH-1/2/6 not all met** | **FIRES.** Library board: **0 Blocker · 0 High**. All **3 Medium** triaged with named enforcing constraints (DE-L1 → CV-C25 + CV-C51 + CV-C64; R11-02(c) → CV-C42; R11-10 → CV-C60). **BENCH-1, BENCH-2 and BENCH-6 are all unmeasured this round** (`bench_c_timers` and `bench_h_candleviewer_budgets` both timed out, including a reduced-parameter retry). | **✅ MATCH** |
| 9 | All Blocker and High closed; all Medium triaged; **all** benchmark thresholds met | **Refused, explicitly and on the record.** BENCH-6 is not *met*; it is **unmeasured, for the fifth consecutive round**, and BENCH-1/BENCH-2 joined it this round. **A row that requires all thresholds met cannot be reached by absence of evidence.** Row 9 is the only row in this table that could retire CV-C12 and the external-scheduler mandate, and it stays shut until `bench_c_timers` produces a number. | **does not fire** |

### DECISION

> ### **ADOPT WITH CONSTRAINTS — decision-table ROW 8.**
> **Up two rows from round 11's row 6; level with round 10.** On all four lifecycle families (B1–B20), under **CV-C01…CV-C64** as recomputed in §7.

**What the recovery means, precisely.** Row 6 and row 8 are both "ADOPT with constraints", and the difference is not cosmetic. At row 6 **one of our constraints was containment for an open library defect** — CV-C47 was the only thing standing between `raise(delay=)` and a 455 MB/24 s leak. At row 8 **every remaining constraint is an architectural consequence of our own benchmarks**, not a fence around someone else's bug. Round 11's verdict said that closing R11-04 would flip the row; #218 closed it, and it flipped.

**What the ceiling means, precisely.** Row 9 — unconstrained ADOPT — is held shut by a measurement **we** owe, not by anything the library does. The distance from row 8 to row 9 is one benchmark script that has not been given a time slice of its own in five rounds. That is now the single highest-value item on the round-13 recipe (§10), and it is ours.

```
Gate run 2026-09-23 - xstate-statemachine main @ de2da4e (unreleased 0.8.1;
                      __version__ still reports 0.8.0 - KEY ON THE COMMIT)
  DECISION     : ADOPT WITH CONSTRAINTS - decision-table ROW 8 (up from row 6)
  issues       : 5 verified - 5 FIXED, 0 partial, 0 not-fixed, 0 regressed-on-one-axis
  gate         : 168 checks - 128 PASS / 40 FAIL (6 new checks, all PASS; exit 1 by design)
  sweep        : 573 scripts - 476 PASS / 94 FAIL / 3 TIMEOUT; TRUE REGRESSIONS: 0
  suite        : 3545 passed, 13 skipped, 0 failed - coverage 92.87% (COMPLETE RUN)
  determinism  : 59/59 under PYTHONHASHSEED=1 and 59/59 under =2
  benches      : bench_a OK, bench_j OK; BENCH-1/2/6 UNMEASURED (timeout) - row 9 refused
  library      : 0 Blocker | 0 High | 3 Medium | 6 Low
  ours         : 2 Blocker (R12-13, R12-14) | 1 High (R12-15) | 2 Medium - config-only, canary-gating
  refutation   : 2 Blockers REFUTED, 1 Blocker DOWNGRADED to Low; none moved up (5th round running)
  constraints  : CV-C01...CV-C64 (CV-C47/C61 RETIRE; CV-C12 STANDS; CV-C63, CV-C64 NEW)
  decided by   : round-12 readiness review, 69-r12-final-readiness-verdict.md
```

---

## 7. Constraints — retire / stand / new

### Does CV-C47 retire now that #218 is fixed?

**Yes. CV-C47 retires, and so does CV-C61.** This is the round's sharpest constraint question and it deserves the full argument, because retiring a constraint is the one move in this process that can silently re-open a closed defect.

**CV-C47** (no `raise(delay=)` self-paced periodic work) has been written twice and grounded twice. Its **original** ground was R10-03 — the heartbeat dies at `maxIterations` — which **#212 closed** in round 11. Round 11 did not retire it, because R11-04 handed it a **new** ground the same week: the unbounded `_timer_handles` leak. Round 11 recorded it as "STANDS, WIDENED, and becomes LOAD-BEARING", and **CV-C61** widened the ban into a ban-plus-narrow-exception with a handle-count gauge and a soak assertion.

**#218 closes that second ground at the mechanism, and the evidence is the kind that permits retirement rather than the kind that merely fails to find the defect:**

- the round-11 repro, **unmodified**, now exits 0 (`retained_per_beat: 0.0` over ~630 beats);
- **200 machines × 10 s = 93,168 beats → `handles_max_per_machine = 1`, RSS Δ 0.00 MB**, against round 11's **+753 MB** on the identical script;
- a 150-s / 200-machine soak reads **1.00 handles per machine**, flat;
- the **cancel** path is covered too — a 500× arm/cancel storm peaks at **0** handles with no double-release, and cancel-after-fire is a clean no-op;
- `STOP` releases the handle;
- and the mechanism is understood, not merely observed: `_schedule_send` keyed under the **machine** id while the only pruner popped by **state** id; both engines now release on fire and on cancel.

**Both grounds are closed, by two different releases, each verified at the mechanism.** A constraint with no surviving ground is not a safety margin — it is rot, and rot is what trains readers to ignore the lint file. **CV-C47 and CV-C61 retire.**

**But the retirement is narrow, and three things do not move:**

1. **CV-C12 (`after` banned in catalogue machines) STANDS, UNCHANGED.** Its ground is **BENCH-6**, which is not merely still missed (174.4 ms against a ≤100 ms bar at last measurement) but **unmeasured for five consecutive rounds**. #218 fixed a *handle-retention* defect; it says nothing about *drift under load*. Retiring CV-C12 on the strength of #218 would be answering a timing question with a memory measurement. All algo timing stays on the external `MonotonicScheduler` with absolute `*_us` deadlines in context.
2. **`raise(delay=)` is not thereby *recommended*.** With CV-C47 and CV-C61 gone, `raise(delay=)` is permitted on the same terms as `after` — which CV-C12 confines to coarse, non-critical timeouts. **Nothing becomes newly legal for algo timing.** CV-C55 (no delay below 10 ms) and R11-W-1 (stable `send_id` on every chart deadline) continue to apply to both spellings.
3. **The handle-count gauge survives CV-C61's retirement, demoted from mitigation to telemetry.** It cost nothing, it is the instrument that would catch a recurrence, and it is the reason this round could assert 1.00/machine rather than "we saw no growth". Folded into CV-C28′s observability set, not into the lint.

### Retired (2)

| Constraint | Why it retires |
|---|---|
| **CV-C47** — no `raise(delay=)` self-paced periodic work | **Both grounds closed.** R10-03 (heartbeat dies at `maxIterations`) closed by #212 in round 11; **R11-04 (unbounded handle retention) closed by #218**, measured at 93,168 beats with **RSS Δ 0.00 MB** and `handles_max = 1`, on both engines and both kinds, with the fire path, the cancel path, the supersede path and `stop()` all covered. CV-C12 continues to confine what `raise(delay=)` may be *used for*. |
| **CV-C61** — `raise(delay=)` only for restart-critical deadlines, with a handle gauge and a soak assertion | **Retires with its parent.** It existed solely to narrow CV-C47's ban around R11-04. **The gauge survives as telemetry** under CV-C28′; the stable-`send_id` clause survives as **R11-W-1**, which was always independent. |

### Standing (unchanged or re-grounded)

**CV-C01…CV-C22** as amended, **including CV-C12 unchanged** (above) · **CV-C23** (quiescence-only snapshots via the factory wrapper; envelope carries `version ≥ 1` + `machine_hash` + **HMAC tag**) — **re-grounded again and now load-bearing for a third round**: R12-01's and R12-02's refutations *both* turn on `from_snapshot` being a documented trusted-input boundary with `machine_hash` explicitly "a fingerprint, not a MAC". **The HMAC tag is the boundary** · **CV-C25** (no external `send()` from inside an action; gateway queue only) — **strongly re-grounded on DE-L1**: it is the reason #219's breaking change cost us nothing, and §0 records that as anticipation rather than luck · **CV-C27′** · **CV-C28′** (no `LoggingInspector` in production; **now also carries the `_timer_handles` gauge as telemetry**) · **CV-C32** · **CV-C33** · **CV-C34** · **CV-C35** · **CV-C36** · **CV-C40** · **CV-C41** · **CV-C42** (no `priority=True` anywhere, any origin) — re-grounded on R11-02(c)/R11-12 and carried-unverified D11-security-5 · **CV-C44** · **CV-C45″** · **CV-C49′** (snapshot only at quiescence; **never re-persist an interpreter that has not been `start()`ed**) — **its ground is closed by #221** (640/640 verbatim across compaction hops) **but it is RETAINED as defence in depth**, because the constraint costs nothing and #221's fix is one release old; re-examine in round 13 · **CV-C50** · **CV-C51** (no entry/exit action may await a receipt on its own interpreter) — **now enforced by the library itself** via #219, which makes it a lint that agrees with the runtime instead of substituting for it · **CV-C52** (`minimum_version=3` at every restore site) — **re-grounded and re-labelled**: R12-02 proves it is **hygiene, not a security control**; keep it, and stop describing it as a defence · **CV-C53** (the snapshot journal is MAC'd at rest) — **the load-bearing security constraint on this board**, and the boundary both R12-01's and R12-02's refutations rest on · **CV-C54** (restore reconciles persisted vs admitted record counts) — **re-grounded on R12-01's surviving residual**, the `scheduled_sends` strict bypass · **CV-C55** (no delay below 10 ms in `raise(delay=)` **or** `after`) · **CV-C56** (`start()` wrapped in `asyncio.wait_for`) — **its ground R11-06 is closed by #219**, retained because a bounded `start()` is cheap insurance against the *next* descent-gate change · **CV-C57** (the wrapper runs its **own** recursive key check over every state node) — **re-grounded on Q-5**: #220 now covers what CV-C57 was written for, *except* inline-machine `invoke.src`; the constraint survives on the remaining hole · **CV-C58** · **CV-C59** (supervisors must not poll `last_error` for chain health) — **re-grounded on #222 itself**: the library now provides the latch CV-C59 demanded, so the constraint becomes "use `chain_trips` / `last_chain_error` / `on_chain_budget_exceeded`, never `last_error`" · **CV-C60** · **CV-C62** · **the wrapper top-level config-key whitelist** — **stands, narrowed**: #220 now covers every level *except* inline `invoke.src`, so the whitelist's job shrinks to that hole plus our own non-library keys.

Plus the three **needs-wrapper** rules, all standing: **R11-W-1** (stable `send_id` on every chart deadline — now applies to `after` and `raise(delay=)` equally), **R11-W-2** (never register a user action colliding with a built-in), **R11-W-3** (`SimulatedClock` fires neither `after` nor restored `scheduled_sends` on this build — deadline properties verified against the real clock; **carried-unverified this round**, so it stands by default).

### New (2)

| ID | Constraint | Ground | Enforcement |
|---|---|---|---|
| **CV-C63** | **Chain-trip durability is the wrapper's job.** Read `chain_trips` and `last_chain_error` **before** `get_persisted_snapshot()` and write both into the wrapper's own envelope; on restore, seed the supervisor from the envelope, not from the interpreter. The library's latch is a **process-local live-supervision signal** and is deliberately not a snapshot field — so a restart silently resets "this machine discarded work" to zero. | D12-security-1 / Q-7 | `test_cv_c63_chain_trips_survive_restart`; assertion in the snapshot wrapper. |
| **CV-C64** | **No action may `await send(..., wait=True)` on its own interpreter, and no action may hand out an `ensure_future` receipt on its own interpreter either.** #219 refuses the first loudly and — via an inheritable `ContextVar` — refuses the second unpredictably (DE-L1). If a helper task spawned inside an action must talk to the machine, it goes through the **gateway queue** (CV-C25) or is spawned with a **fresh context**. A **`def`** action calling `send(..., wait=True)` gets an unawaited `_Awaitable` — no error, no warning, no receipt — so the lint covers both kinds. **Run this lint over every action body BEFORE upgrading past `c78ce99`**: #219 is a deliberate breaking change. | DE-L1 / Q-1; #219 as a breaking change; the `def`-lane observation | Extends CV-C51's lint to helper-spawn sites (`ensure_future`, `create_task`, `wait=True`); `test_cv_c64_no_self_receipt_from_action_or_helper` — must pass on **both** kinds. |

**Net: 2 retired, 2 new, 62 standing → CV-C01…CV-C64.** The count is flat and the character has changed: **for the first time since round 10, no constraint on this list is containment for an open library defect.** CV-C51 and CV-C59 are now *agreements with the runtime* rather than substitutes for it — the library enforces what they assert — which is the healthiest state a constraint can reach short of retirement.

### FINAL mandatory config block

```jsonc
// Every CandleViewer machine definition. ROUND 12, main @ de2da4e (unreleased 0.8.1;
// __version__ STILL reports 0.8.0, twelfth round running - PIN ON THE COMMIT).
// Decision: ADOPT WITH CONSTRAINTS, decision-table ROW 8 (up from row 6).
{
  "strictConfig": true,              // #216 + #220. Either this key or the strict_config=True
                                     // kwarg raises InvalidConfigError on an unknown key;
                                     // either ALONE is sufficient (verified). We set BOTH.
                                     // ROUND-12 SCOPE UPDATE: #220 makes this RECURSIVE -
                                     // nested states, parallel regions, on/always/after/onDone
                                     // transition bodies, invoke entries and their
                                     // onDone/onError, with per-level known sets and
                                     // PATH-NAMED findings ("m.r2.y.z: 'tpye' (did you mean
                                     // 'type'?)"). Round 11's 0/120-nested-typos hole is CLOSED:
                                     // 638/640 caught, 11/11 nesting levels, 0 false positives
                                     // on 400 valid charts. x-/meta/description/tags accepted
                                     // at EVERY level.
                                     // ALL 20 OF OUR CHARTS BUILD CLEAN UNDER IT, 0 WARNINGS,
                                     // BOTH LANES - so nothing in B1-B20 was silently dropping
                                     // an entry action or a transition at c78ce99.
                                     // REMAINING HOLE (Q-5): it does NOT recurse into an
                                     // inline-machine invoke.src. -> CV-C57 STANDS, re-grounded
                                     // on exactly that hole. Do not retire the wrapper's own
                                     // recursive check.

  "actionErrorPolicy": "rollback",   // R10-D1 unchanged: rollback + invoke.onDone RE-ARMS the
                                     // service and each lap is a real exchange order. Services
                                     // MUST be idempotent under re-entry - client order id
                                     // keyed on CHART STATE, never on lap.
  "guardErrorPolicy": "deny",        // A guard-denied event IS an unhandled event (#170).
                                     // Any state whose only arm is guarded needs an ORDERED
                                     // UNGUARDED FALLBACK. This is R12-14 (was C-07b) - OURS,
                                     // Blocker, open SEVEN rounds, fixable in config alone.

  "onUnhandled": "defer",            // order path. No "*" scaffolding (CV-C34).
                                     // NEVER "error" on a control chart: R12-14 proves one
                                     // guard-denied RELEASE under onUnhandled:"error" makes the
                                     // machine FATAL (status='error') and BRICKS the kill switch
                                     // - the next AUTHORISED release is accepted by send() and
                                     // silently dropped. B18 must move to "defer" + an ordered
                                     // UNGUARDED auditing RELEASE fall-through (proven 6/6).
                                     // Kill/cancel events declared on an ANCESTOR of every
                                     // invoking state, never only on siblings.
                                     // AND: "defer" is not free either - R12-15 shows an event
                                     // with no arm in the active region PARKS FOREVER. Every
                                     // operator-recovery event needs an arm in EVERY state it
                                     // must be honoured in (B19 stale_lockout.on.OPERATOR_RESOLVED).

  "strictTargets": true,             // unchanged.
  "strict": true,                    // unchanged. NOTE (R12-01 residual): strict IS enforced on
                                     // restored pending_events but is SILENTLY BYPASSED on
                                     // restored scheduled_sends (last_error stays None) -
                                     // _rearm_restored_self_sends never calls _admit_restored.
                                     // -> CV-C54 count reconciliation is the cover. Low, filed.

  "maxIterations": 1000,             // CV-C62 sizing: descent-seeded chains get maxIterations+3
                                     // laps, externally kicked ones exactly +2. Sizing against
                                     // the external number under-provisions descent by ~2.7x.

  // --- TIMING (the one place round 12 CHANGED the rules) ---------------------
  // CV-C47 and CV-C61 RETIRE this round: #218 closes the unbounded _timer_handles
  // leak at the mechanism (93,168 beats -> handles_max_per_machine = 1,
  // RSS delta 0.00 MB, vs +753 MB at c78ce99), and #212 had already closed the
  // heartbeat-dies-at-maxIterations ground. BOTH grounds are gone.
  //
  // THIS DOES NOT MAKE raise(delay=) RECOMMENDED. CV-C12 STANDS UNCHANGED:
  // `after` (and now raise(delay=), which #212 made its equal) is permitted ONLY
  // for COARSE, NON-CRITICAL timeouts where seconds of lateness is tolerable.
  // Its ground is BENCH-6 - 174.4 ms against a <=100 ms bar at last measurement,
  // and UNMEASURED FOR FIVE CONSECUTIVE ROUNDS. A constraint whose ground has not
  // been re-measured cannot be retired: that would be deciding on absence of evidence.
  //
  // ALL ALGO TIMING (TWAP intervals, chase repricing, iceberg release) stays on the
  // external MonotonicScheduler with absolute *_us deadlines in context.
  // CV-C55: no delay below 10 ms, in either spelling. R11-W-1: every chart deadline
  // carries a STABLE send_id. R11-W-3: SimulatedClock fires NEITHER `after` NOR
  // restored scheduled_sends on this build - verify deadline properties on the real clock.
  // Telemetry (survives CV-C61's retirement): export
  // len(i._timer_handles.get(i.id, [])) as a gauge. It is the instrument that
  // would catch a recurrence.

  // --- ACTIONS: READ THIS BEFORE UPGRADING PAST c78ce99 ----------------------
  // #219 IS A BREAKING CHANGE. An action that awaits send(..., wait=True) on its
  // OWN interpreter now raises ReentrantWaitError instead of deadlocking. The sync
  // engine refuses the same shape for parity.
  // OUR CATALOGUE NEEDED ZERO CHANGES - verified positively, not assumed: 0 of 573
  // corpus scripts and 0 of 20 contract charts contain the shape (f7_r11.py 5/5,
  // e6_round11.py 8/8 per lane). That is CV-C25 doing its job since round 5, not luck.
  // CV-C64 (NEW) makes the audit standing, and extends it: the DOCUMENTED escape
  // hatch asyncio.ensure_future(i.send(..., wait=True)) is ALSO unsafe (DE-L1) -
  // the guard rides an INHERITABLE ContextVar, so a task spawned inside an action
  // keeps _ACTIVE_ACTION_OWNER for its whole life and is refused even 300 ms after
  // the machine went idle. If a helper must talk to the machine: gateway queue
  // (CV-C25), or spawn it with a FRESH contextvars.Context().
  // A `def` action calling send(wait=True) gets an unawaited _Awaitable - no error,
  // no warning, no receipt. Lint BOTH kinds.

  // --- SUPERVISION (#222 gives us the API CV-C59 asked for) ------------------
  // Never poll last_error for chain health - it is the PER-STEP read it always was,
  // and one benign event erases it. Use interpreter.chain_trips (monotonic),
  // interpreter.last_chain_error (a latch; cleared only by clear_chain_error()) and
  // PluginBase.on_chain_budget_exceeded (fires exactly once per trip, settle-budget
  // trips included). on_event_dropped(reason='chain_budget') PRECEDES it; either is
  // safe to key a supervisor on.
  // CV-C63 (NEW): the latch is PROCESS-LOCAL - chain_trips and last_chain_error are
  // NOT snapshot fields (restored_chain_trips = 0, restored_latch = null). Read both
  // BEFORE get_persisted_snapshot() and carry them in the WRAPPER's envelope, or a
  // restart silently resets "this machine discarded work" to zero.

  // --- PERSISTENCE ------------------------------------------------------------
  // minimum_version=3 at every restore site (CV-C52) - RE-LABELLED this round:
  // R12-02 proves it is HYGIENE, NOT A SECURITY CONTROL. It refuses a forged v2 blob
  // while leaving an equivalent v3 verbatim write untouched, which is exactly what
  // shows the TRUST BOUNDARY - not upcast - is load-bearing.
  // THE boundary is CV-C53: the snapshot journal is MAC'd at rest by the wrapper.
  // from_snapshot documents the snapshot as TRUSTED INPUT and machine_hash as
  // "a fingerprint, not a MAC" (#205). Both Blocker refutations this round rest on it.
  // CV-C49' retained as defence in depth even though #221 closed its ground
  // (640/640 verbatim across compaction hops): never re-persist an un-start()ed
  // interpreter. Re-examine in round 13.
  // CV-C54: reconcile persisted pending_events + scheduled_sends against admitted
  // records and fail loudly - the cover for R12-01's surviving strict-bypass residual.
  // CV-C60: read last_error / last_transition_ok immediately after from_snapshot and
  // BEFORE start(); on_invalid_event is structurally unreachable there (D11-security-4).
}
```

---

## 8. Release readiness — would we pin a tag cut at `de2da4e`?

**Yes. Unreservedly, and with nothing required to land first.**

This is the first round in twelve where the answer has no conditional clause attached, so it is worth being explicit about what is being claimed and what is not.

### The case for tagging

| Criterion | At `de2da4e` |
|---|---|
| Library Blockers | **0** — fourth consecutive round |
| Library Highs | **0** — first time since round 10 |
| Upstream suite | **3545 passed, 13 skipped, 0 failed**, complete run at the commit under test |
| Coverage | **92.87 %**, above the project's own 90 % floor and this gate's 86 % bar |
| True regressions vs the prior commit | **0** — across 168 gate checks and a 573-script sweep, sixth round running |
| Fixes claimed vs fixes verified | **5 of 5**, both engines, both service spellings — third consecutive clean set |
| Fixes with no scope residual | **3 of 5** — best in the series |
| Test integrity of the diff | `+794 / −1` lines, **no test deleted, weakened, `xfail`ed or skipped**; the one test edit (`30ae276`) *strengthens* a #219 pin and adds an assertion |
| Determinism | 59/59 under `PYTHONHASHSEED=1` and 59/59 under `=2` |
| Our contract corpus | 20/20 charts build clean under the new recursive strict check, 0 warnings, both lanes |

**Nothing on the library board must land before a tag.** The three open Mediums and six Lows are all either contained by constraints we already lint, adjacent-scope gaps, or documented trust boundaries. To be concrete about the strongest candidate: **DE-L1 is a real defect and should be fixed**, but it breaks a pattern that **our own CV-C25 has banned since round 5**, it fails **loudly**, and it is **strictly safer than the silent `start()` deadlock it replaced**. That is not tag-blocking. It is the first item of the next patch release.

**Recommendation: cut and tag 0.8.1 at `de2da4e`.** It is materially better than `c78ce99` on every axis we measure and worse on none.

### The one thing that must ship *with* the tag (not before it)

**`__version__` must be bumped to `0.8.1` in the same commit as the tag.** It has reported `0.8.0` on an `[Unreleased] — targeting 0.8.1` tree for **twelve consecutive rounds** (Q-8). This is not a defect in the library's behaviour and it does not block the cut — but a tag that ships with a wrong version string converts a harmless inconsistency into a **distributed** one: every downstream pin, CI assertion and bug report keyed on `xstate_statemachine.__version__` will then mis-identify a *released* build, and unlike an unreleased commit, a released build cannot be re-cut quietly. **Bump the string, then tag.**

### What the release notes must say, in these words

1. **`ReentrantWaitError` is a breaking change for user actions** (#219). An action that awaited `send(..., wait=True)` on its own interpreter previously deadlocked and now raises. Audit every action body for `wait=True`, `ensure_future` and `create_task` before upgrading. This deserves a bullet at the top of the notes, not a line inside a fix list — **it is the only change in the set that can break working code.**
2. **The documented `ensure_future` escape hatch is not yet reliable** (DE-L1). Until the guard's predicate is narrowed, the safe spellings are: send from **outside** any action, or spawn the helper with a **fresh `contextvars.Context()`**. Saying this in the notes costs nothing and saves the first adopter who follows the idiom a day.
3. **`strictConfig` now recurses** (#220). A machine that built clean on 0.8.0 may now raise `InvalidConfigError` — **and if it does, the typo was always there and was always silently dropping an action or a transition.** Frame it as a discovery, not a regression.
4. **`last_error` is documented as a per-step read; chain stickiness moved to the new API** (#222). Any supervisor polling `last_error` for chain health must move to `chain_trips` / `last_chain_error` / `on_chain_budget_exceeded`. Note that the latch is **process-local and not persisted**.
5. **Snapshot layout is v3, unchanged from the prior commit**; `minimum_version=3` is **hygiene, not a security control** (R12-02). Authenticate snapshots at the storage boundary — `machine_hash` is a fingerprint, not a MAC, and the docstring already says so.

### What we would pin, in our own tree

```
xstate-statemachine == 0.8.1        # tag cut at de2da4e, ONLY IF __version__ == "0.8.1"
                                    # otherwise: pin the COMMIT, as we have for twelve rounds
```

Until the tag exists with a correct version string, **our pin stays keyed on the commit `de2da4e`** — the same rule that has protected every gate baseline in this study.

### What is *not* resolved by tagging

The two Blockers and one High that remain open are **ours** — R12-13, R12-14, R12-15, all catalogue JSON, all config-only. **A tag does not touch them, and they gate the canary, not the adoption.** That distinction is the whole content of §10.

---

## 9. What would change the verdict

Written so a future reader can falsify this round rather than re-litigate it. Each trigger names the measurement that would fire it.

### Would move us DOWN from row 8

| Trigger | Consequence | Why it is live |
|---|---|---|
| **A catalogue action, or any shape with no fresh-context / gateway alternative, is found to need an in-step self-`send(wait=True)` or an `ensure_future` receipt.** | **DE-L1 returns to High → row 6.** | This is the explicit falsifier for §5.2's row-deciding call. It is a *finding*, not an opinion: produce the shape and the severity moves. CV-C64's lint is where it would surface. |
| **`_timer_handles` growth reappears on any shape** — the gauge (CV-C28′ telemetry) reads above 1 per machine on a steady heartbeat, or a soak shows non-flat RSS. | **CV-C47 / CV-C61 un-retire; R11-04 reopens at High → row 6.** | The retirement in §7 is the round's boldest move. It rests on 93,168 beats at `handles_max = 1` and RSS Δ 0.00 MB across the fire, cancel, supersede and `stop()` paths — but it is one release old, and the gauge is retained precisely so this is detectable. |
| **The upstream suite fails, or coverage drops below 86 %, at a future commit.** | **Row 2 fires → DEFER**, before any adoption row is reached. | Row 2 sits above everything. This round is the first in four where it rests on a measurement at the commit under test; that must not regress to a carry-over. |
| **A `PASS → FAIL` delta survives ×5 serial re-runs and is not superseded by a documented rule change.** | First **true** regression in six rounds → re-open the round. | The sweep produced 11 candidate deltas and all 11 dissolved under serial re-run or supersession. One that does not dissolve is a different kind of event. |
| **A forgery vector is found that uses only the public API and achieves more than the `state_ids`/`context`-only control.** | R12-01/02/03 reopen; the security board moves from Info to live. | This is standing amendment 18 stated as a falsifier. Four provenance Blockers have now died on this control; the fifth might not. |
| **A new library Blocker or High at a future commit.** | Row 4/5/6 as applicable. | The ordinary case. |

### Would move us UP from row 8 to row 9 (unconstrained ADOPT)

**Exactly one thing, and it is ours.**

| Trigger | Consequence |
|---|---|
| **BENCH-6 (loaded timer drift) is measured and met (≤100 ms under `load_100` / `load_500`), together with BENCH-1 (order-path headroom ≥ 3×) and BENCH-2 (rule rate ≥ 2,000 ev/s).** | **Row 9 fires: ADOPT, unconstrained.** **CV-C12 retires**, `after` and `raise(delay=)` become usable for real timing, and the external `MonotonicScheduler` mandate — the single largest architectural constraint this study has imposed on CandleViewer — is lifted or narrowed. |

Note the asymmetry deliberately: **BENCH-6 being *measured and missed* does not move us at all** — it would merely re-ground CV-C12 on a fresh number instead of a five-round-old one, which is itself worth doing. Only *measured and met* opens row 9. The last reading was **174.4 ms against a ≤100 ms bar**, so the honest prior is that BENCH-6 will be missed and CV-C12 will stand on solid ground rather than stale ground. **We should want the measurement either way; we should not assume the outcome.**

### Would change the *tag* recommendation (§8)

| Trigger | Consequence |
|---|---|
| The tag is cut **without** bumping `__version__` to `0.8.1`. | The recommendation stands but the pin does not change: **we keep pinning the commit**, and we say so in the postables. A released build with a wrong version string is a distributed problem, not a local one. |
| A library Blocker or High appears between `de2da4e` and the tag commit. | Re-run the gate at the tag commit. **A tag is a new build**, and this study's binding rule is that nothing is verified by inheritance. |

### Would NOT change the verdict

Stated because these have been proposed in prior rounds and each would be an error:

- **Closing R12-13 / R12-14 / R12-15.** They are **ours**. Fixing them un-gates the canary, not the adoption. The gate row is computed from the **library** board only, and conflating the two boards is how a config bug becomes an argument against a dependency.
- **`__version__` staying at `0.8.0` on an untagged commit.** Twelve rounds of keying on the commit have made this cost us nothing. It is a Low and it stays one — right up until a *tag* ships with it (§8).
- **The gate's exit code 1.** It is the designed steady state: the gate deliberately retains a standing red set of carried findings. A gate that goes green by deleting its own history is worse than one that stays red honestly.
- **`bench_j`'s `rollback_and_defer` at 0.631×.** Read low twice now. That makes it **the real number**, not a regression — and it supersedes round 11's "should be re-checked" flag. It is an input to budget sizing, not to the verdict.

---

## 10. Next steps

### 10.1 Round-13 recipe — in this order, and the order is the point

1. **`bench_c_timers` FIRST, ALONE, with a dedicated 300 s slice.** BENCH-6 has gone unmeasured for **five consecutive rounds**, and every one of those rounds attempted it *alongside* other work inside a shared budget. **The method has failed five times; change the method, not the effort.** Run `load_100` at two delays and nothing else if that is what fits. This is the only item that can open row 9, and CV-C12 — our largest architectural constraint — stands on its stale number.
2. **`bench_h_candleviewer_budgets` SECOND, ALONE.** BENCH-1 and BENCH-2 fell out this round only because they share a script with a timeout. Give it its own slice; it does 500-order populations sequentially and has never fitted in a shared budget either.
3. **Suite + coverage as a background run started first** — the round-12 pattern, which worked, and which produced the first complete measurement in four rounds. Keep it.
4. **Run the regression sweep SERIALLY** (or retire the parallel driver for the timing-sensitive subset). `R11-H-1` is now **binding**, not advisory: 6 workers produced 4 false FAILs in round 11, 10 workers produced **11** in round 12. The error scales with the worker count and costs more triage than the parallelism saves.
5. **Re-examine CV-C49′** (never re-persist an un-`start()`ed interpreter). #221 closed its ground at 640/640; it was retained this round as one-release-old defence in depth. If #221 holds at the next commit, retire it.
6. **Re-run the three carried-unverified Lows** — D11-security-5 (sync restore lane), D11-security-6 / R11-W-3 (`SimulatedClock` and restored `scheduled_sends`), and R12-02's residual doc note. Each was carried, not verified, this round and is recorded as such.

### 10.2 Phase-3 gates

**Phase 3 continues, and row 8 is the position it needs.** The library is no longer the binding constraint on any Phase-3 gate.

| Gate | Status at `de2da4e` |
|---|---|
| **G-P3-1 — library adoption** | **MET.** Row 8, 0 Blocker / 0 High on the library board, suite complete at 92.87 %, zero true regressions for six rounds. |
| **G-P3-2 — contract corpus builds and drives clean on both service spellings** | **MET for 17 of 20 charts.** The three exceptions are R12-13 (B16), R12-14 (B18), R12-15 (B19) — **all ours, all config-only**. |
| **G-P3-3 — linter + `tests/xstate_contract/` green** | **NOT MET — and it is now the single gating condition, as it has been since the 0.8.0 register.** `E29-T10` and the contract test package have not shipped. CV-C63 and CV-C64 are new tests this round; CV-C47 and CV-C61 retire theirs. **An unenforced rule is not a rule (MUST-09)**, and the whole row-8 argument depends on constraints being mechanically enforced. |
| **G-P3-4 — two-week canary on the order path** | **BLOCKED by R12-13 and R12-14 only.** Both are ours, both are config-only, both are proven fixed by a patch that passes 6/6 and 13/13 on both engines and both spellings. **Nothing upstream blocks this gate.** |

### 10.3 E50 — backlog actions

| Item | Action |
|---|---|
| **E50-T43** (land the C-04 / C-07b config fixes) | **P1, unblocked, and the highest-value item on the board.** Open **seven rounds**. **Acceptance criteria AMENDED this round:** the C-04 remedy is *not* the root hoist alone — the root hoist fixes **9 of 12** lanes because the deeper `elevated.on.REVOKE` handler outranks the root arm. **The region-level `REVOKE` handler must also be deleted.** Verify 12/12 across both engines, both spellings and all four kill events. |
| **E50-T53** (CV-C62 + the three R11-W lints) | **Un-parks and shrinks.** Round 11 parked it noting that one of its items (E50-T45) contained an **open library High** — that is no longer true; #218 closed R11-04. It is now purely additive hardening, as round 10's set was. |
| **E50-T45** (CV-C47 / CV-C61 enforcement: the `raise(delay=)` ban and handle gauge) | **RETIRE the lint half; KEEP the gauge.** Both constraints retire (§7). The `_timer_handles` gauge survives as **telemetry** under CV-C28′ — it is the instrument that would detect a recurrence and the reason this round could assert 1.00/machine rather than "we saw no growth". |
| **NEW — E50-T54** (CV-C63: chain-trip durability in the wrapper envelope) | **P2.** Read `chain_trips` / `last_chain_error` before `get_persisted_snapshot()`, carry them in our envelope, seed the supervisor from it on restore. Test `test_cv_c63_chain_trips_survive_restart`. |
| **NEW — E50-T55** (CV-C64: the self-receipt lint, both kinds, **pre-upgrade**) | **P1 — must run BEFORE the dependency bump.** #219 is a deliberate breaking change. Lint every action body for in-step `send(wait=True)`, for `ensure_future` / `create_task` helper-spawn sites that later send, and for the `def`-lane unawaited-`_Awaitable` shape. Our corpus is clean today (0/573, 0/20) — the lint keeps it that way. |
| **E50-T34** (contract test package) | Precondition (ii) now reads CV-C01…**CV-C64**, minus retired CV-C47 / CV-C61. |
| **E50 epic** | Gate row recorded as **8**; ADR-0016 **Amendment 12**. |

### 10.4 What remains OURS

**Everything still open on the order path.** Stated plainly because it is the study's most important structural result and this is the second round it has held:

- **R12-13** (B16, elevation outlives session) — **Blocker**, ours, config-only, **open seven rounds**, fix corrected this round.
- **R12-14** (B18, kill switch bricked by one guard-denied press) — **Blocker**, ours, config-only, **open seven rounds**, fix proven 6/6 and unlanded.
- **R12-15** (B19, operator cannot clear a stale lockout) — **High**, ours, config-only, fix proven standalone in both lanes.
- **C-04b, C-04c** (B16) — Medium, ours, unchanged.
- **G-P3-3** — the linter and `tests/xstate_contract/`: ours, unshipped, and **the single gating condition** for the whole constraint argument.
- **BENCH-6, BENCH-1, BENCH-2** — ours to measure, unmeasured, and the only thing between row 8 and row 9.

**Six items. Not one of them is upstream.**

### 10.5 The one-line summary

**Round 11's regression is reversed at the mechanism, not papered over: #218 closed the leak that cost us a row, #219 converted a silent deadlock into a loud error, #220 proved retroactively that none of our twenty charts was ever silently dropping an action, and the suite finally finished — 3545 passed at 92.87 %. The library board is 0 Blocker, 0 High for the first time since round 10, the gate returns to ROW 8, and a tag cut at `de2da4e` is one `__version__` bump away from being the release we pin. Everything still blocking the order path is ours.**

---

## 11. Artefacts produced this round

| File | Contents |
|---|---|
| `65-r12-regression.md` | Gate (168 checks) + 573-script sweep, every delta ×5 serial |
| `65-r12-01-refutation.md` | R12-01 Blocker → Low |
| `66-r12-suite-bench.md` | Complete suite + coverage, hash-seed determinism, benchmarks |
| `67-r12-diff-review.md` | `c78ce99..de2da4e`, probes Q-1…Q-8 |
| `68-r12-14-refutation.md` | R12-14 CONFIRMED Blocker (ours) |
| `69-r12-final-readiness-verdict.md` | **this document** |
| `suite-de2da4e.log` | Upstream pytest + coverage, complete |
| `battle-de2da4e/*.md` + tracks | 8 battle tracks, 5 with empty new-defect registers |
| `battle-de2da4e/contracts/` | 20 contract charts, both lanes |
| `issues/verify-main-de2da4e/` | 7 independent fix pins for #218–#222, all PASS |
| `refutations/r12-15-b19-operator-clear.py` | R12-15 fix proof, both lanes |
| `gate/result-main-de2da4e.json`, `r12_*` | Machine-readable gate + sweep + flake results |
| `issues/post-de2da4e/` | **Draft postables — NOT POSTED** |
