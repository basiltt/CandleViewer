# 64 — Round-11 FINAL readiness verdict: `xstate-statemachine` main @ `c78ce99` (unreleased 0.8.1)

Date: 2026-09-22. Round 11. Prior decision (round 10, `19cb1f1`): **ADOPT WITH CONSTRAINTS, decision-table row 8**.

**Identify this build by commit, never by version string.** `__version__` still reports `0.8.0` on `c78ce99` (merge of PR #217, `fix/0.8.1-round10`) while `CHANGELOG.md [Unreleased]` targets 0.8.1. Every pin, CI assertion and gate baseline keys on the commit.

Method: 5 issue verifications (#212–#216) re-run live (`issues/verify-main-c78ce99/`); full regression sweep — gate (163 checks) plus a 527-script sweep, every delta re-confirmed **serially** (`60-r11-regression.md`); suite + benchmarks (`61-r11-suite-bench.md`, `suite-c78ce99.log`); diff review `19cb1f1..c78ce99` (`62-r11-diff-review.md`); 8 battle tracks plus contracts (`battle-c78ce99/`); triage → dedupe (`63-r11-findings-register.md`) → **independent adversarial refutation of every Blocker and High**, applied below.

**Financial-OMS standard applied throughout:** nothing counted without a standalone repro on a clean interpreter from neutral cwd `<home>`, and **every service/action check run with both `def` and `async def`**.

**Two semantic reversals honoured throughout:** (a) **#212 supersedes #206** — a `raise(delay=)` self-send is a timer; a 1 ms self ping-pong is a legal periodic process, not a runaway. (b) **#213 introduces snapshot layout v3** with `scheduled_sends`; **#214** applies `strict` on restore, upcasts v2 `done`/`error`/`after` records as engine-minted, and records carry `lane`.

---

## 0. The answer

### Are the reported issues genuinely closed?

**Yes — all five (#212, #213, #214, #215, #216), on both engines and both service spellings.** This is the second consecutive round in which every fix the release claims verifies clean. #212's timer semantics are exact, not approximate — the measured `raise(delay=)` beat rate is indistinguishable from the `after:` spelling at every rung, 2000/2000 livelock-fuzz cells clean, and zero-delay cycles still trip. #213's v3 round-trip is exact on 600/600 armed-send trials (right `remaining_ms` ±0.5 ms, right `send_id`, fires not early, not late, exactly once). #214's strict-on-restore works for `pending_events`. #215's lap parity holds on the shapes it pins and `start()` descent-settle is bounded under 100 concurrent starts. #216's top-level key check is flawless where it looks: 47/47 mutations warned with a correct did-you-mean, 47/47 raised under `strict_config=True`.

Three of the five carry a **scope residual** rather than a defect in what they fixed: #214's strict check was applied to `pending_events` but not to the `scheduled_sends` field added in the same release (R11-02, Low after refutation); #216 validates the root dict only, while `KNOWN_MACHINE_KEYS` is overwhelmingly a list of *state-level* names (R11-07, Medium); #215's new descent gate created a new `start()` hang shape (R11-06, Medium). #213 is the one fix with a *new* correctness hole one hop out: restore-then-re-persist without `start()` drops every armed delayed self-send (R11-08, Medium).

### Is the library fully battle-tested?

**Not this round, and the gap is now three rounds deep on the same two items.** Eight battle tracks, contracts on both spellings, a 527-script regression sweep and a 15/15 round-10 unit pin all ran. But **the full suite did not finish inside the bound for the third consecutive round** (reached ~4 % of 3535 tests, zero failures observed) and **BENCH-6 (loaded timer drift) has now gone unmeasured for four rounds**. We carry round 10's completed measurement (3505 passed, 13 skipped, 0 failed, 92.78 % coverage at `19cb1f1`) as the standing coverage evidence; it is one commit stale and it is the input to decision-table row 2. That is an honest hole and it is recorded as such, not papered over.

What *was* tested was tested hard, and the round's headline finding was found by measuring the container rather than inferring from RSS.

### Is it good to proceed?

**Yes — Phase 3 continues, but the row-8 ADOPT does not carry forward unamended.** Post-refutation the round closes at **0 Blocker · 1 High · 4 Medium · 5 Low**. The single High (**R11-04**, the unbounded `_timer_handles` leak on the `raise(delay=)` path) is mechanically contained by a constraint we *already lint* — **CV-C47**, which bans `raise(delay=)` self-paced periodic work — so the gate lands on **row 6: ADOPT WITH CONSTRAINTS**, a one-row regression from round 10's row 8. That regression is real and it is not cosmetic: it is the difference between "the remaining constraints are architectural consequences of our own benchmarks" (row 8) and "one of them is containment for an open library defect" (row 6).

**Refutation moved every Blocker/High candidate DOWN and none up, for the fourth round running.** Of five candidates — one Blocker and four Highs — **three were refuted outright** (R11-01, R11-03, R11-05), **one was downgraded High → Low** (R11-02), and **one survived at High** (R11-04). The two candidates the round's framing pointed at hardest, the security ones, are the two that did not survive contact with a control probe.

### Round question 1 — did the #212 rule reversal re-open any bounded-cycle class (a collateral regression)?

**No.** This was tested directly and adversarially, and the answer is clean on three independent lines of evidence.

1. **The purpose-built collateral-unboundedness probe** (`60-r11-regression.md` §4) found **no previously-bounded shape that became unbounded**, with watchdogs on both the `def` and `async def` lanes.
2. **R11-05 — the one finding that claimed otherwise — is REFUTED.** The claim was that #212's exemption keys on delay *truthiness*, so `raise(delay=0.0001)` escapes `maxIterations` at ~20k laps/s. The mechanism reproduces exactly, but the **control kills it**: plain `after:` — exempt from `maxIterations` since long before #212 — behaves identically on the same charts at the same delays (`after:0.0001` 10,247 beats / 20,485 per s vs `raise(delay=0.0001)` 10,539 / 21,075; pure ping-pongs 8,235 vs 6,701), on both lanes. #212 therefore opened **no escape**; it made `raise(delay=)` equal to `after`, which `maxIterations` never bounded by design. Both sub-claims are true of `after:` on every prior commit, so nothing regressed. The behaviour is documented verbatim in `production-characteristics.md` §2 including the new #212 rule, agrees with SCXML §6.2 and XState v5 (delayed sends go to the scheduler, outside the microstep bound), and is not a liveness failure — an external `send("PING")` during the ~15k beats/s spin is served in 16.5 ms (`def`) / 15.3 ms (`async`), the same Windows timer floor as the quiescent chart. `delay` is milliseconds, so `0.0001` = 100 ns is API misuse, not an escape hatch.
3. **The gate and the 527-script sweep produce exactly one stable PASS→FAIL delta across 163 checks**, and it is `issues/verify-main-19cb1f1/206_delayed_selfsend_charged.py` — **our own test encoding the #206 rule #212 deliberately reverses**. That is category (b), SUPERSEDED-BY-#212, not a regression. The whole round is otherwise regression-free.

**The honest caveat, and it is the round's real finding.** #212 opened no *semantic* hole, but it made a pre-existing *resource* defect unbounded. `_timer_handles` always leaked one handle per `raise(delay=)` beat; before #212, #206's chain trip killed such a cycle at ~12 beats, capping growth at ~12 entries. #212 makes the cycle legal, so the growth is now unbounded — **+455 MB / 24 s at 200 machines, strictly linear, no plateau** (R11-04, the surviving High). The rule reversal is correct; its collateral is a leak, not a lost bound.

### Round question 2 — did snapshot v3 / the v2-upcast-as-engine-minted rule re-open the #195/#203 forgery boundary?

**No.** Both candidates were filed at Blocker/High and **both were refuted on control probes**, following exactly the R10-01 pattern this series has now hit three times.

**R11-01 (filed Blocker — the `"version": 2` downgrade mint) is REFUTED.** The mechanism reproduces exactly: `upcast()`'s `if version < 3` block applies `rec.setdefault("engine", True)` to forged `done`/`error`/`after` records, and they fire — a 60,000 ms `after` in ~1 ms, an `onDone` with attacker context, `last_error=None` throughout, the v3 controls correctly refusing. But it is **not a defect**, because `from_snapshot` is a **documented trusted-input boundary** (#205: `state_ids`/`configuration`/`context` are applied verbatim; `machine_hash` is a fingerprint, explicitly "not a MAC"). The control probe is decisive: **an attacker who can edit `version` can equally edit `state_ids` and land in the target state directly**, with no event forgery at all. The upcast confers no privilege the payload did not already have. The documented mitigation — `from_snapshot(minimum_version=3)` — raises `SnapshotVersionError` on the forged blob, confirmed in three tracks. **Residual: a Low doc nit only** — the snapshot guide still recommends `minimum_version=1` as the anti-downgrade floor and should say **3**, now that v3 is the layout carrying provenance.

**R11-03 (filed High — the four-way `after`-provenance forgery, carried from round 10) is REFUTED, severity None.** All four vectors re-run verbatim, but no trust boundary is crossed. **Control V1 — the only vector reachable from the documented public API — is correctly refused with `UnknownEventError`**, which is precisely the claim #195/#203 make. V2 needs a non-exported implementation module (probe Q1: `engine_after`/`engine_done`/`engine_error`/`_EngineAfter` are absent from the top level and from `__all__`) — in-process privileged code that could equally monkeypatch the interpreter. V3/V4 require *already holding* a genuine engine-minted event; probe Q3 on both lanes shows the original and the pickle clone behave identically, so the escalation is zero, and `events.py:249-251` documents copying as the legitimate case. V5 requires authoring arbitrary snapshot bytes; probe Q2 on both lanes shows that same writer reaches `n1.expired` with context `{"fired": 99}` using `state_ids`/`context` alone, **no event at all** — which `events.py:409-420` states verbatim. XState v5 likewise has no cryptographic event provenance and restores caller-supplied snapshots unchecked; SCXML §5.10 treats the queue as engine-internal. "Type identity is not a capability" attacks a capability claim **the library never makes**. Carried forward only as a consumer constraint: authenticate/sign persisted snapshots at the storage boundary — which is CV-C23's HMAC clause, already mandatory for us.

**R11-02 (filed High — `scheduled_sends` is a second, ungated restore door) is DOWNGRADED to Low.** The behaviour reproduces exactly: `scheduled_sends` bypasses `_admit_restored`, forged records deliver bogus events under `strict`, drive `onDone`, and fire a declared 60 s `after` in ~1 ms, on both engines and both kinds, with `invalid==[]` and `last_error==null`. But a new standalone probe (`probes/main-c78ce99/r11_02_equivalent_doors.py`) shows **forging the snapshot's `configuration` alone reaches the same target state with no event at all**, and that both the v2 `pending_events` upcast (#214) and the v3 `"engine": true` flag (#195) are *documented* doors to the same place. `events.py:421` states the boundary explicitly. A **live** `raise(delay=)` is strict-checked at arm time (`base_interpreter.py:3525`), so an undeclared event enters `scheduled_sends` only via forgery or a chart change. **What survives is real but observability-grade:** #214 promises that restored user events get the strict check *with a reported refusal*, and `scheduled_sends` does not — so a chart upgrade that undeclares an event yields silent delivery instead of `on_invalid_event`/`last_error`. That is a contract inconsistency worth filing (one-line fix: route `_rearm_restored_self_sends` through `_admit_restored`), not a security hole.

**Net on question 2: the boundary #195/#203 target holds in every probe.** Snapshot v3 and the v2 upcast operate entirely *inside* the already-documented trusted-input boundary. For the third round running, a Blocker filed against engine-event provenance has been refuted by our own control probe — a pattern now worth naming in the method: **any finding whose threat model requires blob-write must first be tested against "what does the same writer achieve with `state_ids`/`context` alone?"** If the answer is "the same thing", there is no defect.

### The one-line summary

**Round 10's fixes are genuine and land on every axis they claim; the round's two security alarms are both false; and the round's real cost is one High-severity unbounded memory leak that #212 turned from capped to uncapped — contained by a constraint we already lint, at the price of dropping from decision-table row 8 back to row 6.**

---

## 1. The 5 issues

| Issue | Claim | Verdict at `c78ce99` | Evidence |
|---|---|---|---|
| **#212** | A `raise(delay=)` self-send is a **timer**, not a chain link: arming ends the step's chain, firing is a clock event; a 1 ms self ping-pong is a legal periodic process. **Supersedes #206.** | **FIXED — clean, exact, both engines, both kinds.** Parity with `after:` is measured, not asserted. | 200 machines × 1 ms ping-pong for 10 s → **0 `RunawayChainError`, 0 `chain_budget` drops, 200/200 still beating** (`x4`); zero-delay cycles still trip, including in a chart that *also* arms a delayed send (`x4/B`); 500-config × 2-kind × 2-engine livelock fuzz **2000/2000 clean** (`x6`); beat rate indistinguishable from `after:` at every rung (`x5`); 540 fuzz cells with a two-sided oracle, 0 violations, `cpu/wall = 0.26`; real B5 refill cycle 40 beats / 21 laps with live invokes (`K2`). **Residual: none semantic.** The one collateral is **R11-04**, a resource leak the old trip used to mask. |
| **#213** | Snapshot layout **v3** with `scheduled_sends` (remaining delay + id), re-armed on `start()`. | **FIXED — round-trip exact.** | 300 random machines × 2 kinds, snapshotted at a random point inside the delay: **600/600** carried the right `remaining_ms` (±0.5 ms) and `send_id` and fired **not early, not late, exactly once** (`x1`); 200 concurrent restores identical (`x9/B`); `p1_v3_roundtrip` **300/300**; 4000.0 ms + `send_id` round-trip on a real contract (`K3`). **Residual: R11-08 (Medium)** — restore → re-persist **without** `start()` drops every armed send, because `_persist_scheduled_sends` reads only the live `_armed_self_sends` dict and `_restored_self_sends` is written by neither path. Exactly the failure #213 was filed to fix, one hop out. |
| **#214** | Restore applies `strict`; v2 `done`/`error`/`after` records upcast as engine-minted; records carry `lane`. | **FIXED for `pending_events`; scope residual on `scheduled_sends`.** | Strict-on-restore verified for `pending_events` on both engines/kinds: an unknown restored user event is refused, recorded in `last_error`, dropped (`x3/D`, `K4`); a fired timer restores ahead of the inbox (`x3/A`). **Residuals: R11-02 (Low)** — the field added in the *same release* does not get the check, so #214's stated invariant is true for one half of the restore path and false for the other; **R11-10 (Low)** — the refusal is structurally unobservable to `on_invalid_event` because `from_snapshot` takes no `plugins=` and is still constructing the interpreter; **R11-12 (Low)** — `lane` is persisted but the sync engine has no priority queue to honour it. The upcast itself is **not** a security defect (**R11-01 REFUTED**). |
| **#215** | Settle-budget reset keys on external provenance; the run loop waits for the initial descent to settle; descent raises get seed standing. | **FIXED — lap parity holds on the shapes it pins; one new hang shape.** | 100 concurrent starts of an `always` + descent-`raise` chart return in 0.01 s with identical lap counts (`x9/A`); `215_216_lap_parity_and_unknown_keys.py` re-run fresh from neutral cwd, **exit 0, ALL PASS**; `pytest -k 'LapParity or UnknownTopLevel'` **7 passed**; the `q3_sharp.py` sweep settles the CHANGELOG's own `+2`/`+3` contradiction — **`+3` only for seed standing, exactly `+2` for an externally kicked cycle**, identical cell-for-cell in the `def` lane. **Residual: R11-06 (Medium)** — an entry action that `await`s its own receipt can never satisfy the `_descent_done` gate, so `start()` hangs **forever, silently** (`last_error=None`, status `running`, configuration legal). Proven causal by a subclass that pre-opens the gate with **library source untouched**: 3.01 s to 0.00 s. |
| **#216** | Unknown top-level keys produce a WARNING with did-you-mean; `strict_config=True` / `"strictConfig": true` raises `InvalidConfigError`; `KNOWN_MACHINE_KEYS`. | **FIXED at the level it checks — flawless there; scope gap below it.** | 47/47 policy-key mutations warned, 47/47 raised under `strict_config=True`, did-you-mean named the right key **47/47** (`x7/A`); 120/120 and 200/200 top-level caught in two independent harnesses; both spellings of the switch work and either one alone raises (`p7` c); 0 unknown top-level keys across B6–B10 with a positive control raising (`OBS-216`). **Residual: R11-07 (Medium)** — `validate_top_level_keys` iterates the **root dict only**, while `KNOWN_MACHINE_KEYS` is overwhelmingly *state-level* names. `{"states": {"a": {"entryy": [...], "onn": {...}}}}` builds a clean machine with no entry actions and no transitions under **every** strict setting — **0/120 nested caught**, and with no WARNING either, so the did-you-mean net is absent exactly where typos are most likely. |

**Disposition:** 5 FIXED, 0 partial, 0 not-fixed, 0 regressed-on-one-axis. **The service-kind axis is flat across the entire corpus for the second consecutive round.** Four of the five carry a residual, and **every residual is a scope or composition gap, not a failure of the mechanism that shipped** — #214 and #216 each fixed one level and left the adjacent one, #213 fixed the hop and left the second hop, #215 fixed the parity and added a gate.

---

## 2. Regressions

Four categories, kept strictly separate because conflating them is how a superseded test becomes a permanent blocking FAIL.

### (a) TRUE regressions — **ZERO**

Across the full gate (**163 checks**, 124 PASS / 39 FAIL vs `19cb1f1`'s 117/38 — every delta being the `verifyM7` set appearing for the first time) and a **527-script sweep** (444 PASS / 83 FAIL / 0 TIMEOUT), **not one stable PASS→FAIL delta is a true regression**. For the 45 failures with no round-10 baseline entry, each was re-run against a `19cb1f1` git worktree to separate pre-existing from new; all were pre-existing. Every candidate delta was confirmed **×5 serially**.

**Methodological correction, recorded because it will recur.** The 6-worker parallel sweep produced **four false FAILs** (`107`, `154`, `158`, `167`) that pass 5/5 serially — these scripts poll wall-clock deadlines and are contention-sensitive, and round 10's baseline was produced by a *serial* driver, so a naive parallel-vs-serial diff **overstates regressions**. Standing rule for round 12: timing-sensitive scripts run serially, or their polling budgets are raised. Recorded as `R11-H-1` (harness error), together with the stale `107`/`154`/`158` probes reaching into `i._priority_queue`, whose elements have been `(event, bool)` tuples since round-8 `061d619`.

### (b) SUPERSEDED-BY-#212 — **our tests, 1 script**

| Script | At `19cb1f1` | At `c78ce99` | Action |
|---|---|---|---|
| `issues/verify-main-19cb1f1/206_delayed_selfsend_charged.py` | PASS | **FAIL ×5/5 (stable)** | **RETIRE from the gate.** It asserts the #206 rule — that a re-armed delayed self-send is charged per lap — which #212 deliberately reverses. Also covers record `A` (`attack_a_superseded_206`). |

This is **the single stable PASS→FAIL delta in the entire round**. Left in place it becomes one permanent, meaningless blocking FAIL that trains the reader to ignore red. §10 lists the scripts retired or rewritten in `gate/run_gate.py`.

Additional **assertions** (not scripts) superseded in our battle corpus and re-asserted under the new oracle rather than counted as failures: the observability track's V4 (`raise(delay=1ms)` ping-pong trips at `maxIterations`) — re-run as attack A under the #212 rule, **500 beats, zero trips**; and every prior security-track assertion of the old rule, recorded **SUPERSEDED**, not FAIL.

### (c) SUPERSEDED-BY-v3 (#213/#214) — **0 scripts, 2 standing constraints re-grounded**

No script asserted the pre-v3 layout in a way that v3 breaks, because round 10's **R10-04** (armed delayed self-raise lost on restore) was filed as an *absence*, and #213 fills it. The effect is the opposite of a regression: **CV-C49** (snapshot only with no armed self-delayed debt) loses its original ground — the debt is now persisted — and is **rewritten** in §7 rather than retired, because R11-08 gives it a *new* and narrower ground (the restore→re-persist hop).

One carried finding is **re-scoped** by v3 rather than superseded: round-10's **R10-05b** (a 0.8.0-era `after` record is refused rather than demoted) is now handled by #214's upcast — the migration cliff is gone — so **CV-C48 retires** (§7).

### (d) Library regressions — **1 resource, 1 liveness, both new at this commit**

| ID | Kind | What round 10's code did |
|---|---|---|
| **R11-04** (High) | Resource | Not a new *mechanism* — `_timer_handles` always retained one handle per `raise(delay=)` beat — but **#212 removed the trip that bounded it**. At `19cb1f1` the cycle died at ~12 beats so the round-10 soak read +1.2 MB; at `c78ce99` the cycle is legal and growth is **unbounded**: **+455 MB / 24 s at 200 machines**, strictly linear, no plateau. A genuine net-new production risk created by a correct semantic fix. |
| **R11-06** (Medium) | Liveness | **#215's `_descent_done` gate is net-new.** An `async def` entry action that awaits its own receipt deadlocks `start()` forever with no diagnostic. Proven causal against a gate-pre-opening subclass with library source untouched. |

Both are new at this commit and neither is visible to the gate — the same blind spot round 7 recorded. Neither is a *semantic* regression: no previously-correct behaviour became incorrect.

---

## 3. Scorecard per battle track (both service kinds)

| Track | Scope actually run | Result | New canonical findings |
|---|---|---|---|
| **persistence** | `x1`–`x14`, all standalone, all proved from neutral cwd, **every one on both `XS_SVC=async` and `XS_SVC=def`** | **Strongest track this round and the source of the round's headline.** #213 round-trip **600/600** exact; #212 **200/200** beating; #214 strict-on-restore and lane-restore verified; #215 100 concurrent starts in 0.01 s; #216 **47/47** with correct hints; **determinism total** — 50× traces on both engines, both kinds, including a `scheduled_sends` restore, produce **one digest, the same on both engines**, invariant across `PYTHONHASHSEED` (`x11`) | **R11-04** (High, the leak — measured on the container, not inferred), R11-07, R11-01 (→REFUTED) |
| **concurrency** | `u1`–`u8` | #212 **correct and holds under attack**: 540 fuzz cells, two-sided oracle, 0 violations, `cpu/wall = 0.26`, 0 chain trips on periodic work, zero-delay cycles still trip, `after` parity **exact**. v3 property `p1` **300 machines, 0 failures, 0 missing records** | R11-02 (→Low), R11-08, R11-10, R11-11 |
| **security** | 21 prior scripts re-run verbatim + 11 new (`n1`–`n11`), both kinds | Every prior item holds. The two headline attacks **both refuted on controls** (§0 Q2). A forged `engine:true` record with a **mismatched** `after`-id does **not** fire — #203's per-record matching is sound | R11-01 (→REFUTED), R11-03 (→REFUTED), R11-09, R11-12 |
| **fuzz** | Full re-run + new #212–#216 attack set | 30/30 nested config mutations silently accepted (R11-07); the dangerous `last_error`-erasure variant found here — 40/40 trips, machine permanently inert at n=24 polled to convergence, yet **6/40 (`def`) and 8/40 (`async`)** post-mortems read `status='running'`, `last_error=None` | R11-07, R11-09, R11-11, R11-03 |
| **semantics** | `p/c/f/s/k` suites + repro + machine-readable results, both lanes | All round-10 semantics defects verified fixed; #212 reversal confirmed on a real chart; the `+2`/`+3` plateau question **settled** by a sweep over limits {3,5,7,9} | R11-04 (corroborating), R11-05 (→REFUTED), R11-06, R11-DC-1 |
| **soak** | **REDUCED** — 30-machine / 20 s heartbeat+chaos-restore instead of the specified 12-min / 200-machine | Clean at the reduced scale; corroborates R11-04's linearity | R11-01 (dup) |
| **determinism** | Full inherited suite `d1`–`d10b`, `e1`, `f1` re-run both kinds + 2 new round-10-targeted attacks (`i1` #212, `i2` the v2-upcast question) | **All inherited FIXED items remain FIXED. No regression in any inherited script** | R11-01 (dup, from the benign direction) |
| **observability** | **REDUCED** — A, B, C/D, E, F; G as a confirmatory probe | #212 live and the #206 charge gone (500 beats, 0 trips). **V1/V2, V5, V6, V7 not independently re-verified this round** — presumed unchanged, recorded as untested | `OBS-BUILTIN-SHADOW` → R11-W-2 |

**Coverage honesty.** Three tracks ran **reduced** (soak, observability, and determinism's concurrency/fuzz/soak halves) against the 20-minute whole-task bound; each says so in its own header. The full spec exceeds the bound by roughly an order of magnitude. **Both service kinds were exercised in every track that invokes a service or action**, which is the axis that has historically produced findings.

**Cross-track consistency, and a caution.** R11-01 was found independently by **six** tracks and R11-07 by **eight**; dedupe collapsed 34 records. That breadth is why both were triaged high on first pass, and it is worth recording that **breadth of independent discovery predicted neither severity nor validity**: the eight-track finding (R11-07) survived at Medium, and the six-track finding (R11-01) was refuted outright.

---

## 4. Contract machines — both kinds, plus `strictConfig`

Twenty catalogue machines (B1–B20), JSON byte-identical (md5-verified) to the `19cb1f1`, `f28719c` and `3ed3099` sets, driven end-to-end under the **mandated config** — `actionErrorPolicy: rollback`, `onUnhandled: defer` (order path) / `error` (control plane), `guardErrorPolicy: raise`, `strictTargets`, `strict`, **`strict_config=True`**, bounded `RAISE` inbox (`max_queue_size=64`), `SimulatedClock`, and a `CvErrorHooks`-shaped plugin stub carrying `on_invocation_stranded` and `on_invalid_event`.

### Kind 1 — library behaviour under our contracts

| Group | Result | Notes |
|---|---|---|
| **B1–B5** (Order, TradeGroup, Leg, OCO, Iceberg) | **356 checks, 0 FAIL** — 178 per service-spelling lane, every driver run twice (all `async def`, then all plain `def`), async engine primary with sync-engine parity on configuration, action trace **and** service-call trace | #212 confirmed on a **real** B5 refill cycle with live invokes (40 beats / 21 laps, `K2`); #213 `scheduled_sends` 4000.0 ms + `send_id` round-trip (`K3`); #214 strict-on-restore (`K4`); #216 clean on B1–B5 (`K1`) |
| **B6–B10** (algos) | Clean both lanes; `def` lane **52/52** (it was 51/52 before #204) | 0 unknown top-level keys, positive control raises (`OBS-216`) |
| **B11–B15** (RecordingSession, ReplaySession, ExchangeConnection, IngestionPipeline, PaperMatcher) | Clean under the newly-mandatory `strictConfig: true`, plus the four standing drives and both semantic reversals | `spawnBlockingTimeout` reads back as `spawn_blocking_timeout_ms == 5000.0` |
| **B16–B20** (control plane) | **Zero new library findings** (`CV78-L0`); #207 plateau `maxIterations+2` on B18/B19 with `on_invocation_stranded`, `has_dormant_invocations` and `pending_invocations()` all answering | The B18 kill-switch storm still plateaus correctly |

**Library verdict on contracts: 20/20 LIBRARY-GO, zero library defects across all four groups, on both spellings — for the second consecutive round.** Everything that blocks a contract machine is now **ours**.

### Kind 2 — our own contract defects (carried, re-verified fresh at `c78ce99` on both action kinds)

| ID | Sev | Status | Fix |
|---|---|---|---|
| **C-04** | **Blocker** | **STILL PRESENT — open six rounds.** `B16.elevation.elevated` omits `LOGOUT` / `IDLE_DEADLINE` / `ABSOLUTE_DEADLINE`. Re-run: `["session.auth.revoked","session.elevation.elevated"]`, `still_elevated: true` for **all three** kill events. A dead session stays elevated and can be **re-elevated**. Refuted as a library defect in round 10 — `REVOKE`, listed in both regions, clears correctly, so engine dispatch is sound. Merges C-04b (re-elevation unaudited) and C-04c (post-revoke `STEP_UP_OK`) as the same missing-handler root | Hoist the four revocation events onto the root. **Config-only.** |
| **C-07b** | **Blocker** | **STILL PRESENT — open six rounds.** Re-run, both kinds: a denied `RELEASE` yields `status='error'` + `UnhandledEventError`; the subsequently **authorised** `RELEASE` returns `ok=True` but `final=['kill_switch.engaged']` — `bricked: true`. This is documented opt-in policy (`onUnhandled: 'error'` + #170: a guard-denied event *is* unhandled), refuted as a library defect in round 10. **The round-6 Amendment-6 removal still has not landed in the JSON** (`ka_killswitch`, sha1 `3d0de943effd`) | An ordered **unguarded `RELEASE` fall-through** arm that audits the denial as a no-op. **Config-only.** |
| CD-B8 | High | `B8.sl.attaching` retries with no chart-level bound; parks with a live position, **no stop-loss**, `raise_critical_alert=0`, `stranded=[['position_protection.sl.attaching','att']]`. B6 and B10 bound their equivalents; B8 does not | Cap `attach_attempts`. Config-only. |
| K10 | High | Idempotency: the mandated R6-03 rollback+onDone storm places `place_order` **128× (async) / 91× (def)** on B1 and `submit_child` **208× / 126×** on B5 before the chain cut. **Library-correct** (rollback ⇒ re-enter ⇒ re-invoke; #207 makes the strand observable) | **An idempotency key on every order-placing service is mandatory** — client order id keyed on **chart state**, never on lap. |
| C-06 | High | `B19.stale_lockout` handles `RECONNECTED` only; `OPERATOR_RESOLVED` is deferred, so on a venue that never reconnects cleanly the only exit is a process restart | Add the operator arm. |
| CD-01 | High | Carried from `battle-f28719c` unchanged; nothing at `c78ce99` affects it | — |
| **K11** | Medium | **No timers are declared in any chart**: all 20 machines have zero `after` transitions and zero `raise(delay=)` actions (`after=[] delayed_sends=[]`; every driver snapshot reads `v=3:sched=0`). #213 exists precisely to make deadlines restart-safe and **we cannot use it until the deadlines move into the charts** | See the tension below — this is now the most consequential item on the list. |

**C-04 and C-07b have been open for six rounds, both refuted as library defects, both fixable in config alone, and both still not landed.** For two consecutive rounds the binding constraint on our order path has been our own catalogue. That is now the single largest self-inflicted item on this board and it is tracked in E50.

### `strictConfig` findings against our JSON

`strict_config=True` (and the equivalent `"strictConfig": true` in the JSON — either spelling alone raises) was applied to **all 20 catalogue machines** this round for the first time as a mandatory setting. **Result: zero unknown top-level keys across the entire catalogue**, with a positive control confirming the check is live rather than vacuous.

But the check's value for us is **much smaller than it looks**, per R11-07: it covers the **root dict only**. Our catalogue's realistic typo surface is the ~200 state nodes, not the ~10 root keys, and a misspelled `entry`/`on`/`after`/`invoke`/`onDone` inside a state is accepted **silently, with no WARNING and no raise, under every strict setting**. So `strictConfig: true` becomes mandatory (it is free and it closes the root) **and** the wrapper must run its own recursive check (**CV-C57**). Note the one exception the fuzz track correctly identified: nested *policy* misspellings (e.g. `actionErrorPolicyy` under a state) are inert either way, because policies are read from the root only — the **structural** keys are the real exposure.

### Constraint status: C-04 / C-07b

| | Status |
|---|---|
| **C-04** | **OPEN, Blocker, ours, six rounds.** Blocks B16 from the order path. Not a library defect. |
| **C-07b** | **OPEN, Blocker, ours, six rounds.** Blocks B18 from the order path. Not a library defect. The Amendment-6 change is specified, agreed and unlanded. |

Neither affects the **library** gate decision — the gate's Blocker row (row 4) reads *filed library Blockers*. Both are absolute blockers on **our** B16/B18 order-path shipping, and §10 gates Phase 3's canary on them.

---

## 5. Surviving defects by final severity

Post-refutation: **0 Blocker · 1 High · 4 Medium · 5 Low** (12 canonical library defects filed; 3 refuted outright, 1 downgraded to Low).

### High (1)

| ID | Title | Why it survived refutation | Containment |
|---|---|---|---|
| **R11-04** | **Unbounded `_timer_handles` growth — one retained handle per `raise(delay=)` beat, both engines** | **Every refutation avenue failed.** (a) *API misuse?* No — six postures × both engines × both action flavours all retain **1.00 handle/beat**: id reuse, no send id, 250 ms period, a never-exiting self-loop, and **explicit `cancel(sendId)` before each re-arm**; the `after:` control is **0.00**. `_cancel` clears the clock and `_armed_self_sends` but never the `_timer_handles` entry. (b) *Documented?* No — #212/#213, `json-config.md`, `production-characteristics.md` and `snapshots.md` all **bless** a self-paced heartbeat "of any period" and none mentions retention. (c) *Upstream agreement?* No — XState v5 deletes the scheduled entry on fire; SCXML has no retained-record semantics. (d) *Duplicate?* No — round 10 was flat only because #206's trip capped the cycle at ~12 beats. (e) *Artefact?* No — measured on the container (`len(i._timer_handles[i.id])`), polled to convergence at 3/6/9/12 s and 6/12/18/24 s, strictly linear, no plateau, RSS a corroborating second signal. (f) *Trust boundary?* Not applicable — the growth comes from the machine's own blessed heartbeat. **Cause confirmed by reading:** `interpreter.py:2354` / `sync_interpreter.py:1198` key the handle under `self.id`, while the only pruner (`:2557` / `:1488`) pops `_timer_handles[state.id]` on state exit — and the machine id never exits. The `after` path uses `owner_id=state.id` and **is** pruned. | **CV-C47** (already linted: no `raise(delay=)` self-paced periodic work) + **CV-C61** (new: bounded interpreter lifetime and a handle-count gauge on any machine that uses `raise(delay=)` at all). **One-line owner fix per engine.** |

**Why High and not Critical:** unbounded, sustained (no ceiling short of `stop()`), triggered by usage the library now *explicitly endorses*, reachable in every long-lived process, and it collides with R11-DC-2/K11. But there is no corruption, no wrong semantics, memory is reclaimed at `stop()`, and `after:` remains a leak-free workaround.

### Medium (4)

| ID | Title | One-line risk | Containment |
|---|---|---|---|
| **R11-06** | #215's `_descent_done` gate: an entry action awaiting its own receipt hangs `start()` **forever, silently** | `last_error is None`, status `running`, configuration legal — indistinguishable from a slow entry action; #207's `on_invocation_stranded` does not cover it (no invoke involved) | **CV-C51** (new: no entry/exit action may await a receipt on its own interpreter — lintable) + **CV-C39** widened to **CV-C56** (every `start()` wrapped in `asyncio.wait_for`) |
| **R11-07** | #216 validates the root config only; a misspelled key **inside a state** is silently dropped even under `strict_config=True` | `{"entryy": [...], "onn": {...}}` builds a clean machine with no entry actions and no transitions, with **no WARNING either** | **CV-C57** (new: recursive key check over every state node at build time) |
| **R11-08** | Restore then re-persist **without** `start()` silently drops every armed delayed self-send | A journal-compaction or snapshot-migration job that loads and re-writes without starting destroys every deadline — the exact failure #213 was filed to fix, one hop later | **CV-C58** (new: never re-persist an un-`start()`ed interpreter; any snapshot-rewriting utility must `start()` or copy `scheduled_sends` verbatim) |
| **R11-09** | A `RunawayChainError` trip reaches only `last_error`, which **the next event erases**; no hook names it | A permanently inert machine reports healthy on **6/40 (`def`) / 8/40 (`async`)** post-mortems. Post-#212 a legal heartbeat guarantees ticks keep arriving, so **in an OMS the race is won by the eraser** | **CV-C59** (new: never poll `last_error` for chain health; latch `RunawayChainError` from the log or a latching plugin wrapper) |

Classified Medium rather than High because each is either bounded to an unusual shape (R11-06), detectable by our own build-time check (R11-07), avoidable by an operational rule (R11-08), or observable via a log-scraping supervisor (R11-09). R11-09 is **High in effect and Medium in classification**; it produced **99 false violations** in the security track's own fuzz harness before the read was latched, which is evidence the observable is genuinely unusable as written.

### Low (5)

| ID | Title |
|---|---|
| **R11-01** (was Blocker) | The v2-downgrade upcast mints `engine: true` on forged records. **REFUTED as a defect** — `from_snapshot` is a documented trusted-input boundary and the same writer reaches the target state via `state_ids` alone. **Residual is a doc nit:** the snapshot guide still recommends `minimum_version=1` as the anti-downgrade floor and should say **3**. |
| **R11-02** (was High) | `scheduled_sends` bypasses `_admit_restored`. **DOWNGRADED** — no trust boundary crossed (equivalent doors probe). **Residual is a real contract inconsistency:** #214 promises restored user events get a *reported* strict refusal and this field does not, so a chart upgrade that undeclares an event yields silent delivery. One-line fix. |
| **R11-10** | `on_invalid_event` is **structurally unreachable** on the restore path — `from_snapshot` takes no `plugins=` and is still constructing the interpreter, so no ordering exists in which a plugin observes a restore refusal. Contradicts #214's CHANGELOG claim. The library's own pin (`test_round10_findings.py:305-313`) registers the plugin *after* the restore and asserts only on `last_error`, never on `plug.seen`. |
| **R11-11** | `structure_hash` omits `raise(delay=)` delays although it covers `after` delays — changing `delay: 60000` to `delay: 100` leaves the hash byte-identical, so a v3 snapshot carrying a 60,000 ms armed send restores against a chart that now means 100 ms with the drift check silent. |
| **R11-12** | The priority `lane` is persisted but **not honourable on the sync engine** (no priority queue by construction), so cross-engine restore is not order-equivalent. Pairs with R11-02(c): `lane` is both unenforceable on sync and forgeable on async — **the wrapper must not depend on restored ordering at all.** |

### Refuted outright (2) — recorded to prevent re-litigation

**R11-03** (severity **None**): the `after`-provenance boundary is *not* forgeable from outside the trust boundary. Control V1 — the only vector reachable from the documented public API — is correctly refused with `UnknownEventError`. V2 needs non-exported modules; V3/V4 need an already-held genuine engine event (probe Q3: original and pickle clone behave identically, zero escalation); V5 needs blob-write, which reaches the target state with **no event at all** (probe Q2). "Type identity is not a capability" attacks a capability claim the library never makes. **Carried forward only as the consumer constraint we already hold: sign persisted snapshots at the storage boundary (CV-C23).**

**R11-05** (severity **none**): #212's timer exemption does not void `maxIterations`. Plain `after:` at the same sub-millisecond delays behaves identically on the same charts, on both lanes — so #212 opened no escape, it achieved parity with a path `maxIterations` never bounded by design. Documented, SCXML- and XState-conformant, and **not a liveness failure** (external `send` served in 16.5/15.3 ms during the spin — the Windows timer floor).

### Non-defect classifications carried

- **R11-DC-1** (design constraint): descent-seeded chains get `limit+3` laps, external-seeded exactly `limit+2` — intended #215/#77 parity, measured deterministic across limits {3,5,7,9}. **Budget sizing against the external number under-provisions the descent case by ~2.7×** (**CV-C62**). The `#210` CHANGELOG sentence conflating them is a genuine (trivial) doc defect.
- **R11-DC-2** (design constraint): `after` deadlines are **not** persisted while `raise(delay=)` **is** — both documented, both intentional, visually interchangeable in a chart. **This is the constraint that collides with R11-04.**
- **R11-W-1/2/3** (needs-wrapper): stable `send_id` on every catalogue deadline; **never register a user action whose name collides with a built-in** (`raise`, `send`, …) — a collision silently disarms the built-in with `beats=0`, `last_error=None`, no warning; `SimulatedClock` does **not** fire restored `scheduled_sends` (nor `after`), so deadline properties must be verified against the real clock on this build.

### The unresolvable tension — record it plainly

**R11-04 says *do not use `raise(delay=)` for periodic work*. R11-DC-2 + K11 say *deadlines must be `raise(delay=)`*, because `after` is not persisted and our charts currently carry no timers at all.** The wrapper cannot satisfy both. Until R11-04 is fixed upstream the only coherent posture is the three-way split in **CV-C61**: restart-critical deadlines on `raise(delay=)` with a stable `send_id`, bounded interpreter lifetime and a handle gauge; everything periodic and non-persistent on `after:`; and **no high-frequency `raise(delay=)` heartbeat under any circumstances**. This is the item that should be pushed hardest upstream, because a one-line fix on each engine dissolves it entirely.

---

## 6. GATE DECISION (per `20-adoption-gate.md` §7)

Rows applied **in order; the first match wins.**

| # | Condition | This round |
|---|---|---|
| 1 | Any `ERROR` row in the gate output | **No.** `gate/run_gate.py --timeout 120` exited **0**; 163 checks, 124 PASS / 39 FAIL, every FAIL a known baseline entry or the one superseded script. The four parallel-sweep false FAILs were re-run serially and are harness artefacts, **excluded from the decision and recorded as `R11-H-1`**. No ERROR rows. Row does not fire. |
| 2 | Library's own suite fails, or coverage drops below 86 % | **Does not fire — but on carried, one-commit-stale evidence, and this must be said plainly.** The full suite did **not** complete inside the bound for the third consecutive round (~4 % of 3535 tests reached, **zero failures observed**). The standing measurement is round 10's completed run at `19cb1f1`: **3505 passed, 13 skipped, 0 failed, 566.57 s, coverage 92.78 %** — above the library's own 90 % floor and our 86 % bar. Supporting evidence at *this* commit: `tests/test_round10_findings.py` **15/15**; round8+9+10 combined **65/65 under both `PYTHONHASHSEED=1` and `=2`**; no test failure observed anywhere in the round. **Judgement: row 2 is not triggered, but it is now resting on inference again** — exactly the risk round 9 carried and round 10 discharged. §9 makes a completed suite run the first item of round 12. |
| 3 | Snapshot format changed while LC-21 (no schema version) is open | **No.** LC-21 is closed. The format **did** change — v2 → **v3** — which is why this row must be checked rather than assumed: `version` and `machine_hash` are present, `check_version` / `minimum_version` / `expected_machine_hash` exist (#205), and #214 upcasts v2 rather than refusing it, so there is **no silent restore-compatibility break**. Round 10's R10-05b migration cliff is *closed* by the upcast. Row does not fire. |
| 4 | Any filed **Blocker** repro still exits 1 (LC-01, LC-02, LC-03, LC-16) | **No.** All four remain closed; no library Blocker survives refutation this round (R11-01 REFUTED). The two open Blockers on this board — **C-04** and **C-07b** — are **ours**, defects in our catalogue JSON, refuted as library defects in round 10. This row reads *filed library Blockers*, so it does not fire; C-04/C-07b are gated in §10 instead. |
| 5 | All Blockers closed; **> 5 High** open | **No.** Exactly **1** High open (R11-04). |
| **6** | **All Blockers closed; 1–5 High open, each with a mechanically enforced mitigation and a passing test in `tests/xstate_contract/`; all Medium triaged** | **YES — this row fires.** One High (**R11-04**), mechanically enforced by **CV-C47** (already linted: ban `{"type":"raise","params":{"delay":…}}` targeting the machine's own events) widened by **CV-C61** (bounded interpreter lifetime + `_timer_handles` gauge), with `test_cv_c47_no_self_delayed_raise` in place and `test_cv_c61_timer_handle_gauge` to be added. All four Medium triaged, each with a named constraint and a named test. |
| 7 | 1–5 High open **without** enforced mitigations | Not reached. Worth stating for the record: **if CV-C47's lint were not already in place and green, this round would be row 7 — DEFER.** The lint predates the finding by one round, which is the entire difference between adopting and deferring. |
| 8 | All Blocker **and High** closed; all Medium triaged; BENCH-1/2/6 not all met | Not reached — **R11-04 keeps the High row non-empty.** This is the one-row regression from round 10. |
| 9 | All closed; all benchmark thresholds met | Not reached. |

### DECISION

```
Gate run 2026-09-22 - xstate-statemachine main @ c78ce99 (unreleased 0.8.1, __version__ reports 0.8.0)
DECISION: ADOPT WITH CONSTRAINTS -- decision-table ROW 6
          (REGRESSED one row from round 10's ROW 8 at 19cb1f1)
  gate     : exit 0; 163 checks, 124 PASS / 39 FAIL (all FAILs known-baseline or superseded)
  sweep    : 527 scripts, 444 PASS / 83 FAIL / 0 TIMEOUT; every delta re-confirmed SERIALLY
  regress  : ZERO true regressions. 1 stable PASS->FAIL delta = OUR test encoding the
             #206 rule that #212 deliberately reverses (retire it)
  issues   : 5/5 FIXED (#212 #213 #214 #215 #216) -- both engines, both service spellings
  suite    : NOT COMPLETED within bound (3rd consecutive round; ~4% reached, 0 failures).
             Carried: 3505 passed / 13 skipped / 0 failed / 92.78% coverage at 19cb1f1
  benches  : 5/7 thresholds met - BENCH-2 missed (~5x), BENCH-6 UNMEASURED FOR FOUR ROUNDS
  blockers open: none (library). C-04, C-07b are OURS, open six rounds
  high open    : R11-04 (_timer_handles unbounded leak on the raise(delay=) path)
                 -> enforced by CV-C47 (already linted) + CV-C61 (new)
  medium open  : R11-06, R11-07, R11-08, R11-09 (all triaged, all constrained)
  low open     : R11-01, R11-02, R11-10, R11-11, R11-12
  refuted      : R11-03 (High->None), R11-05 (High->none), R11-01 (Blocker->Low doc nit),
                 R11-02 (High->Low)
  constraints  : CV-C01..CV-C62 as recomputed in 64-r11-final-readiness-verdict.md §7
                 (CV-C48 RETIRES; CV-C49 REWRITTEN; CV-C47 WIDENED and now LOAD-BEARING;
                  CV-C51..CV-C62 NEW)
  decided by   : round-11 readiness review
```

### Why the row-8 → row-6 regression matters, and why it is not a reason to stop

Row 8 means *"the only remaining constraints are architectural consequences of our own benchmarks"* — constraints we would carry even against a perfect library. Row 6 means *"one of the constraints is containment for an open library defect."* Round 9's verdict named row 8 as the honest ceiling for this library in our system, and round 10 reached it. **We have come off it, by one row, because of one leak.**

Three things keep this from being a stop signal:

1. **The regression is one defect with a one-line fix on each engine**, already understood at the source level (`interpreter.py:2354` / `sync_interpreter.py:1198` key under `self.id`; the pruner at `:2557` / `:1488` pops `_timer_handles[state.id]`), with a working leak-free control (`after:`) in the same codebase.
2. **Its containment already existed and was already green.** CV-C47 was written in round 10 against a *different* finding (R10-03) and happens to ban exactly the shape that leaks. We did not have to invent a mitigation under pressure.
3. **The direction of travel is unchanged.** Five fixes landed clean on every axis for the second consecutive round; the service-kind axis stayed flat; the security boundary held against both of the round's attacks. Trajectory across the series: **4 Blocker · 8 High (round 5) → 0 · 2 (round 9) → 0 · 0 (round 10) → 0 · 1 (round 11).**

**The honest sentence: this release is better than the one before it and our position is one row worse, because the release made a legal usage that leaks.**

---

## 7. Constraints — retire / stand / new

### Does CV-C12 (`after` banned) or any `raise(delay=)` rule change under #212?

This is the round's sharpest constraint question and the answer is **counter-intuitive but firm**.

**CV-C12 — `after` remains banned in catalogue machines — STANDS, UNCHANGED.** #212 did not touch `after`'s drift characteristics; it made `raise(delay=)` *equal* to `after`. CV-C12's ground is **BENCH-6**, which is not merely still missed (174.4 ms against a ≤100 ms bar at last measurement) but **has now gone unmeasured for four consecutive rounds**. A constraint whose ground has not been re-measured cannot be retired — retiring it would be a decision made on absence of evidence. All algo timing stays on the external `MonotonicScheduler` with absolute `*_us` deadlines in context. `after` remains permitted **only** for coarse, non-critical timeouts where seconds of lateness is tolerable.

**CV-C47 — no `raise(delay=)` self-paced periodic work — STANDS, WIDENED, and becomes LOAD-BEARING.** Its original ground (R10-03: the heartbeat dies at `maxIterations`) is **gone** — #212 closes it, and this is precisely a case where keeping the old justification would let the constraint rot. But the constraint itself is **more** necessary now, on entirely new ground: **R11-04**, the unbounded handle leak. Round 10's verdict §9 item 4 said CV-C47 "becomes load-bearing rather than precautionary" if the spelling proves fatal on a shape we use. It has, for a different reason than anticipated. The lint text is unchanged; the ground, the severity and the status all change.

**The net effect of #212 on our rules is therefore zero relaxation and one tightening.** The reversal that made `raise(delay=)` legal is the same reversal that made it leak.

### Retired (2)

| Constraint | Why it retires |
|---|---|
| **CV-C48** (0.8.0-era snapshots migrated before restore; a `pending_events` record with `kind:"after"` and no `engine` flag rejected at the envelope and the deadline re-armed from context) | **RETIRES.** Its entire ground was R10-05b — a persisted 0.8.0 `after` record was *refused* rather than demoted, dropping the deadline silently. **#214's v2 upcast closes exactly this**: the record is upcast as engine-minted and fires. The migration cliff is gone. The *security* objection to that upcast (R11-01) was refuted, so there is no reason to re-erect the fence. **The HMAC clause of CV-C23 subsumes what remains** — we verify the envelope's tag, so a v2 blob we did not write never reaches `upcast` in the first place. |
| **CV-C45's restore clause as written** (strip every `Done`/`Error`/`After` record from `pending_events` before `from_snapshot`, matching the serialised `kind`, and re-arm deadlines from context) | **RETIRES in its stripping form, SURVIVES as CV-C45″.** Stripping was a workaround for records being *refused* silently; with #214 they are admitted correctly and refusals are strict-checked and recorded in `last_error`. Replaced by the narrower **CV-C45″**: read `last_error` / `last_transition_ok` **immediately after `from_snapshot` and before `start()`**, and reconcile admitted-record count against persisted-record count (see CV-C60). Ground: R11-10 — the refusal is real but structurally unobservable to `on_invalid_event`. |

### Standing (unchanged or re-grounded)

**CV-C01…CV-C22** as amended, **including CV-C12 unchanged** (above) · **CV-C23** (quiescence-only snapshots via the factory wrapper; envelope always carries `version ≥ 1` + `machine_hash` + **HMAC tag**) — **re-grounded and now doing more work than ever**: R11-01's and R11-03's refutations both turn on `from_snapshot` being a trusted-input boundary, and `machine_hash` being explicitly "not a MAC". **The HMAC tag is the boundary.** It also now carries R11-11: `structure_hash` omits `raise(delay=)` delays, so the library's own fingerprint will not catch a delay edit and **our** tag must cover the chart bytes · **CV-C25** (no external `send()` from inside an action; gateway queue only) · **CV-C27′** (two-sided `configuration`/`state_ids` agreement on restore) · **CV-C28** (no `LoggingInspector` in production) · **CV-C32** (async engine ⇒ every service `async def`; ground remains R10-D2) · **CV-C33** (`send_threadsafe` only via our gateway) · **CV-C34** (no `"*"` scaffolding) · **CV-C35** (no `always` into an invoked child, no `always` to an ancestor of its own source) · **CV-C36** (every `send_threadsafe` future read; the gateway counts call-site `QueueOverflowError` refusals **itself** — 99.3 % of shed never reaches `on_event_dropped`) · **CV-C39** (`await start()` always bounded — **now subsumed and strengthened by CV-C56**) · **CV-C40** (no snapshot before the post-start settle observation) · **CV-C41** (root-only snapshots) · **CV-C42** (no `priority=True` anywhere, any origin) — **re-grounded on R11-02(c) and R11-12**: `lane` is forgeable on async and unenforceable on sync, so restored ordering is not a property at all · **CV-C44** (entry actions on invoke-bearing states are `async def`, yielding at least once) — **re-grounded on R11-06**, which is the sharper version of the same hazard · **CV-C50** (`CvErrorHooks` implements `on_invocation_stranded`, samples `on_event_dropped(..., "chain_budget")`, never polls `last_error`) — **strongly re-grounded on R11-09**, which shows one benign event erases the trip · **wrapper top-level config-key whitelist** — **stands and is now doubly required**: #216 covers the root, our whitelist covers what #216's *scope* misses via CV-C57.

**CV-C49 — REWRITTEN, not retired.** Original text: *snapshot only at quiescence with no armed self-delayed debt; any state whose only exit is a delayed self-`raise` is forbidden on the persisted path.* Its ground (R10-04, the debt discharged silently on restore) is **closed by #213** — the debt is now persisted exactly, 600/600. **New text (CV-C49′):** *snapshot only at quiescence (CV-C23 unchanged), and **never re-persist an interpreter that has not been `start()`ed*** — because the restored debt lives in `_restored_self_sends` until `start()` consumes it, and `_persist_scheduled_sends` reads only `_armed_self_sends`. Ground: **R11-08**. This is the same constraint name guarding the opposite hop.

### New (12)

| ID | Constraint | Ground | Enforcement |
|---|---|---|---|
| **CV-C51** | **No entry or exit action may `await` a receipt (`send(..., wait=True)`) on its own interpreter**, directly or through a helper. | R11-06 | Lint over action bodies + `test_cv_c51_no_self_receipt_in_entry`. |
| **CV-C52** | **Every restore call site passes `minimum_version=3`.** Lint for a bare `from_snapshot(`. (Retained even though R11-01 was refuted: it is free, it is the library's own documented mitigation, and it fences the v2 path we no longer need.) | R11-01 (residual) | Lint; `test_cv_c52_minimum_version_pinned`. |
| **CV-C53** | **The snapshot journal is an integrity-protected artefact** — MAC'd at rest by the wrapper. Neither `minimum_version=3` nor `strict` is sufficient alone; this is the boundary both R11-01's and R11-03's refutations rest on. | R11-01, R11-02, R11-03 | Subsumes/strengthens CV-C23's HMAC clause; `test_cv_c53_tampered_blob_refused`. |
| **CV-C54** | **The restore routine reconciles counts**: persisted `pending_events` + `scheduled_sends` vs admitted records, and fails loudly on a mismatch. | R11-02, R11-10 | `test_cv_c54_restore_count_reconciliation`. |
| **CV-C55** | **No `delay` below 10 ms anywhere in the catalogue**, in `raise(delay=)` or `after`. `delay` is milliseconds; sub-millisecond values are API misuse and land under the ~15.6 ms Windows clock floor regardless. | R11-05 (refuted, but the misuse is real) | Static check over catalogue JSON; `test_cv_c55_no_submillisecond_delays`. |
| **CV-C56** | **Every `start()` is wrapped in `asyncio.wait_for(..., CV_START_TIMEOUT)`** and a timeout is a hard startup failure, never a retry. Supersedes and strengthens CV-C39. | R11-06 | `test_cv_c56_start_is_bounded`. |
| **CV-C57** | **The wrapper runs its own recursive key check over every state node** against `KNOWN_MACHINE_KEYS` at build time. `strict_config=True` covers the root only. | R11-07 | Build-time validator; `test_cv_c57_nested_typo_rejected`. |
| **CV-C58** | **Never re-persist an interpreter that has not been `start()`ed.** Any snapshot-rewriting or journal-compaction utility must `start()` first, or copy `scheduled_sends` through verbatim. | R11-08 | `test_cv_c58_repersist_preserves_scheduled_sends`; code review rule on the compaction job. |
| **CV-C59** | **Supervisors must not poll `last_error` for chain health.** Latch `RunawayChainError` from the log or from a latching plugin wrapper; a poll slower than the event rate cannot observe discarded work. | R11-09 | `test_cv_c59_chain_trip_latched` — must pass on **both** kinds. |
| **CV-C60** | **Read `last_error` / `last_transition_ok` immediately after `from_snapshot` and before `start()`.** Do not register `on_invalid_event` expecting restore coverage — it is structurally unreachable there. | R11-10 | `test_cv_c60_restore_refusal_read_before_start`. |
| **CV-C61** | **`raise(delay=)` is permitted only for restart-critical deadlines**, each with a stable `send_id` (R11-W-1), on machines with a **bounded interpreter lifetime**, and with `len(i._timer_handles.get(i.id, []))` exported as a gauge and alerted. **No high-frequency `raise(delay=)` heartbeat under any circumstances.** Widens CV-C47 from a ban into a ban-plus-narrow-exception. | **R11-04** (the open High), R11-DC-2, K11 | Lint (CV-C47's existing rule, extended with the allow-list); `test_cv_c61_timer_handle_gauge`; soak assertion on handle count. |
| **CV-C62** | **Budget sizing accounts for both plateaus**: a descent-seeded chain gets `maxIterations+3` laps, an externally kicked one exactly `+2`. Any runbook asserting `+3` for an external cycle is reliably wrong by one; sizing against the external number under-provisions the descent case by ~2.7×. | R11-DC-1 | `test_cv_c62_both_plateaus_pinned`. |

Plus the three **needs-wrapper** rules promoted to catalogue lint: **R11-W-1** (stable `send_id` on every chart deadline), **R11-W-2** (**never register a user action whose name collides with a built-in** — filter registrations through `xstate_statemachine.actions.is_builtin`; a collision silently disarms the built-in with `beats=0`, `last_error=None`, no warning, no error), **R11-W-3** (`SimulatedClock` fires neither `after` nor restored `scheduled_sends` on this build — deadline properties must be verified against the real clock).

---

### FINAL mandatory config block

```jsonc
// Every CandleViewer machine definition. ROUND 11, main @ c78ce99 (unreleased 0.8.1;
// __version__ still reports 0.8.0 - PIN ON THE COMMIT).
{
  "strictConfig": true,              // #216, NEWLY MANDATORY IN THE JSON ITSELF. Either this
                                     // key or the strict_config=True kwarg raises
                                     // InvalidConfigError on an unknown key; either one ALONE
                                     // is sufficient (verified). We set BOTH.
                                     // SCOPE WARNING (R11-07): this checks the ROOT DICT ONLY.
                                     // KNOWN_MACHINE_KEYS is mostly STATE-level names, and a
                                     // misspelled entry/on/after/invoke/onDone INSIDE a state
                                     // is accepted with NO raise AND NO WARNING under every
                                     // strict setting - 0/120 nested typos caught.
                                     // -> CV-C57: the wrapper runs its own RECURSIVE key check
                                     // over every state node at build time. Non-negotiable:
                                     // our typo surface is ~200 state nodes, not ~10 root keys.

  "actionErrorPolicy": "rollback",   // R10-D1 unchanged: rollback + invoke.onDone RE-ARMS the
                                     // service and each lap is a real exchange order. Services
                                     // MUST be idempotent under re-entry - client order id
                                     // keyed on CHART STATE, never on lap. K10 re-measured at
                                     // c78ce99: 128x (async) / 91x (def) place_order on B1;
                                     // 208x / 126x submit_child on B5 before the chain cut.
  "guardErrorPolicy": "deny",        // A guard-denied event IS an unhandled event (#170).
                                     // Any state whose only arm is guarded needs an ORDERED
                                     // UNGUARDED FALLBACK. This is C-07b - OURS, Blocker,
                                     // open SIX rounds, fixable in config alone.

  "onUnhandled": "defer",            // order path. No "*" scaffolding (CV-C34).
                                     // Kill/cancel events declared on an ANCESTOR of every
                                     // invoking state, never only on siblings (CV-C4x):
                                     // sibling-only 1.458s, ancestor 0.001s, invoking-state
                                     // 0.000s. priority=True does NOT help - it is an inbox
                                     // lane, not configuration-level selection, and post-R11-12
                                     // the lane is not even honoured on the sync engine.
  "onUnhandled": "error",            // control machines ONLY, and NOT on B18 until C-07b lands.

  "strictTargets": true,             // #147: RootTargetError at build time, non-downgradable.
  "strict": true,                    // #190/#195/#203 hold at c78ce99. The round-11 attacks on
                                     // this boundary BOTH FAILED against controls:
                                     //  - R11-01 (v2-downgrade upcast mints engine:true):
                                     //    REFUTED. from_snapshot is a DOCUMENTED TRUSTED-INPUT
                                     //    boundary (#205). The same writer reaches the target
                                     //    state via state_ids/context with NO EVENT AT ALL.
                                     //  - R11-03 (four-way after forgery): REFUTED. The only
                                     //    vector reachable from the PUBLIC API is correctly
                                     //    refused with UnknownEventError.
                                     // CONSEQUENCE, and it is the important line here:
                                     // `strict` IS NOT AND NEVER WAS A SNAPSHOT BOUNDARY.
                                     // The boundary is the HMAC TAG on the blob (CV-C53).
                                     // Residual (R11-02, Low): scheduled_sends restores
                                     // WITHOUT the strict check #214 promises, so a chart
                                     // upgrade that undeclares an event yields SILENT delivery
                                     // instead of on_invalid_event/last_error -> CV-C54.
  "maxIterations": 500,              // Lane-parity-verified (#209/#215). THREE standing notes:
                                     //  - TWO PLATEAUS, both correct (R11-DC-1, CV-C62):
                                     //    descent-seeded = maxIterations+3, externally kicked
                                     //    = EXACTLY +2. Sweeps over limits {3,5,7,9} confirm.
                                     //    The #210 CHANGELOG sentence conflates them.
                                     //  - maxIterations NEVER BOUNDED DELAYED WORK, on any
                                     //    commit. #212 gives raise(delay=) the same exemption
                                     //    `after` always had (R11-05, REFUTED - the `after`
                                     //    control behaves identically at every delay). Do NOT
                                     //    treat maxIterations as a liveness bound for timers.
                                     //  - A trip reaches ONLY last_error and ONE BENIGN EVENT
                                     //    ERASES IT (R11-09) -> CV-C59, latch from the log.
  "spawnBlockingTimeout": 5000       // Reads back as spawn_blocking_timeout_ms == 5000.0.
}
```

```python
# Runtime construction - MANDATORY (round 11, main @ c78ce99)
MachineLogic(strict=True)
create_machine(cfg, strict_config=True)        # #216, BOTH spellings (see JSON above)
Interpreter(..., max_queue_size=64, overflow_policy=OverflowPolicy.RAISE,
            service_pool_size=<explicit>)      # default is 4. SyncInterpreter accepts NEITHER
                                               # max_queue_size NOR overflow_policy (DC-1).
                                               # The gateway COUNTS call-site QueueOverflowError
                                               # refusals ITSELF - 99.3% of shed never reaches
                                               # on_event_dropped (CV-C36).

# ENGINE:   the order path runs on the async Interpreter (design preference since round 10;
#   CV-C46 retired then and stays retired). R11-12 adds a reason to keep it: the priority
#   `lane` #214 persists is honoured on the async engine ONLY - the sync engine has no
#   priority queue by construction, so a restored deadline loses precedence there.
# SERVICES: async def ONLY on the async engine (CV-C32, ground R10-D2). Blocking work via
#   asyncio.to_thread. A `def` service is non-preemptable and blocks its own machine's timers.
# ACTION NAMES: never register a user action colliding with a built-in (`raise`, `send`, ...).
#   A collision SILENTLY DISARMS the built-in: beats=0, last_error=None, no warning, no error -
#   total and completely silent. Filter through xstate_statemachine.actions.is_builtin (R11-W-2).
# ENTRY/EXIT ACTIONS: async def, yielding at least once (CV-C44). AND (CV-C51, NEW) NO entry or
#   exit action may await a RECEIPT (send(..., wait=True)) on its own interpreter, directly or
#   through a helper - #215's _descent_done gate makes that cycle unsatisfiable and start()
#   HANGS FOREVER with last_error=None, status='running' and a legal configuration (R11-06).
# start():  ALWAYS asyncio.wait_for(start(), CV_START_TIMEOUT) - never bare. A timeout is a hard
#   startup failure, NEVER a retry (CV-C56, supersedes CV-C39). This is the only detector we
#   have for R11-06.
#
# TIMERS - the round's central rule, and it is a THREE-WAY SPLIT (CV-C61, ground R11-04):
#   (1) restart-critical deadlines -> raise(delay=), with a STABLE send_id (R11-W-1), on a
#       machine with a BOUNDED INTERPRETER LIFETIME, with len(i._timer_handles.get(i.id, []))
#       exported as a gauge and alerted. This path LEAKS ONE TIMER HANDLE PER BEAT, FOREVER,
#       on BOTH engines: +455 MB / 24 s at 200 machines, strictly linear, no plateau. No usage
#       bounds it - id reuse, explicit cancel(sendId) before re-arm, and a 250 ms period all
#       retain 1.00/beat. Reclaimed only at stop().
#   (2) everything periodic and non-persistent -> `after:` (0.00 handles/beat, leak-free).
#   (3) NO HIGH-FREQUENCY raise(delay=) HEARTBEAT UNDER ANY CIRCUMSTANCES (CV-C47, which
#       STANDS, is WIDENED, and is now LOAD-BEARING on R11-04 rather than precautionary on
#       R10-03 - #212 closed its original ground and R11-04 replaced it).
#   NO delay below 10 ms anywhere, either spelling (CV-C55): delay is MILLISECONDS and the
#   Windows clock floor is ~15.6 ms.
#   CV-C12 STANDS UNCHANGED: `after` remains BANNED in catalogue machines. BENCH-6 is not just
#   still missed (174.4 ms vs <=100 ms) but UNMEASURED FOR FOUR ROUNDS. All algo timing stays
#   on the external MonotonicScheduler with absolute *_us deadlines in context. `after` is
#   permitted ONLY for coarse timeouts where seconds of lateness is tolerable.
#   NOTE (R11-W-3): SimulatedClock fires NEITHER `after` NOR restored scheduled_sends on this
#   build. Deadline properties must be verified against the REAL clock.
#
# SNAPSHOT: factory wrapper only; at quiescence (CV-C23); ROOT ONLY (CV-C41). #213 now persists
#   armed delayed self-sends EXACTLY (600/600, right remaining_ms +/-0.5 ms, right send_id,
#   fires not early not late exactly once) - so CV-C49's original ground is CLOSED and it is
#   REWRITTEN as CV-C49': NEVER RE-PERSIST AN INTERPRETER THAT HAS NOT BEEN start()ed. The
#   restored debt sits in _restored_self_sends until start() consumes it, while
#   _persist_scheduled_sends reads only _armed_self_sends - so a journal-compaction or
#   migration job that loads and re-writes without starting DESTROYS EVERY DEADLINE (R11-08,
#   CV-C58). Never read a send(wait=True) receipt for configuration NOR as "the chain
#   finished" - it is a MACROSTEP receipt.
#   The library's structure_hash OMITS raise(delay=) delays although it covers `after` delays
#   (R11-11) - changing delay 60000 -> 100 leaves the hash BYTE-IDENTICAL. Our envelope tag
#   must cover the CHART BYTES; do not rely on machine_hash for delay drift.
#
# RESTORE: pass minimum_version=3 (CV-C52, raised from 1 - v3 is the layout that carries
#   provenance) and expected_machine_hash=<ours> explicitly. Our envelope ALSO writes and
#   VERIFIES an HMAC TAG over the whole blob (CV-C53) - #205's machine_hash is explicitly
#   "NOT A MAC", and BOTH of this round's refutations turn on from_snapshot being a documented
#   TRUSTED-INPUT boundary. THE TAG IS THE BOUNDARY; strict and minimum_version are not.
#   CV-C48 RETIRES - #214's v2 upcast closes the 0.8.0 `after`-record migration cliff, and the
#   security objection to that upcast was refuted. CV-C45's stripping clause RETIRES with it,
#   replaced by CV-C45": read last_error / last_transition_ok IMMEDIATELY AFTER from_snapshot
#   AND BEFORE start() (CV-C60) - on_invalid_event is STRUCTURALLY UNREACHABLE on the restore
#   path (from_snapshot takes no plugins= and is still constructing the interpreter), and
#   last_error holds only the LAST refusal and reverts to None after start(). Reconcile
#   ADMITTED vs PERSISTED record counts and fail loudly (CV-C54). Assert configuration/state_ids
#   agree BOTH ways (CV-C27').
#   Do NOT depend on restored ORDERING at all: `lane` is forgeable on async (R11-02c) and
#   unenforceable on sync (R11-12).
#
# OBSERVABILITY: CvErrorHooks implements on_invocation_stranded; the supervisor samples
#   on_event_dropped(..., "chain_budget") and asserts has_dormant_invocations() is False.
#   NEVER POLL last_error FOR CHAIN HEALTH (CV-C59): a RunawayChainError trip reaches only
#   last_error and ONE BENIGN EVENT ERASES IT - 6/40 (def) and 8/40 (async) post-mortems on a
#   PERMANENTLY INERT machine read status='running', last_transition_ok=True, last_error=None,
#   pending_events=0. Post-#212 a legal heartbeat guarantees ticks keep arriving, so in an OMS
#   the race is won by the eraser. LATCH from the log or a latching plugin wrapper.
# BUDGET SIZING: two plateaus, both correct - descent-seeded maxIterations+3, externally kicked
#   exactly +2 (CV-C62). Sizing against the external number under-provisions descent by ~2.7x.
```

---

## 8. Release-readiness for 0.8.1

### Would we pin a tag cut at `c78ce99`?

**Yes — with one carve-out, and the carve-out is a lint rule we already run.**

If upstream cut `v0.8.1` at `c78ce99` today, **we would pin it**, in preference to `0.8.0` and in preference to `19cb1f1`. The reasoning:

- **It is unambiguously better than every prior build in the series.** Five fixes land clean on both engines and both service spellings. Round 9's two Highs and round 10's five Mediums are closed at the sites named. No true regression exists across 163 gate checks and 527 sweep scripts.
- **Its one High-severity defect is fully contained by a constraint that predates it** (CV-C47, green since round 10), and the containment costs us nothing we were not already paying — K11 records that **no catalogue machine currently uses a timer at all**.
- **Both security alarms were false.** The trust boundary is where the docs say it is, and our HMAC envelope was already sitting on it.
- **The alternative is worse.** Staying on `19cb1f1` means keeping the #206 rule (which makes a legal heartbeat die at 12 beats), keeping the unpersisted-deadline gap #213 closes, and keeping the 0.8.0 `after`-record migration cliff #214 closes. `19cb1f1` leaks too — it is merely capped at ~12 handles because a *different* defect kills the cycle first.

**The carve-out:** we would pin it **with CV-C47/CV-C61 enforced in CI**, i.e. we would not ship a machine that uses `raise(delay=)` for periodic work on this tag. That is a row-6 adoption, written down as such.

**Pin on the commit, not the string.** `__version__` reports `0.8.0` on this tree. If a tag lands, our pin must assert the **resolved commit sha** and the source sha256, not `xstate-statemachine==0.8.1` — this is the eleventh round in which the version string has been wrong, and it will bite whoever trusts it.

### What must land before we would call 0.8.1 *unconstrained*-ready

In priority order. The first is the only one that changes our gate row.

| # | Item | Why it blocks | Size |
|---|---|---|---|
| **1** | **R11-04** — key the delayed-self-send handle by the **owning state id** (or discard it in `_fire`/`_cancel`). `interpreter.py:2354`, `sync_interpreter.py:1198`; the `after` path at `:2747` already does this correctly with `owner_id=state.id`. | **The only open High. Landing it alone returns us to row 8** and dissolves the R11-04 / R11-DC-2 / K11 tension entirely. | **One line per engine.** |
| 2 | **R11-06** — bound the `_descent_done` gate with `wait_for`, or set it before running entry actions and use a re-entrancy flag (which is what #215's own comment says it mirrors from the sync engine). | A silent, unbounded hang inside `start()` with no diagnostic is the worst failure shape in an OMS. | Small. |
| 3 | **R11-07** — **recurse** `validate_top_level_keys` over state nodes. `KNOWN_MACHINE_KEYS` already contains every state-level name; the recursion is the only missing part. | #216's value is ~95 % unrealised without it, and the nested case emits no WARNING either. | Small. |
| 4 | **R11-08** — have `_persist_scheduled_sends` union `_armed_self_sends` with any unconsumed `_restored_self_sends`. | Re-opens #213's own failure one hop out. | Small. |
| 5 | **R11-02** — route `_rearm_restored_self_sends` through `_admit_restored`, and refuse `kind in (done, error, after)` in `scheduled_sends` outright (a delayed *self-send* is never a completion). | Makes #214's stated invariant actually true for both halves of the restore path. | Small. |
| 6 | **R11-09** — make a chain trip **sticky**: a `chain_trips` counter or a dedicated `on_chain_budget_exceeded` hook, as #207 did for stranding. | Today only the log remembers. | Small. |
| 7 | **R11-10** — add `plugins=` to `from_snapshot`, or defer the refusal report to `start()`. Also fix the library's own pin, which registers the plugin *after* the restore and never asserts on it. | #214's CHANGELOG claim is currently false as written. | Small. |
| 8 | **R11-11 / R11-12 / R11-01-doc / #210-doc** — include `raise` delays in `structure_hash`; document that `lane` is async-only; change the snapshots guide's anti-downgrade floor from `minimum_version=1` to `3`; fix the `+2`/`+3` contradiction. | Doc and parity hygiene. | Trivial. |
| **9** | **A completed full-suite + coverage run at this commit, and BENCH-6 measured.** | Not upstream's obligation — **ours**. Decision-table row 2 currently rests on a one-commit-stale number, and BENCH-6 has been unmeasured for four rounds while CV-C12 stands on it. | One dedicated round-12 time slice. |

**Items 1–8 are all small and six of them are one-liners.** This is the most tractable defect list the series has produced. If items 1–4 land, the next round is row 8 again with a materially lighter constraint set.

---

## 9. What would change the verdict

Falsifiable, in rough order of likelihood. Each is written so that a single measurement settles it.

1. **R11-04 fixed upstream → row 6 becomes row 8 immediately.** The single most valuable change available, and it is one line per engine. This is the whole of the gap between this round and the last.
2. **A completed suite run at `c78ce99` that fails, or drops coverage below 86 % → decision-table row 2 fires and the verdict becomes DEFER**, regardless of everything else in this document. Row 2 sorts *above* every adoption row. We have observed zero failures in ~4 % of the suite and 65/65 on the round8-10 pins under two hash seeds, so this is unlikely — **but it is currently unmeasured at this commit, and it is the single largest open risk on this board.** Round 12's first time slice goes here.
3. **BENCH-6 measured and MET (≤100 ms p95 at 500 busy interpreters) → CV-C12 retires**, `after` becomes usable for real deadlines, the external `MonotonicScheduler` requirement relaxes, and — combined with item 1 — the R11-04/R11-DC-2/K11 tension disappears from both ends. Four rounds unmeasured. **Round 12's second time slice.**
4. **BENCH-6 measured and MISSED badly (worse than 174.4 ms) → CV-C12 hardens** and K11's "move deadlines into the charts" plan needs rethinking before it starts.
5. **A catalogue machine that genuinely requires a restart-safe periodic deadline → R11-04 goes to Critical for us specifically.** Today K11 says no chart uses a timer at all, which is why the containment is free. The moment B6/B7/B8's algo timing moves into the charts (which is the direction E50 is heading), CV-C61's narrow exception becomes load-bearing and a leaking primitive becomes a production dependency. **Watch this one — it is our own roadmap walking into the defect.**
6. **A vector reaching the `after`/`done` selection site from genuinely outside the process** — without attacker-controlled Python and without blob-write. That is the exact boundary both R11-01's and R11-03's refutations rest on, and it is falsifiable by construction. Such a vector would restore R11-01/R11-03 toward Blocker and put CV-C45's send-side clause back on duty. **Attacked in rounds 10 and 11; not found in either.** A third failed attempt should retire this line of attack rather than a fourth repetition of it.
7. **A restore→re-persist drill that loses a real deadline → R11-08 goes High.** CV-C58 contains it, but the containment is *ours* and untested in anger, and a journal-compaction job is exactly the kind of utility that gets written without reading this document.
8. **An entry-action hang observed in a real drill → R11-06 goes High.** Currently Medium because "await your own receipt" is unusual; "await a helper that happens to await a receipt" is not.
9. **A nested config typo reaching production → R11-07 goes High.** Contained only by CV-C57, which is a validator **we have not written yet**. Until it exists, this is our least-defended Medium.
10. **The `rollback_and_defer` policy cost staying at 0.536×** (it was 0.754× in round 10, and 0.75–0.93× in round 9). One reading outside its prior band, not bisected. If round 12 reproduces it, it is a real regression in the combined-policy path and should be filed; if not, it is contention noise.
11. **KB/order continuing to climb** — 2.128 → 3.064 → **5.512 KB/order** across rounds 9/10/11. Each reading is a single-sample RSS delta over ~1.5–2.7 MB of signal, so probably noise, **but the spread is widening rather than narrowing**. Round 12 should take n>1 samples rather than treat another single reading as informative.

---

## 10. Next steps

### Phase-3 gates, re-evaluated against this evidence

Round 10 authorised Phase 3 (order-path shim retirement) to **begin**, with four acceptance conditions of which (iii) — the ≥86 % coverage measurement — was the only one with a library dependency, and it was discharged at 92.78 %.

**Re-evaluation at `c78ce99`:**

| Condition | Status | Change this round |
|---|---|---|
| (i) Both library gating Highs closed | **HELD, with an amendment.** #203/#204 remain closed. But the High row is **no longer empty**: R11-04 is open. | **Phase 3 continues** — R11-04 is contained by a green lint and touches a primitive **no catalogue machine currently uses** (K11). It is **not** a Phase-3 gate. It **becomes** one the moment K11 is addressed (see §9 item 5). |
| (ii) CV constraints enforced by lint **and** covered by their named tests | **PARTIAL and now materially larger.** Twelve new constraints (CV-C51…CV-C62) plus three wrapper rules land this round; two retire; two are rewritten. **CV-C57's recursive validator does not exist yet** and is the least-defended item. | **This is now the critical path for Phase 3**, ahead of anything library-side. |
| (iii) Coverage ≥86 % | **HELD on carried evidence** (92.78 % at `19cb1f1`), **not re-measured at `c78ce99`**. | Downgraded from "discharged" to "carried". Round 12 first slice. |
| (iv) Five green nightlies, lint+tests, two-week canary | **Ours, unchanged.** | **Canary is gated on C-04 and C-07b landing** — six rounds open, both config-only, both blocking B16/B18 from the order path. |

**Verdict on Phase 3: CONTINUE.** The order-path shim retirement does not stop. What changes is that the *binding* constraint is now unambiguously our own work — the CV-C5x test/lint build-out and the two catalogue Blockers — not the library.

### E50 tickets

New and updated tickets for `docs/plan/backlog/E50.json` (see the file for full bodies):

| Ticket | Title | Priority |
|---|---|---|
| **E50-T42** | Land C-04 (hoist `LOGOUT`/`IDLE_DEADLINE`/`ABSOLUTE_DEADLINE` to the B16 root) — **Blocker, open six rounds, config-only** | P0 |
| **E50-T43** | Land C-07b (ordered unguarded `RELEASE` fall-through on B18 `engaged`, auditing the denial as a no-op) — **Blocker, open six rounds, config-only; the Amendment-6 removal has still not landed in `ka_killswitch`** | P0 |
| **E50-T44** | Implement **CV-C57**: recursive state-node key validator against `KNOWN_MACHINE_KEYS` at build time + `test_cv_c57_nested_typo_rejected` | P1 |
| **E50-T45** | Implement **CV-C61** timer policy: lint the three-way split, export the `_timer_handles` gauge, soak assertion; widen the existing CV-C47 lint | P1 |
| **E50-T46** | Implement **CV-C51** + **CV-C56**: ban receipt-awaits in entry/exit actions; wrap every `start()` in `wait_for` with a hard-fail timeout | P1 |
| **E50-T47** | Implement **CV-C58** / **CV-C49′**: never re-persist an un-`start()`ed interpreter; audit the journal-compaction job | P1 |
| **E50-T48** | Implement **CV-C59** + **CV-C60** + **CV-C54**: latch `RunawayChainError`; read `last_error` before `start()`; reconcile admitted-vs-persisted record counts | P1 |
| **E50-T49** | Implement **CV-C52/53/55**: `minimum_version=3` at every restore call site; HMAC envelope over the blob covering chart bytes; ban sub-10 ms delays | P1 |
| **E50-T50** | Retire **CV-C48** and CV-C45's stripping clause; delete their workaround tests (a mitigation that outlives its defect becomes folklore) | P2 |
| **E50-T51** | Round-12 measurement debt: **full suite + coverage at the pinned commit, run ALONE and FIRST**; then **BENCH-6** alone; then n>1 KB/order samples and a `rollback_and_defer` repeat | P0 |
| **E50-T52** | K11: decide whether catalogue deadlines move into the charts. **Blocked on R11-04 upstream** — moving them today adopts a leaking primitive as a production dependency | P2 |
| **E50-T53** | Implement **CV-C62** budget sizing (both plateaus) and **R11-W-1/2/3** catalogue lints (stable `send_id`; built-in action-name collision check via `actions.is_builtin`; real-clock deadline verification) | P2 |

### Upstream, in priority order

**R11-04** (the open High, one line per engine) → **R11-06** (bound the gate) → **R11-07** (recurse the existing key list) → **R11-08** (union the two dicts) → **R11-02** (compose #213 and #214) → **R11-09** (sticky chain trip) → **R11-10** (`plugins=` on `from_snapshot`) → then R11-11, R11-12, the `minimum_version` doc floor, and the `#210` `+2`/`+3` doc contradiction. Drafts in `issues/post-c78ce99/` — **not posted**.

### Round-12 method notes

1. **Run the full suite alone and first**, before any benchmark competes for CPU. Three consecutive rounds have failed to complete it.
2. **Then BENCH-6 alone**, per-tier, at the specified 300 s cap. Four rounds unmeasured while CV-C12 stands on it.
3. **Run timing-sensitive scripts serially** — the parallel sweep manufactured four false FAILs this round, and the baseline is serial.
4. **Retire `206_delayed_selfsend_charged.py` from the gate** before the next run (§2b, and `gate/run_gate.py` updated accordingly).
5. **Test every blob-write finding against the `state_ids`-only control first.** Three rounds, three refuted Blockers, one pattern: if the same writer reaches the same place without the forgery, there is no defect. Make it a triage precondition rather than a refutation step.

---

*Verdict: `64-r11-final-readiness-verdict.md`. Register: `63-r11-findings-register.md`. Refutation: `64-r11-04-refutation.md`. Regression: `60-r11-regression.md`. Suite/bench: `61-r11-suite-bench.md`. Diff review: `62-r11-diff-review.md`. Battle: `battle-c78ce99/`. Drafts: `issues/post-c78ce99/` — **not posted**.*
