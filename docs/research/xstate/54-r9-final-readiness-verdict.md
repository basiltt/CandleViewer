# 54 — Round-9 FINAL readiness verdict: `xstate-statemachine` main @ `f28719c` (unreleased 0.8.1)

Date: 2026-09-22. Question asked by the owner: *"Verify all reported issues are genuinely closed; is the library completely ready, fully battle-tested, and are we good to proceed?"*

**Identify this build by commit, never by version string.** `__version__` still reports `0.8.0` on `f28719c` (merge of PR #202, `fix/0.8.1-round8`) while `CHANGELOG.md [Unreleased]` targets 0.8.1. Every pin, gate baseline and CI assertion keys on the commit plus its source sha256.

Method: 12 issue verifications (round-8 fixes #192–#201 plus reopened #181/#186) re-run live; full regression sweep (`50-r9-regression.md`); suite + benchmarks (`51-r9-suite-bench.md`, partial — see §2); diff review `6db65d8..f28719c` (`52-r9-diff-review.md`); all 8 battle tracks re-run (`battle-f28719c/*.md`); all 20 contract machines driven end-to-end **on both service spellings**; then triage → dedupe (`53-r9-findings-register.md`) → **independent adversarial refutation of every Blocker and High**, applied below.

**Financial-OMS standard applied throughout:** nothing counted without a standalone repro on a clean interpreter, and **every service-related check run with both `def` and `async def` services**.

---

## 0. The answer

### Are the 12 reported issues genuinely closed?

**Eleven of twelve changed code and hold on re-verification. One (#197) is closed only in part. Two of the eleven are closed *narrower than claimed*, and the narrowing is where this round's two Highs live.**

- **FIXED, clean, verified on both service kinds and both engines (9):** **#181, #186, #192, #194, #198, #199, #200, #201, #196.** Each re-runs green in `issues/verify-main-f28719c/*.result.md` with the `def` / `async def` cells at parity. #194 is the standout: the per-child bound *and* an always-on WARNING now fire even on the non-preemptable `def` lane, which is exactly the "test that cannot fail" defect round 8 called out. #196 additionally closed the `SyncInterpreter` invoked-child pump-thread leak.
- **FIXED with a surviving residual (2):** **#195** (engine-event provenance is real and closes by-name laundering — but it was never wired into the `after` selection site, which is **R9-02, High**), **#193** (rollback cancellation of a `def`-service handoff genuinely landed on the async engine — but the **roll-forward** half did not land on either engine, and the sync engine leaks both halves: **R9-04, High**).
- **PARTIAL (1):** **#197.** The library's own pinned property test passes, but the reporter's original `always`+nested-final+`after` chart still yields a success-shaped `send(wait=True)` receipt over an empty configuration. `get_persisted_snapshot()` correctly refuses at the same instant, so the torn state is not persistable — the residual is a *receipt* defect (**R9-08, Medium**), not a persistence one.

**The round's one sentence: #195 built the right mechanism and applied it to two of the three event families it covers.** `base_interpreter.py:4523` still selects `after` transitions on a bare `isinstance(event, AfterEvent)` against the **public exported** class, never consulting `is_system_event` / `_EngineAfter` — unlike the `DoneEvent`/`ErrorEvent` branch eight lines below it. Same file, same function, same release, one branch short.

### Is the library fully battle-tested and ready?

**Closer than it has ever been, and for the first time the answer on the order path is yes-with-constraints rather than no.** After independent refutation the round leaves **0 Blocker · 2 High · 5 Medium · 8 Low** live library defects. Refutation moved **three of five** Blocker/High candidates *down* (**R9-01 Blocker→Low**, **R9-03 High→REFUTED outright**, **R9-05 High→Medium**) and **none up**. That is the best post-refutation position in nine rounds — round 8 closed 1 Blocker · 3 High, round 7 2 Blocker · 4 High, round 5 4 Blocker · 8 High.

**Round 8's Blocker R8-01 is closed.** #192 taught the *drop* site the provenance rule the charge site already knew: the priority lane now charges self-issued sends and shields external ones by provenance rather than FIFO position, verified on both engines and both service kinds. That was the single thing round 8 said would flip the verdict, and it flipped it.

The two surviving Highs, both CONFIRMED against every refutation axis:

- **R9-02 (High, CONFIRMED, and sharpened this round)** — **`after.*` is matched on the public class.** The discriminating control refutes the open-namespace defence: at the **default `strict=False`**, `AfterEvent("after.60000.m.work")` → `['m.expired']`, while a plain `Event` of the *same name* and a bare string both stay in `['m.work']`. The class itself is privileged, and `AfterEvent` is exported from the package root. **One correction to the register, made by re-running the vector rather than inheriting it:** with `strict=True` the *send-side* vector **is** correctly refused (`UnknownEventError`) — so #195's send-side gate does cover hand-built `AfterEvent`s, and the register overstated this half. What survives is the vector that needs no API call at all, and it is the serious one: `t3_snapshot_after.py` plants a forged `pending_events` record `{"kind":"after","type":"after.60000.m.work"}` with **no `"engine"` flag**, which restores as user traffic per #195 and is then handed straight to the inbox by `_enqueue_restored` (`base_interpreter.py:1768`), **bypassing the `send()`-time `strict` check entirely**. **Re-run fresh this round: with `strict=True` the machine still reaches `m.expired` — a 60-second timer fired instantly from untrusted snapshot data.** Not documented away, not API misuse, not a duplicate (#195 built `_EngineAfter` but never switched this selection site). Fix is one line: gate `:4523` on the minted subclass. Repro: `issues/post-f28719c/new/repro/R9-02_after_matched_on_public_class.py`, **2/2 vectors fire** (A at the default, B even under `strict`).
- **R9-04 (High, CONFIRMED)** — **a `def` service armed by a transition an `always` rolls forward is still submitted.** Re-run fresh this round, `battle-f28719c/contracts/repro/ld01_always_rollforward.py`: **3 of 6 lanes leak** — case A (roll-forward) leaks on `def`/async-engine and `def`/sync-engine; case B (rollback) leaks on `def`/sync-engine. `docs/_guide/production-characteristics.md:97` promises the exact opposite in so many words ("rolled forward (an `always` out of the state before it stabilises) is **never** submitted to the pool"), and the leaking case A row is verbatim that sentence. SCXML 6.4 sides with the reporter: `exitStates` removes the state from `statesToInvoke`, so a state left by `always` in the same macrostep must never invoke. Worse, the library is **internally inconsistent**: `test_round8_findings.py::test_always_rollforward_matches_sync` pins the *leaking* behaviour as the contract while the CHANGELOG and docs promise non-submission — so the green suite never covers the published claim. In OMS terms this is a real child-order submission issued from a state the machine never settled in.

**Both are mechanically mitigable by us, and that is what decides the gate.** R9-02 is contained by **CV-C45**, which we already mandate — it strips every `DoneEvent`/`AfterEvent` from `pending_events` before `from_snapshot()` and rejects both classes at the gateway; it needs only the `AfterEvent` send-side clause made explicit (§7). R9-04 is contained by **CV-C32** — the only async-engine leak is `def`-service, and CV-C32 already bans `def` services on the async engine outright; the sync-engine lanes are contained by new **CV-C46**, which keeps the order path off `SyncInterpreter` entirely.

**What is *not* a defect, stated plainly because three rounds of register inflation ran through here.** **R9-01 is not a Blocker and never was.** Every successful forgery vector requires a capability that already dominates the engine — holding a genuine engine-minted event, importing an unexported underscore-private class, or authoring arbitrary snapshot records — all three documented at `events.py:245-252` and `:405-412` as the intended trust boundary per #185. The only vector reachable *without* privileged capability, a hand-built public `DoneEvent`, is still correctly refused. XState v5 performs no provenance check on `xstate.done.actor.*` at all and SCXML 6.4 treats `done.invoke.<id>` as a plain internal-queue event name, so this library is **stricter than both**. Six sub-findings merged into R9-01 are one finding restated; merging does not aggregate severity. **Low**, with a doc-note ask. And **R9-03 is refuted outright**: its "permanent starvation" rests on reading a counter after a fixed `asyncio.sleep(1.0)`; polling until the queues drain gives **500/500 applied, inbox 0, priority 0** on both lanes, its "silent, no error" claim is backwards (both lanes now trip `RunawayChainError` — that *is* the #179/#201 fix), its ablation table is stale, and its chart is a documented-invalid unguarded `always` into its own region.

### Are we good to proceed?

- **Non-order paths (B10–B17, B19, B20): YES — proceed now**, under §7's constraints. Unchanged from round 8 and strengthened: all five control machines build clean from the corrected catalogue JSON and pass every invariant on both spellings, with round-7's CV-221-01 Blocker confirmed closed at identical lap counts on both lanes.
- **Order path (B1–B9, B18): YES — proceed, WITH CONSTRAINTS. This is the round the order path opens.** No Blocker survives refutation. Both Highs are upstream, both are one-line-shaped, and — decisively — **both are fully contained by constraints we already mandate and lint** (CV-C45, CV-C32), not by convention. That is decision-table **row 6**, not row 7.

**What blocks, and whose it is.** *Nothing blocks adoption.* Two things block **shim retirement on the order path**, and both are **UPSTREAM**: R9-02 (gate `base_interpreter.py:4523` on `_EngineAfter`) and R9-04 (cancel the `def`-service executor handoff on the `always` roll-forward epilogue, and on both halves in `SyncInterpreter`). Until they land, the order path runs **behind our contract suite with CV-C45/C32/C46 enforced**, which is exactly what "with constraints" buys. What blocks **B16 and B18 specifically is still OURS** and unchanged for four rounds: catalogue Blockers **C-04** (B16 elevation outlives revocation) and **C-07b** (B18 `onUnhandled:"error"` bricks the kill switch on a guard-denied `RELEASE`). Those are ours to fix and they gate no library decision.

**One measurement we owe and did not make, stated rather than glossed.** The full suite + coverage total did not complete inside the 20-minute bound (~51 % of collected tests observed green). Coverage is therefore **unmeasured this round** — it was 92.70 % at `6db65d8` and nothing in the diff suggests a drop, but decision-table row 2 keys on it and I am recording it as an open measurement, not as a pass. I did, however, run down the one suite failure that *was* visible, and it is **not** a library defect: `TestAsyncRollbackRearmCycleBounded::test_service_calls_bounded_by_max_iterations` (kind=`def`) asserts equality across a 0.6 s / 0.3 s sleep pair, and on this host the `def` lane is still climbing at 0.6 s. Polled to convergence (`battle-f28719c/r9triage/t_r6_plateau.py`, new, standalone) **both lanes plateau at exactly 1003 = `maxIterations`+2 and stay there** — `def` reaches it at ~1.0 s, `async` before 0.5 s. **The cycle is bounded; the library's own test sleeps too briefly.** Round 9's characterisation of this as a possible regression needing root-cause is superseded: it is a too-tight test bound, filed as a comment on the release ticket.

---

## 1. The 12 issues

| # | Claim in `CHANGELOG [Unreleased]` | Verified disposition at `f28719c` | Residual |
|---|---|---|---|
| **#181** | `children_timeout` per child + WARNING always on overrun | **FIXED** — WARNING fires on **every** overrun; `def` lane uncancellable-but-reported, `async def` bounded ~0.11 s. Both confirmed fresh. Closes round-8 R8-03, whose whole complaint was the suppressed WARNING. | — |
| **#186** | contradictory `configuration`/`state_ids` refused | **FIXED** — agreement now enforced **both directions** on both engines; `SnapshotCorruptError` on empty *and* contradicting. Closes R8-08 (the one-sided `or`). | — |
| **#192** | priority lane sheds by provenance, not FIFO position | **FIXED** — charges self-issued sends, shields external sends, on both engines and both service kinds. **Closes round-8's sole Blocker R8-01.** | lane + tag not persisted (**R9-10**, Low) |
| **#193** | `def`-service executor handoff moved into the engine-held task so rollback/roll-forward cancels before submission | **FIXED-OPT-IN, two-thirds delivered** — rollback half genuinely lands on the async engine (the dangerous half in OMS terms). Mid-run `def` cancellation explicitly out of scope per the documented in-step-await contract. | **R9-04 (High)** — roll-forward half unfixed on both engines; `SyncInterpreter` leaks both halves |
| **#194** | per-child bound + always-on WARNING | **CONFIRMED FIXED** — async `def` at n=1 and n=5; non-preemptable `def` now **does** fire the WARNING (elapsed unbounded, as documented). Exactly the axis round 8 said the shipped test could not fail on. | — |
| **#195** | private engine event subclasses; strict refuses user-built ones | **FIXED for `done`/`error`** — hand-built and unmarked-restored `Done`/`Error` events refused under `strict` on both engines and both service kinds; marked restores keep provenance. | **R9-02 (High)** — the `after` family was never wired to the new gate; **R9-01** (Low) privileged-capability forgery; **R9-12** (Low) `done.state.*` unreserved |
| **#196** | `always` selected only in the eventless settle pass (SCXML §3.13) | **CONFIRMED FIXED** — `always` never steals a named `EXT` event, **200/200 applied** on both engines and both kinds; `SyncInterpreter` invoked-child pump thread no longer leaks. | — |
| **#197** | (closed in round 7/8 by #179/#182) | **PARTIAL** — library's own pinned property test passes, but the reporter's original `always`+nested-final+`after` chart still returns a success-shaped `send(wait=True)` receipt over an empty configuration. `get_persisted_snapshot()` correctly refuses at the same instant, so nothing torn is persistable. | **R9-08 (Medium)** — receipt defect only |
| **#198** | versioned running snapshots need both configuration fields non-empty | **CONFIRMED FIXED** — refuses emptied/dropped `configuration` or `state_ids`; v0 still accepted by design; both engines. | **R9-14** (Low) — narrows v1 compat beyond what the changelog names |
| **#199** | `on_interpreter_start` inside the in-flight window | **CONFIRMED FIXED** — flag raised before the hook on both engines; hook-time snapshot refused with `SnapshotMidStepError`. Closes round-8 R8-09. | **R9-15** (Low) — `child=False` misreported |
| **#200** | `_chain_owed` is a task set self-clearing via done-callback | **CONFIRMED FIXED** — clears on any terminal outcome including bare `BaseException`; debts stay per-invocation independent. Closes round-8 R8-10. | — |
| **#201** | lap parity | **CONFIRMED FIXED** — initial-descent completions seeded not charged; async lap counts now match sync exactly. The documented rollback+`onDone` asymmetry is explicit, not a regression. Closes round-8 R8-11. | **R9-09** (Medium, doc) — "all three lanes agree at every limit" is still false at odd `maxIterations` on the `def` lane |

**Score: 9 clean · 2 fixed-with-High-residual · 1 partial · 0 not-fixed · 0 documentation-only.** No issue regressed. Every round-8 residual that round 8 itself named as its exit condition (R8-01, R8-03, R8-08, R8-09, R8-10, R8-11) is closed.

---

## 2. Regressions

### 2a. Library regressions (`6db65d8` → `f28719c`)

**Zero true PASS→FAIL regressions.** The gate (`run_gate.py`, 143 checks) shows exactly one cell flip, investigated and dismissed:

| id | label | baseline | current | disposition |
|---|---|---|---|---|
| LC-42 | `send_receipt` (`verify`) | PASS | FAIL | **HARNESS-ERROR / flaky threshold.** Asserts `send_priority()` p50 < 1 ms behind 2 000 queued events. Re-ran ×5: **4/5 PASS** (p50 0.396–0.738 ms), fails only under host load. Every other assertion in the script passed every run; the `verifyM` twin stayed green 5/5. Not a functional defect. |

The three pre-existing blocking FAILs are **byte-identical to baseline** and already triaged: `167` (`verifyM4`/`verifyM5` rollback_reinvoke_spin — expected; CHANGELOG #201 explicitly does not promise the sync re-arm), `PROBE-01` (16/20, same 4 cells A3/A6/A10/A18), `PROBE-03` (13/17, same 4 cells C6/C7/C15/C17).

**One suite failure, re-triaged this round and reclassified.** `tests/test_round6_findings.py::TestAsyncRollbackRearmCycleBounded::test_service_calls_bounded_by_max_iterations` (kind=`def`) fails standalone 4/5 where round 8 recorded 0/3 — round 9 escalated it to "needs root-cause, possible regression". **It is neither a regression nor a library defect.** The test reads the counter at 0.6 s and again at 0.9 s and asserts equality; on this host the `def` lane is still climbing at 0.6 s. Polled to convergence:

```
kind=def   status=running final_calls=1003
  series=[(0.5,781),(1.01,1003),(1.52,1003),(2.03,1003),(2.54,1003),(3.05,1003),(3.55,1003)]
kind=async status=running final_calls=1003
  series=[(0.51,1003),(1.02,1003),(1.53,1003),(2.03,1003),(2.54,1003),(3.05,1003)]
BOUNDED=True plateau=1003     # == maxIterations + 2, both lanes
```

`battle-f28719c/r9triage/t_r6_plateau.py` (new, STANDALONE). **The cycle is bounded and lane-identical; the library's own test sleeps too briefly.** Filed as a comment on the release ticket, not as a finding.

**Coverage is unmeasured this round** — the `--cov` run did not finish inside the wall-clock bound (~51 % of collected tests observed, all green). Decision-table row 2 keys on coverage ≥ 86 %; it was 92.70 % at `6db65d8` and the diff adds tests without removing any, so row 2 is not triggered on available evidence — but this is an **open measurement**, recorded as such, and it is the first item in §8's re-verification recipe.

### 2b. Ours — stale fixtures, not library regressions

Six of our own scripts exit non-zero for reasons that are **our staleness**, not library behaviour. All are fixed or retired in `run_gate.py` per §10:

| Script | Why it exits 1 | Action |
|---|---|---|
| `post-6db65d8/new/repro/R8-02_def_service_uncancellable…py` | Asserts the pre-#193 expectation; `def` non-cancellability is now a **documented contract**, not a bug | Retire → rewrite against the documented contract |
| `…/R8-03_children_timeout_def_noop.py` | #194 changed the contract (WARNING now always fires) | Retire — superseded by `194_children_timeout_per_child.py` |
| `…/R8-04_always_ondone_reentry_settle_tripped.py` | #196 moved `always` into the settle pass; the assertion predates it | Retire — superseded, and R8-04's premise is what R9-03 refuted |
| `…/R8-11_service_kind_lap_parity.py` | #201 restated parity exactly, with one documented exception | Retire — superseded by the `201_*` verification |
| `…/R8-05_doneevent_forgery.py` | `check2` does not catch `UnknownEventError` — **which is the #195 protection firing**. `check1` shows the forgery does not drive `onDone` | **Fix**: treat `UnknownEventError` as the success mode |
| `verify-main-f28719c/197_empty_config_wait.py` | Carries an assertion beyond the gate-tracked `verifyM5` cell (which PASSes) | **Keep and promote** — it is the genuine R9-08 signal; the gate cell is the weaker one |

Two further artefacts from round 9's sweep are **not** failures: `195_provenance.py` and `196_always_vs_named_event.py` both pass at RC=0 once given ≥90 s (each contains multiple 30 s-sleep service cells); their earlier "TIMEOUT"/143 readings were the sweep's shorter default timeout. `run_gate.py` gets a per-script timeout override for both.

---

## 3. Scorecard per battle track (both service kinds)

`async` = `async def` services on `Interpreter`; `def` = plain `def` services, run on `Interpreter` and, where the track covers it, on `SyncInterpreter`.

| Track | async | def | New defects | Verdict |
|---|---|---|---|---|
| **semantics** | clean | clean | R9-08 (Med), R9-13 (Low) | Prior-defect table fully re-run; #193/#194/#195/#196/#198/#199/#200/#201 all hold on both kinds. |
| **concurrency** | clean | clean | R9-11 (Low) | 4 of 5 prior defects FIXED, including the round-8 Blocker and High, **fixed at the root rather than papered over**. |
| **persistence** | clean | clean | R9-01 (Low, was High), R9-05 (Med), R9-10 (Low) | 4 of 5 prior FIXED; 0 torn blobs, 0 raw leaks, 0 round-trip mismatches across **320 random machines × both kinds**; 200-machine/4-min soak with **0 dropped external priority sends**. Sound against corruption and accident; **not an authenticity boundary**. |
| **determinism** | clean | clean | — | All round-5/6/7 determinism fixes hold; `d1`–`d10b`, `e1`, `f1`–`f5`, `n5b`, `n6`, `g1`–`g7` pass. Reduced scale this pass (see §2 caveat). |
| **security** | clean | clean | — | 13 prior scripts re-run: snapshot-corrupt fuzz **300 mutations, 0 accepted bad**; RAISE-refusal observability still 1:1 (199/199); chain budget holds under 16 concurrent senders (1 784 delivered); livelock config fuzz **120/120 settled on both engines, 0 RUNAWAY**. `send_threadsafe(internal=True)` forgery unchanged (informational, both kinds). |
| **fuzz** | clean | clean | R9-03 **REFUTED**, R9-06 (Med), R9-09 (Med) | R9-03's starvation claim collapses under a poll-to-drain: **500/500 applied, both queues 0**, both lanes trip `RunawayChainError`. |
| **observability** | clean | clean | R9-11 (Low) | Both prior round scripts re-run verbatim; 7 new attacks (U1–U7) aimed at #192–#199. Reduced matrix (time-boxed, stated in the track). |
| **soak** | clean | clean | — | 11 prior scripts re-run byte-for-byte; 2 new attacks for #192/#195 under load. Chaos soak reduced to 1.5 min/40 machines/3 producers; run twice, clean at a corrected wait bound. |

**The service-kind axis is now flat on every track except R9-04.** That is the headline structural change of this round: rounds 6, 7 and 8 each found the fix landed on only one spelling. Here the only surviving `def`/`async` divergence in the entire corpus is R9-04's roll-forward leak — and one documented, intended one (`def` services are non-preemptable and block their own machine's timers, `production-characteristics.md:93`).

**Time-boxed reductions, stated rather than glossed:** livelock fuzz at N=120 not ≥500; the 12-minute async soak not run; full-scale determinism fuzz not re-derived; the full coverage run unfinished (§2). None sits on a Blocker/High evidence path, and every track states its own reduction in-place.

---

## 4. Contract machines — PASS/FAIL under async AND def

All 20 machines built from the corrected catalogue JSON (byte-compared equal to the `battle-6db65d8` copies before use) and driven end-to-end. Mandatory config on every machine and every interpreter.

| Group | Machines | async | def | Library defects | Ours |
|---|---|---|---|---|---|
| **B1–B5 + B18** | Order, TradeGroup, TradeGroupLeg, OCO, Iceberg, KillSwitch | **138 / 138** | **138 / 138** | 0 | 0 at build time |
| **B6–B10** | 5 order-path machines | **52 / 52** | **51 / 52** | **1 — LD-01 = R9-04** | CD-01 (High, ours) |
| **B11–B15** | RecordingSession, ReplaySession, ExchangeConnection, IngestionPipeline, PaperMatcher | pass | pass | 0 | OUR-B14-d, OUR-B11-d (Med) |
| **B16–B20** | AuthSession, LiveEnablement, KillSwitch, Reconciliation, RiskLockout | pass | pass | 0 — **all LIBRARY-GO** | **C-04, C-07b (Blocker, ours)**; C-05, C-07 (Low) |

**Zero `InvalidConfigError` and zero `ImplementationMissingError` across all 20 on both lanes.** Every machine reached its expected terminal or parked configuration; every invariant held; snapshot/restore at every quiescence point round-tripped with states *and* context matching and **0 spurious `SnapshotMidStepError`**. Sync-engine parity: **15/15** identical configuration, action trace *and* service-call trace.

**The one contract FAIL is R9-04**, and its lane matrix is the finding (re-run fresh this round):

```
ok   case A | async service | async engine | calls=[]
LEAK case A | def   service | async engine | calls=['submit_child']
LEAK case A | def   service | sync  engine | calls=['submit_child']
ok   case B | async service | async engine | calls=[]
ok   case B | def   service | async engine | calls=[]     <- #193's real win
LEAK case B | def   service | sync  engine | calls=['submit_child']
3/6 lanes leaked the service call
```

Case B/`def`/async-engine flipping LEAK→ok is #193 delivering, and it is the dangerous half (a reprice we had already decided had failed). **Under CV-C32 + CV-C46 — `async def` on the async engine, order path never on `SyncInterpreter` — every leaking lane is unreachable for us.** That is what makes R9-04 a constrained-adopt item rather than a blocker.

**The three mandated explicit drives, both lanes:**

1. **rollback + `invoke.onDone`** — **NEEDS-WRAPPER**, unchanged from rounds 7/8. Bounded and observable (1003 calls at default = `maxIterations`+2; 28 at `maxIterations`=25), *identical on both spellings*, trips `RunawayChainError`. Each lap is still a real exchange order, so the wrapper's attempt counter stands.
2. **`always` → invoked child** — passes on B18 (`engaging.always → cancelling`) and B19 (`reporting.always → divergent`), both lanes.
3. **B18 `send_priority` under a self-generated chain** — **12/12 kill presses accepted, 0 shed as `chain_budget`, and the press pre-empts the chain**, both lanes. This is #192 working on the real kill switch, and it is the single most important cell in the round.

**Round-8 provenance holds on the real machines:** a hand-built `DoneEvent("done.invoke.cx", …)` sent at B18 while the genuine `cancel_all_working_orders` is in flight is **refused** with a message naming it engine-generated; the machine does not move.

---

## 5. Surviving defects by final severity

Post-refutation. **0 Blocker · 2 High · 5 Medium · 8 Low.**

### Blocker (0)

**None.** Round 8's R8-01 is closed by #192. R9-01 was refuted down to Low.

### High (2) — both upstream, both mechanically contained

| ID | Title | Containment (ours) | Upstream fix |
|---|---|---|---|
| **R9-02** | `after.*` matched on the **public** `AfterEvent`; a forged `pending_events` record fires a 60 s timer instantly under `strict`, with no API call | **CV-C45** (strip every `DoneEvent`/`AfterEvent` from `pending_events` before restore; reject both at the gateway) — **already mandated**, send-side clause made explicit in §7 | One line: gate `base_interpreter.py:4523` on `_EngineAfter` instead of `AfterEvent` |
| **R9-04** | A `def` service armed by a transition an `always` rolls **forward** is still submitted; `SyncInterpreter` leaks both halves | **CV-C32** (async engine ⇒ every service `async def`) + **new CV-C46** (order path never on `SyncInterpreter`) — together these make all 3 leaking lanes unreachable | Cancel the executor handoff on the `always` roll-forward epilogue; extend #193 to `SyncInterpreter`. Also fix `test_always_rollforward_matches_sync`, which pins the leaking behaviour against the published claim |

### Medium (5)

| ID | Title | Disposition |
|---|---|---|
| **R9-05** | Snapshots are unauthenticated: a *consistent* `configuration`/`state_ids` forgery relocates the machine; a v0/absent-`version` downgrade bypasses the #185 drift check | **DESIGN-CONSTRAINT, downgraded High→Medium.** Documented as intended (`check_identity`); XState v5 `createActor({snapshot})` likewise trusts persisted snapshots; SCXML specifies no persistence model. Exploitation presupposes write access to the snapshot store. **Wrapper obligation stands: HMAC-tag control-plane snapshots, reject `version < 1`.** |
| **R9-06** | A delayed self-`send` cycle is charged to no budget and tagged *external* by #192, so it can never be shed — `maxIterations` inert on that path | Contained by **CV-C42** (no `priority=True` anywhere) + the delayed-send ban under CV-C25. Real, narrow. |
| **R9-07** | `rollback` + `invoke.onDone` storm self-terminates below `maxIterations`, never reports `RunawayChainError`, wedges in the transient invoking state | Contained by the wrapper attempt counter (drive 1 above). Observability gap, not an unbounded run. |
| **R9-08** | `send(wait=True)` resolves with `last_transition_ok=True` at an instant where `current_state_ids == []` | **#197's residual.** Contained by the CV-C06 clause: never read a receipt for configuration. `get_persisted_snapshot()` correctly refuses at the same instant, so nothing torn is persistable. |
| **R9-09** | #201's "all three lanes agree at every limit tested" is false: sync runs exactly two laps more than async at every **odd** `maxIterations` on the `def` lane | **DOC-DEFECT.** Either fix the parity or correct the claim. No runtime consequence for us under CV-C46. |

### Low (8)

**R9-01** (engine-completion forgery via privileged capability — refuted Blocker→Low; doc-note ask for the `_replace` footgun) · **R9-10** (priority lane + #192 tag lost across a snapshot round-trip) · **R9-11** (call-site `QueueOverflowError` refusals fire no `on_event_dropped`; hook under-counts the shed rate ~99.8 %) · **R9-12** (`done.state.*` is an unreserved event namespace) · **R9-13** (`strict` does not gate events restored from `pending_events` — contradicts the documented restore contract; **this is R9-02's delivery mechanism** and rises with it) · **R9-14** (#198 narrows v1 restore compat beyond the changelog) · **R9-15** (`SnapshotMidStepError` from an invoked child's entry action reports `child=False`) · **R9-16** (unknown top-level config keys accepted silently, downgrading policy to defaults — contained by the wrapper key whitelist).

### Refuted outright (1)

**R9-03** — `always` → `invoke` → `onDone` "permanently starves external priority traffic". Every load-bearing claim fails at `f28719c`: the starvation is a measurement artefact of reading a counter after a fixed `sleep(1.0)` (poll to drain: **500/500 applied, inbox 0, priority 0**, `LOST=0`); "silent, no error" is backwards (both lanes now trip `RunawayChainError` — that *is* #179/#201); the ablation table is stale; and the chart is a documented-invalid unguarded `always` targeting its own region, which runs away with **zero** external traffic. Correct usage is 300/300 with queues at zero on both kinds. `54-r9-03-refutation.md`.

### Ours, not the library's (carried, unchanged)

**Catalogue Blockers: C-04** (B16 elevation outlives `LOGOUT`/deadlines and is acquirable after revocation) and **C-07b** (B18 `onUnhandled:"error"` turns a guard-denied `RELEASE` into `UnhandledEventError` — a dead kill switch). **High: C-06, CD-01.** **Medium: CD-02, OUR-B14-d, OUR-B11-d.** **Low: C-05, C-01, C-07.** These gate B16/B18 on **any** runtime and are tracked in E50.

---

## 6. GATE DECISION (per `20-adoption-gate.md` §7)

Applying the decision table in order, first match wins:

| Row | Condition | Status at `f28719c` |
|---|---|---|
| 1 | Any `ERROR` row in gate output | **No.** 143 checks, no ERROR rows; the one PASS→FAIL is a flaky sub-ms latency threshold (4/5 PASS). |
| 2 | Suite fails, or coverage < 86 % | **Not triggered on available evidence.** The one visible suite failure is a too-tight sleep in the library's own test, disproved by polling to convergence (§2a). Coverage did not finish inside the bound — 92.70 % at `6db65d8`, ~51 % of tests observed green here. **Recorded as an open measurement and the first item of §8's recipe.** |
| 3 | Snapshot format changed while LC-21 open | **No.** LC-21 is closed — `version` + `machine_hash` are present and #198 tightened v1. |
| 4 | Any filed **Blocker** repro still exits 1 | **No. The Blocker row is EMPTY.** LC-01, LC-02, LC-03, LC-16 all closed; round-8's R8-01 closed by #192; R9-01 refuted Blocker→Low. |
| 5 | All Blockers closed; **> 5 High** open | **No** — open-High is **2**, against a bar of 5. |
| **6** | **All Blockers closed; 1–5 High open, each with a mechanically enforced mitigation and a passing test in `tests/xstate_contract/`; all Medium triaged** | **MATCH.** |

### → **ADOPT WITH CONSTRAINTS**

**Stated plainly: the order path is open.** For the first time in nine rounds the Blocker row is empty, and the two surviving Highs are each contained by a mechanism we already enforce in code and lint — not by a documented convention, which row 7 explicitly rejects as insufficient. This is row 6, and it applies to **all four lifecycle families**, order path included.

### The load-bearing constraints

Each open High must name its enforcing mechanism and a passing contract test. These two are what carry the decision:

| Open High | Enforcing mechanism | Contract test (must be green in our CI) |
|---|---|---|
| **R9-02** (`after.*` forgeable, incl. via an unauthenticated snapshot record) | **CV-C45** — the restore path strips every `DoneEvent`/`AfterEvent` from `pending_events` before `from_snapshot()`; the gateway rejects any externally submitted event that is an instance of either class. Extended in §7 with an explicit send-side `AfterEvent` clause. | `test_cv_c45_strips_completion_and_after_events` — plants a forged `{"kind":"after","type":"after.60000.m.work"}` record with no `engine` flag in a blob and asserts it is stripped and the timer does **not** fire |
| **R9-04** (rolled-forward `def` invoke still submitted) | **CV-C32** (async engine ⇒ every service `async def`) + **CV-C46** (order path never on `SyncInterpreter`), both linted | `test_cv_c32_no_def_service_on_async_engine`, `test_cv_c46_order_path_engine_is_async` — plus `test_ld01_rollforward_lane_matrix` pinning the 3/6 leak so an upstream fix is *detected* |

Supporting constraints carried from prior rounds and still load-bearing: **CV-C42** (no `priority=True` anywhere — R9-06), **CV-C23/C27′** (snapshot envelope: `version ≥ 1`, `machine_hash`, two-sided configuration agreement, HMAC tag — R9-05), **CV-C06 clause** (never read a `send(wait=True)` receipt for configuration — R9-08), wrapper key whitelist (R9-16), wrapper attempt counter on any `rollback` + `invoke.onDone` state (R9-07, drive 1).

Benchmark-derived constraints **all still apply unchanged** — BENCH-1 and BENCH-2 continue to miss (Budget 1 p95 948.5 ms vs a 300 ms budget, headroom 0.32×; Budget 2 142.9 market ev/s vs 2 000), so the dedicated-loop rule, the ≥99 % pre-filter rule and the external `MonotonicScheduler` rule are mandatory and are the reason §10 retires shims by group rather than wholesale.

### Pin policy

> **`== 0.8.1` once tagged; until then commit `f28719c` + its source sha256.**
> A **vendored copy per MUST-08** is kept in-tree. `__version__` still reports `0.8.0` on this commit, so **no pin may key on the version string** — every pin, CI assertion and gate baseline keys on the commit and hash. The vendored copy is what CI builds against; the pin flips to `== 0.8.1` only when a tag exists whose `__version__` actually reports `0.8.1` and whose tree hash matches what we verified.

### Standing gate

**The contract suite (`tests/xstate_contract/`) enters our CI as a standing, blocking gate**, not a one-off study artefact. It runs on every commit and on a nightly against the vendored copy. It contains: the 20 contract machines end-to-end **on both service spellings**; the three mandated drives; the R9-02 and R9-04 containment tests above; and the lane-matrix pin for R9-04. **Any red cell blocks merge.** This is the mechanism that makes "with constraints" real rather than aspirational, and it is what §10 gates shim retirement behind.

---

## 7. Constraints

### Retired (2)

| Constraint | Why it retires |
|---|---|
| **CV-C43** (order-path liveness must be an out-of-process progress counter, because no in-process detector can see the failure) | **RETIRES as a Blocker mitigation.** Its entire ground was R8-01: a self-issued priority send livelocked the loop thread with `status="running"`, `last_error=None` and no drop hook, so every in-process detector was starved along with it. #192 closes that at the root — verified on both engines and both kinds, and on the real B18 (12/12 kill presses accepted, 0 shed, press pre-empts the chain). **Downgraded to a recommendation, not a mandate:** an out-of-process progress counter remains good operational practice for an OMS, and we keep ours, but it is no longer the *sole* permitted detector and `status`/`last_error` are liveness signals again. |
| **CV-C31″** (no `"rollback"` with a raisable entry action on an `invoke`-carrying state, plain-`def` services only) | **RETIRES.** Its ground was R8-02's residual — a `def` invoke not unwound by `rollback` at all. #193 fixed exactly that on the async engine (case B `def`/async flips LEAK→ok). What survives is the **roll-forward** half, which is a different shape and is carried by R9-04 under CV-C32 + CV-C46. Keeping CV-C31″ would misstate the reason, which is how these constraints rot. |

### Standing (unchanged)

**CV-C01…CV-C22** as amended · **CV-C23** (quiescence-only snapshots via the factory wrapper; envelope always `version ≥ 1` + `machine_hash`; **now also HMAC-tagged** — R9-05) · **CV-C25** (no external `send()` from inside an action; gateway queue only) · **CV-C27′** (two-sided `configuration`/`state_ids` agreement on restore — **weakened in necessity, retained in depth**: #186 is now two-sided itself, so ours is defence in depth rather than the only check) · **CV-C28** (no `LoggingInspector` in production) · **CV-C32** (async engine ⇒ every service `async def`; sync engine ⇒ every service plain `def`) — **now load-bearing for R9-04**, and the reason 2 of the 3 leaking lanes are unreachable · **CV-C33** (`send_threadsafe` only via our gateway) · **CV-C34** (no `"*"` scaffolding) · **CV-C35** (no `always` into an invoked child, no `always` to an ancestor of its own source) — **retained and re-grounded**: R9-03 is refuted, but the chart shape it used is exactly what CV-C35 forbids, and the library documents it as invalid · **CV-C36** (every `send_threadsafe` future read; refusals counted and paged) — retained on R9-11's ground · **CV-C39** (`await start()` always bounded) · **CV-C40** (no snapshot before the post-start settle observation) — **retained in depth**; #199 closed the hook window, so this is now belt-and-braces · **CV-C41** (root-only snapshots; child state via explicit `sendTo`) · **CV-C42** (no `priority=True` anywhere, any origin) — **re-grounded**: R8-01's livelock is fixed, but R9-06 keeps a delayed self-`send` cycle unshedable, so the ban stands on the narrower ground · **CV-C44** (per-child bring-up bounded by us) — **retained in depth**; #194 fixed the library's bound on both lanes, so ours is no longer the only one.

### Widened (1)

| ID | Change |
|---|---|
| **CV-C45** | Was: "the restore path strips every `DoneEvent`/`AfterEvent` from `pending_events` before `from_snapshot()`, and the gateway rejects any externally submitted event whose type is an instance of either class." **Now explicitly extended to the raw-record form and the send side:** the restore filter matches on the **serialised record** (`kind` ∈ {`done`,`error`,`after`}) as well as on the deserialised class, because R9-02's decisive vector is a record with **no `engine` flag** that never passes through a `send()`-time check at all — `_enqueue_restored` (`base_interpreter.py:1768`) puts it straight on the inbox. And the gateway's rejection explicitly names `AfterEvent`, not only the completion classes. **This single constraint contains R9-02 end-to-end** — both the API vector and the snapshot vector. |

### New (1)

| ID | Rule | Enforced by | Covers |
|---|---|---|---|
| **CV-C46** | **The order path never runs on `SyncInterpreter`.** Every order-path machine (B1–B9, B18) is constructed on the async `Interpreter` with an explicitly chosen `service_pool_size`. `SyncInterpreter` is permitted only for non-order tooling, backtests and tests, and never with a side-effecting service. | Factory assertion on interpreter class at construction for any machine in the order-path group, plus a lint on direct `SyncInterpreter(` construction outside the allowed module list, plus `test_cv_c46_order_path_engine_is_async` | **R9-04** (2 of 3 leaking lanes), **R9-09** (sync/async lap divergence is a non-issue if the order path is never sync), and the `167` rollback_reinvoke_spin gate FAIL, which is a `SyncInterpreter`-only behaviour |

**Also promoted to constraint clauses, not new IDs.** Under **CV-C23**: control-plane snapshots carry an **HMAC tag** verified before `from_snapshot()`, and any payload declaring `version < 1` or omitting `version` is refused outright — this closes R9-05 on our side without depending on the library, which documents v0-unchecked as intended. Under **CV-C06**: a `send(wait=True)` receipt is never read for configuration; read the configuration separately at quiescence (R9-08). Under **CV-C25**: a chain-budget trip is invisible to the caller, so the gateway correlates its own send with `on_event_dropped` rather than with the receipt, **and counts call-site `QueueOverflowError` refusals itself** since the hook under-reports them by ~99.8 % (R9-11). Under **CV-C01** (wrapper build): the wrapper **whitelists top-level config keys** and fails the build on an unknown one, since the library accepts a typo silently and downgrades to the default (R9-16).

### FINAL mandatory configuration block

```jsonc
{
  // --- error handling -------------------------------------------------
  "actionErrorPolicy": "rollback",   // DEFAULT, all non-order machines.
                                     // CV-C31" RETIRES: #193 unwinds a `def` invoke on
                                     // rollback on the async engine (case B def/async
                                     // flips LEAK -> ok). The ROLL-FORWARD half is still
                                     // open (R9-04) but is a different shape, carried by
                                     // CV-C32 + CV-C46, not by a policy ban.
                                     // Wrapper attempt counter still REQUIRED on any
                                     // rollback + invoke.onDone state: bounded at
                                     // maxIterations+2, but each lap is a real order,
                                     // and R9-07 can wedge without RunawayChainError.
  "actionErrorPolicy": "fail",       // ORDER-PATH states with invoke + raisable entry.
                                     // #145 still verified: halts with status="stopped",
                                     // configuration cleared, TransitionFailedError
                                     // retained, halted blob refused by from_snapshot.
                                     // Pair with an explicit `halted` state entered from
                                     // on_transition_failed - C-07: STILL MISSING on
                                     // B16-B20 (E50-T16, ours).

  "guardErrorPolicy": "raise",       // #152 + #170: cancels only the FAILING candidate;
                                     // the unguarded fallback is still taken; the
                                     // (denied, error, deferred, changed) matrix is
                                     // INJECTIVE. W-04a retired. W-04b stands: `defer`
                                     // outranks guard_denied, so denied events must be
                                     // drained from the buffer.

  "onUnhandled": "defer",            // order path. No "*" scaffolding (CV-C34).
                                     // Authorisation/risk events are non-deferrable (W-03).
  "onUnhandled": "error",            // control machines ONLY, and NOT on B18 - C-07b:
                                     // a guard-denied RELEASE is terminal, i.e. the kill
                                     // switch is bricked by a wrong press. OURS, Blocker,
                                     // open four rounds (E50).
                                     // #189 FIXED: the fatal kill is visible on the
                                     // sender's Receipt.error on both engines.

  "strictTargets": true,             // #147: RootTargetError at build time, non-downgradable.
  "strict": true,                    // #190/#195: config-level strict is inherited; a "*"
                                     // handler no longer defeats it; hand-built Done/Error
                                     // events are refused on both engines/both kinds.
                                     // TWO RESIDUALS, both ours to contain:
                                     //  - strict does NOT gate events restored from
                                     //    pending_events (R9-13) -> CV-C45 strips them.
                                     //  - `after` is matched on the PUBLIC AfterEvent
                                     //    class (R9-02, High) -> CV-C45 covers both the
                                     //    send side and the raw snapshot-record side.
                                     // R9-16 stands: a TYPO in any top-level key is still
                                     // accepted silently -> the wrapper whitelists keys.
  "maxIterations": 500,              // LIVE and lane-independent. Verified this round by
                                     // polling to convergence: rollback+onDone plateaus at
                                     // EXACTLY maxIterations+2 on BOTH lanes (1003/1003;
                                     // `def` converges ~1.0s, async <0.5s). The library's
                                     // own test reads at 0.6s and so fails spuriously -
                                     // that is a test bug, not a bound failure.
                                     // ONE residual inertness: a DELAYED self-send cycle
                                     // is charged to nothing and tagged external by #192,
                                     // so it can never be shed (R9-06) -> CV-C42.
  "spawnBlockingTimeout": 5000       // Validated then dropped - no attribute on MachineNode,
                                     // so a conformance lint cannot assert it post-build.
                                     // Whitelist top-level keys in the wrapper (R9-16).
}
```

```python
# Runtime construction - mandatory (round 9)
MachineLogic(strict=True)             # W-01: create_machine is NOT a conformance gate; the
                                      # wrapper cross-validates the logic table against JSON.
Interpreter(..., max_queue_size=64, overflow_policy=OverflowPolicy.RAISE,
            service_pool_size=<explicit>)   # default is 4. DC-1: SyncInterpreter accepts
                                      # NEITHER max_queue_size NOR overflow_policy.

# ENGINE:   the ORDER PATH (B1-B9, B18) runs on the async Interpreter ONLY - NEVER on
#   SyncInterpreter (CV-C46, NEW). 2 of R9-04's 3 leaking lanes are sync-engine lanes,
#   and the `167` rollback_reinvoke_spin gate FAIL is sync-only.
# Services: async def ONLY on the async engine (CV-C32). Blocking work via asyncio.to_thread.
#   Load-bearing for R9-04: a plain `def` service armed by a transition an `always` rolls
#   FORWARD is still submitted (production-characteristics.md:97 promises otherwise).
#   A `def` service also remains non-preemptable and blocks its own machine's `after`
#   timers (#174, documented, unchanged).
# Entry actions on invoke-bearing states: async def, yielding at least once (CV-C44).
#   #194 now bounds each child AND always logs the overrun WARNING on both lanes, so
#   CV-C44 is defence in depth rather than the only bound.
# start():  ALWAYS asyncio.wait_for(start(), CV_START_TIMEOUT) - never bare (CV-C39).
# Snapshot: factory wrapper only; at quiescence (CV-C23); ROOT ONLY, child state via
#   explicit sendTo (CV-C41). CV-C40 retained in depth (#199 closed the hook window).
#   Never read a send(wait=True) receipt for configuration (CV-C06 clause, R9-08).
# Restore:  our envelope writes version>=1 + machine_hash + an HMAC TAG, and the restore
#   path VERIFIES THE TAG and refuses version 0/absent before from_snapshot (R9-05);
#   assert configuration/state_ids agree BOTH ways (CV-C27', in depth since #186);
#   STRIP every done/error/AFTER record from pending_events - matching the SERIALISED
#   record kind, not just the class, because R9-02's vector carries no "engine" flag and
#   never passes a send()-time check (CV-C45, WIDENED - contains R9-02 end-to-end).
# Sends:    gateway only; priority=True forbidden EVERYWHERE, any origin (CV-C42, R9-06);
#   every send_threadsafe future is read (CV-C33/C36); the gateway counts call-site
#   QueueOverflowError refusals ITSELF - on_event_dropped under-reports by ~99.8% (R9-11).
# Health:   status/last_error are liveness signals AGAIN (CV-C43 retired as a mandate -
#   #192 closed the livelock that starved every in-process detector). We keep the
#   out-of-process progress counter as recommended practice, no longer as the sole detector.
```

---

## 8. Release-readiness note for the team (before tagging 0.8.1)

**This is the round the library earned its tag.** Round 8's single Blocker is closed at the root, eleven of twelve issues hold on re-verification, the service-kind axis is flat across every battle track for the first time in four rounds, and the two surviving Highs are each one branch of one function. Said plainly: **`f28719c` is tag-worthy, and three small things would make the tag clean.**

1. **Land R9-02 first — it is one line.** `base_interpreter.py:4523` selects `after` transitions on `isinstance(event, AfterEvent)` against the public exported class; the `DoneEvent`/`ErrorEvent` branch eight lines below already consults `is_system_event`. Gate `:4523` on `_EngineAfter` and the whole finding evaporates — including the snapshot vector, which is the one that needs no API call. #195 built this exact mechanism in this exact release; the `after` family was simply never switched over to it.
2. **Bump `__version__` in the same commit that tags.** **Nine** verification rounds have now keyed on commits because `__version__` reports `0.8.0` on a tree whose CHANGELOG describes 0.8.1. If the tag ships with the string still wrong, the commit-keyed escape hatch survives into a *released* artefact, which is far worse than needing it pre-release.
3. **Fix the two tests that are actively misleading.** `test_round8_findings.py::test_always_rollforward_matches_sync` **pins the leaking behaviour as the contract** while `production-characteristics.md:97` and the CHANGELOG promise the opposite — so the green suite certifies the inverse of the published claim, and R9-04 got through because of it. And `test_round6_findings.py::TestAsyncRollbackRearmCycleBounded` reads its counter at 0.6 s when the `def` lane converges at ~1.0 s; it fails ~80 % of runs on a normal host while the behaviour it tests is **correct** (plateau 1003 = `maxIterations`+2 on both lanes, §2a). A test that fails on correct behaviour trains people to ignore the suite; a test that passes on the defect it names closes the issue falsely. **Both failure modes are in this release at once.**

**Round 9's generalisable lesson, and it is a different one from rounds 6–8.** Those rounds each said "parametrise over the axis the defect lives on" (engine, then service kind, then issuer provenance). Round 8 did that, and it worked — that is why this round is clean. **The lesson this round is: when you build a trust mechanism, enumerate every call site it is supposed to govern and assert the list is exhausted.** #195 minted `_EngineDone`, `_EngineError` *and* `_EngineAfter`, wired two of the three into `_select_transitions`, and shipped. A three-line test that asserts every `isinstance(event, <public engine class>)` in `base_interpreter.py` is paired with a provenance check would have caught R9-02 at authoring time — and would catch R9-12 (`done.state.*`) too.

**Also worth landing before the tag, in rough value order:** R9-04 (cancel the executor handoff on the `always` roll-forward epilogue; extend #193 to `SyncInterpreter`); R9-13 (make `strict` gate restored `pending_events` — this is R9-02's delivery mechanism and the two fixes reinforce each other); R9-08 (`send(wait=True)` should not report success over an empty configuration — `get_persisted_snapshot()` already refuses at the same instant, so the correct behaviour is already written down elsewhere in the same file); R9-09 (fix the parity or correct the claim); R9-06, R9-07, R9-10, R9-11, R9-14, R9-15, R9-16 — all small, all independently reproduced, all with standalone repros attached in `issues/post-f28719c/`.

**Measurements we owe and did not make, stated rather than glossed:** the full suite + coverage total (unfinished at ~51 %); `bench_c_timers` and `bench_e_actors` (not completed); the ≥500-config livelock fuzz (run at N=120); the 12-minute soak (reduced to 1.5 min). And the **RSS/open-order figure remains unbisected for a third round** — it read 3.10 KB at round 7, 5.18 KB at round 8, **2.128 KB here**. Three readings spanning 2.4× on a single-sample RSS delta over a ~1 MB population is not a trend, it is an unfit measurement. **Either bisect it properly or replace the metric**; a third shrug is not acceptable on a figure that gates BENCH-4.

---

## 9. What would change the verdict

### Downward — what would turn ADOPT WITH CONSTRAINTS back into DEFER

1. **A contract-suite red cell.** The suite is the mechanism the constraints rest on; if it cannot run green in CI on both service spellings, "with constraints" is unenforceable and row 6 collapses to row 7 (DEFER — a documented convention is not a mitigation).
2. **Coverage coming back below 86 %** when the full run finally completes, or a genuine suite failure among the ~49 % of tests not observed this round. This is the one *measurement* that could move the verdict, which is why it leads §8's recipe — row 2 fires before row 6 is ever reached.
3. **Evidence that CV-C45 does not actually contain R9-02** — e.g. a vector that reaches the `after` selection site without passing through either the gateway or `_enqueue_restored`. That would leave a High with no mechanical mitigation, which is row 7.
4. **A 0.8.1 tag cut with `__version__` still reporting `0.8.0`**, or with `test_always_rollforward_matches_sync` still pinning the leak. Neither is a library defect in itself; both would tell us the release process does not check its own claims, which changes how much weight the CHANGELOG can carry in round 10.
5. **A third round of "fixed on one axis only."** R9-02 and R9-04 are each the *second* incomplete landing of the same fix (#195, #193). A third would stop being a bug pattern and start being a process signal.

### Upward — what would turn this into unconstrained ADOPT

**Row 9 needs all Blocker and High closed, all Medium triaged, and all benchmark thresholds met.** Concretely: land **R9-02** (one line) and **R9-04**, and the High row clears — that is row 8, **ADOPT with the benchmark-derived constraints only**, which is a materially lighter regime: CV-C45's send-side clause and CV-C46 would both retire, and CV-C32 would fall back to a performance preference rather than a safety rule.

Row 9 additionally needs **BENCH-1 and BENCH-2**, and those are **not close** — Budget 1 is at 0.32× headroom (948.5 ms p95 against a 300 ms budget) and Budget 2 at 142.9 market events/s against 2 000. Those are architectural gaps of roughly 3× and 14×, not tuning gaps. **We should not expect row 9, and should not plan for it**: the dedicated-loop rule, the ≥99 % pre-filter and the external `MonotonicScheduler` are permanent features of our design, not temporary mitigations. The honest ceiling for this library in our system is **row 8**.

**Re-verification recipe for round 10 (~45 min, in priority order):**

```
# 1. THE OWED MEASUREMENT - run first, it can move the verdict by itself
pytest tests/ --cov=src --cov-report=term          # full total + coverage >= 86%

# 2. The two Highs
battle-f28719c/r9triage/t3_snapshot_after.py       # R9-02: MUST NOT reach m.expired
battle-f28719c/r9triage/t1_plain_event_control.py  # R9-02: discriminating control
battle-f28719c/contracts/repro/ld01_always_rollforward.py   # R9-04: MUST be 0/6 leaks

# 3. Regression + containment
gate/run_gate.py                                   # now incl. verify-main-f28719c
tests/xstate_contract/                             # the standing gate, BOTH spellings
battle-f28719c/r9triage/t_r6_plateau.py            # bound still maxIterations+2, both lanes

# 4. The owed benchmarks
bench_c_timers (incl. load_500) ; bench_e_actors
bench_h - BISECT the KB/order figure across 6db65d8..f28719c, or replace the metric
```

---

## 10. Next steps — ADOPT, so: phased shim retirement

The shims exist because the library could not be trusted on a given behaviour. Each retires **only** when the contract suite covers what the shim was protecting, green on **both service spellings**, for a full nightly cycle. **The order path goes last, and it goes behind the contract suite.**

### Phase 1 — non-order, immediate (B10–B15, B17, B19, B20)

Retire: the **`always`-ordering shim** (#196 closed it; `always` never steals a named event, 200/200 both engines/kinds), the **`children_timeout` wrapper bound** as a *mandate* (#194 bounds per child and always warns on both lanes — CV-C44 stays as defence in depth), the **one-sided-agreement restore check** as the primary gate (#186 is two-sided now; CV-C27′ stays in depth), and the **`on_interpreter_start` snapshot guard** as the primary gate (#199 closed the window; CV-C40 stays in depth). **Precondition:** contract suite green in CI on both spellings for one nightly.

### Phase 2 — control plane (B16, B18) — blocked on US, not the library

Both are **LIBRARY-GO**. What blocks them is **C-04** (B16 elevation outlives revocation) and **C-07b** (B18 `onUnhandled:"error"` bricks the kill switch on a guard-denied `RELEASE`) — our catalogue Blockers, open four rounds, and they block on *any* runtime. Fix the catalogue, then retire the control-plane shims. **No library dependency whatsoever.**

### Phase 3 — order path (B1–B9, B18), LAST and gated

Retire order-path shims **only** when all four hold: (i) contract suite green on both spellings for **five consecutive nightlies**; (ii) CV-C45 (widened), CV-C32 and CV-C46 enforced by lint **and** covered by their named tests; (iii) the coverage measurement from §8 completed at ≥ 86 %; (iv) a **canary**: one low-notional order machine group in production behind the full constraint set for two weeks with zero constraint-test failures. **CV-C42, CV-C23's HMAC clause and the wrapper attempt counter do not retire in this phase** — they answer R9-05/R9-06/R9-07, which are Medium and still open.

### E50 backlog

**Close (round-8 residuals now verified fixed upstream):** the guard tickets for R8-01 (priority-lane livelock — #192), R8-03 (`children_timeout` no-op — #194), R8-08 (one-sided agreement — #186), R8-09 (`on_interpreter_start` torn snapshot — #199), R8-10 (`_chain_owed` leak — #200), R8-11 (lap parity — #201). Also close the **CV-C43** out-of-process-liveness *mandate* ticket (retired to recommendation) and the **CV-C31″** lint ticket (retired).

**Add:**
- **CV-C46** factory assertion + lint + `test_cv_c46_order_path_engine_is_async` (R9-04)
- **CV-C45 widening**: match serialised record `kind`, name `AfterEvent` on the send side, + `test_cv_c45_strips_completion_and_after_events` (R9-02)
- **`tests/xstate_contract/` into CI as a blocking gate**, both spellings, nightly (the mechanism §6 rests on)
- **HMAC-tag control-plane snapshots + refuse `version < 1`** (R9-05)
- Gateway counts call-site `QueueOverflowError` refusals itself (R9-11)
- Wrapper top-level config-key whitelist (R9-16)
- `test_ld01_rollforward_lane_matrix` pinning 3/6 so an upstream fix is **detected** (R9-04)
- Shim-retirement tickets, one per phase above, with their preconditions as acceptance criteria
- **X01 verdict recorded: ADOPT WITH CONSTRAINTS**, pin `== 0.8.1` once tagged / commit `f28719c` + sha256 until then, vendored per MUST-08

**Keep open (ours, unchanged and now the critical path):** **C-04** and **C-07b** — the only Blockers of any kind left in this study, and both are ours. Nine rounds of library verification have arrived at a state where **the binding constraint on our order path is our own catalogue, not the library.** That is the right problem to have, and it should be the next thing worked.
