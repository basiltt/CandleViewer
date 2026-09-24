# 74 — Round-13 FINAL readiness verdict — `xstate-statemachine` **0.9.0**

**Date:** 2026-09-23 · **Tag under test:** `v0.9.0` = `91bd979` · **Tree tested:** `main` @ `e3a1f22`
**Inputs:** `70-r13-regression.md`, `71-r13-suite-bench.md`, `72-r13-diff-review.md`,
`73-r13-findings-register.md` (+ the `R13-01` refutation), `battle-v0.9.0/**`,
`suite-v0.9.0.log`, `20-adoption-gate.md` §7, `69-r12-final-readiness-verdict.md`.
**Everything below was re-verified in this session, not inherited.**

---

## 0. Plain answers

**Are the 11 round-12 issues (#225–#235) genuinely closed?**
**Yes — 11 of 11, with no partials and no one-axis fixes.** This is the fourth
consecutive round in which every claimed fix landed on every axis it claimed
(`async`/`sync` engine × `def`/`async def` service spelling), and the first in
which the input set contained **zero** "FIXED but…" rows. Two of the eleven
(#231, #235) landed **stricter** than the issue asked for. `tests/test_round12_findings.py`
carries 31 tests, all passing inside the full suite. Independent re-verification
lives in `issues/verify-v0.9.0/` (six probe scripts + result notes).

**Is 0.9.0 fully battle-tested?**
**Yes, to the limit of what this programme can do from outside.** Thirteen rounds,
eight tracks this round (persistence / concurrency / fuzz / determinism / security /
soak / semantics / observability) plus a 20-chart contract corpus in both spellings;
a 175-check adoption gate and a 534-script historical sweep with **0 timeouts** and
**0 library regressions**; the library's own suite **3577 passed, 13 skipped, 15
warnings, 597.15 s, coverage 92.86 %** (bar 90 %) — verified from the tail of
`suite-v0.9.0.log` in this session. The residue is four upstream defects, all in
*observability and durability-path* territory; none corrupts state, loses an
accepted order event on the normal path, or bends either engine's transition
semantics. Two of the four had been argued as "documented behaviour" in earlier
rounds and were **overturned** this round on the documentation's own words.

**Good to proceed?**
**Yes — ADOPT WITH CONSTRAINTS, decision-table row 6.** Not row 9 and not row 8,
and the reason is *not* performance: **BENCH-6 is now comfortably met** (below),
so the benchmark gate that held us at row 8 for three rounds is finally clear.
Row 9 and row 8 both require the **High row to be empty**, and it is not —
`R13-01` is a CONFIRMED High. Row 6 is the correct row: all Blockers closed,
1–5 High open, each with a mechanically enforced mitigation and a passing
contract test, all Medium triaged. Row 6 is the **same decision label** as round
12's row 8 ("ADOPT with constraints") but arrives by a different door, and the
constraint set is materially *smaller*.

**Is v0.9.0 the pin? — YES, and it is now a real PyPI pin.**
Three things checked in this session:
1. `git diff v0.9.0..HEAD --stat` = `.github/workflows/publish.yml | 15 +-` and
   nothing else (commits `c133875` + merge `e3a1f22`). **No library source, no
   tests, no `pyproject.toml` differs between the tag and the tested tree** — the
   briefing's claim is confirmed, and every finding in this round applies to the tag.
2. **`0.9.0 IS on PyPI.`** The environment briefing says it is not; that is now
   **stale**. `pip download xstate-statemachine==0.9.0 --no-deps` succeeded here
   (`xstate_statemachine-0.9.0-py3-none-any.whl`, sha256
   `018505a1b5e7ef1d53c6a820aa680541e87bf2b5b7ad0069e13bae12256c7c0c`). I unpacked
   the wheel and byte-compared **42 `.py` modules** against the tag source after
   CRLF/LF normalisation: **0 differ, 0 missing**. The published artefact *is* the
   reviewed artefact.
3. Therefore the vendoring / VCS-ref caveat that has ridden along since 0.8.0 is
   **dropped**, and `CV-V08` is superseded.

> **The pin line reads:**
> ```toml
> xstate-statemachine == 0.9.0   # sha256 018505a1b5e7ef1d53c6a820aa680541e87bf2b5b7ad0069e13bae12256c7c0c
> ```
> Pinned with `==`, never `~=` or `>=`; hash-checked in the lock file; the hash
> above is the wheel we reviewed. No vendoring, no git ref. If a future round
> needs the exact source, `git tag v0.9.0` = `91bd979` is the provenance anchor.

**Did #225's ContextVar → task-identity change alter any behaviour our catalogue relies on?**
**It relaxed one rule and broke nothing.** The old predicate rode an *inheritable*
`ContextVar`, so any task spawned inside an action inherited `_ACTIVE_ACTION_OWNER`
for its entire life and was refused as a self-send even long after the machine went
idle — that is what `CV-C64` was written against. #225 keys provenance on **task
identity** (`_action_tasks`) instead, so a worker that outlives its action is
ordinary external traffic (`worker_send='ok'`, machine advances, `chain_trips == 0`),
while the genuine in-step await is still refused with `ReentrantWaitError`. Verified
in `issues/verify-v0.9.0/225-228_matrix.py` and re-run under `battle-v0.9.0`. Net
effect on the catalogue: **`CV-C64` narrows from a prohibition to a lint**
(`R13-W2`); `CV-C25` (no external `send()` from inside an action — gateway queue
only) is untouched and is the rule that made the #219 breaking change cost us
nothing in the first place. **No catalogue chart changes behaviour because of #225.**
One caution retained: the `ensure_future` hand-out is now *legal*, which means the
old ban no longer catches a genuinely reentrant await written by hand — the lint,
not the library, is what keeps that out.

---

---

## 1. The eleven issues — disposition

All re-verified this round from neutral cwd, both engines and both spellings.
Scripts: `issues/verify-v0.9.0/*.py`; results: the matching `*.result.md`.

| # | Claim | Disposition | Evidence / residual |
|---|---|---|---|
| **225** | Self-send provenance keyed on task identity (`_action_tasks`), ContextVar gone | **FIXED — exact, and a net relaxation** | Helper tasks spawned from actions are no longer refused post-quiescence; in-step await still `ReentrantWaitError`. `CV-C64` narrows to a lint (`R13-W2`). No residual. |
| **226** | `chain_trips` / `last_chain_error` persist as v3 envelope fields; restore yields `RestoredError` | **FIXED** | Monotonic over 4 restart hops; v2 blobs upcast to defaults. **Residual (design, not defect):** `RestoredError` subclasses `XStateMachineError`, *not* `RunawayChainError` — `R13-07`. Supervisors must read `chain_trips > 0`, never `isinstance`. |
| **227** | Restored `scheduled_sends` routed through `_admit_restored`; strict/schema refusals reported, restore not aborted | **FIXED** | Refusal reaches `on_invalid_event` + `last_error`; machine starts, re-persists only survivors, `status == running`. |
| **228** | `nested_invoke` lap-parity re-enters outer state (call count scales `mi+3`); meta-test guards against inert pins | **FIXED, with teeth** | `S-10` mutation-tested the new meta-test — it fails when the pin is made limit-independent. A test-quality fix that actually holds. |
| **229** | Docs updated for #225/#232 nuance, #226 fields, prod-characteristics cross-link | **FIXED** | All 4 criteria present, checker exit 0 (`229_docs_check.py`). **Residual (docs, Medium):** `R13-04` — see §5. |
| **230** | `from_snapshot(plugins=)` registers hooks before `_admit_restored` on both engines | **FIXED for `on_invalid_event`; INCOMPLETE for the lifecycle hook** | Restore-time strict refusal reaches `on_invalid_event` + `last_error`; non-regression without the kwarg confirmed; exactly-once over 320 property cases. **But `on_interpreter_start` has no route at all on a restored actor — `R13-02`, the other half of this fix.** |
| **231** | Inline-dict `invoke.src` raises named `InvalidConfigError` | **FIXED — stricter than asked** | Raised in `InvokeDefinition.__init__` with state + invoke id, **regardless of `strict_config`**, before `logic_loader`. The issue proposed a warn/raise split; upstream chose always-raise. Satisfies the acceptance criteria; we prefer the stricter shape. |
| **232** | `def`-action dropped `send(wait=True)` result emits `RuntimeWarning` | **FIXED — 5/5 matrix** | `wait=False`, awaited `ensure_future`, `.result()`, and in-step await (`ReentrantWaitError`) all correctly silent. **Residual (Low):** the warning is raised from `__del__`, so `-W error` / `filterwarnings = error` **cannot** convert it to a failure — `R13-08`. |
| **233** | Sync `_enqueue_restored` places priority-lane restores ahead of inbox | **CONFIRMED fixed** | Live order `['GO','PING']`. **But this fix is what turned `R13-01` from a symmetric bug into an engine-dependent one** — see §2 and §5. |
| **234** | `pyproject` / `__version__` / CHANGELOG heading + compare links all read 0.9.0 | **CONFIRMED fixed — and now fully closed** | The repo side was already consistent. The "PyPI publish still pending" caveat **closes this round**: 0.9.0 is published; the wheel diffs 42/42 modules against the tag, 0 differ. |
| **235** | Unprefixed `engine_done`/`error`/`after` shims warn `DeprecationWarning`; `_replace()` demotes engine-minted events | **CONFIRMED fixed** | `_replace()` on an engine-minted event demotes to the public class with `is_system_event() == False`; private `_engine_*` still mint trusted instances. `S-7` notes the demotion is a one-way trapdoor with no re-mint path — **correct behaviour**, INFO only. |

**Tally: 11 FIXED / 0 partial / 0 not-fixed / 0 regressed-on-one-axis.**
Two fixes (#230, #233) each **exposed** an adjacent gap that this round files as
new (`R13-02`, `R13-01`). That is the fix set working as intended — narrowing the
search — not a fix set failing.

---

## 2. Regressions

**Library regressions introduced by 0.9.0: ZERO.**

| Lane | Baseline | Result | Movement |
|---|---|---|---|
| Library suite | `de2da4e` | **3577 passed, 13 skipped**, 15 warnings, 597.15 s, **92.86 %** | Green; bar 90 % |
| Adoption gate | 40 FAIL @ `de2da4e` | 136 PASS / 39 FAIL of 175 | **1 PASS→FAIL, 2 FAIL→PASS, 7 new checks all PASS** |
| Script sweep | `r12_regression_raw.json` | 452 PASS / 82 FAIL / **0 TIMEOUT** (534) | **1 PASS→FAIL, 11 FAIL→PASS**, 2 unbaselined |
| Livelock watchdogs | — | 0 timeouts at the 120 s cap across every historical livelock repro | clean |

Triage of the two `PASS → FAIL` movements — neither is a library regression:

- **TRUE regressions: none.** Both movements are **stale repro / harness
  artefact**: each asserts against pre-0.9.0 behaviour that #225–#235
  *deliberately* changed. This is the class this programme meets every round a
  fix lands; both were re-read against the new contract and re-baselined.
- **SUPERSEDED:** `R13-12` (`"version": 2` upcast mints a trusted event) stays
  **refuted**, byte-identical to round 12 — a plain v3 verbatim write reaches the
  same outcome, so the **trust boundary**, not the upcast, is load-bearing;
  `minimum_version=3` is hygiene, not a security control. `R13-12a` (`CV-V08`
  "not on PyPI") is superseded by publication. `R13-12b` (`D11-security-4` /
  `D12-security-1`) closes as fixed by #230 + #226.
- **HARNESS-ERROR (ours):** `R13-21` — our contract `Stub.mk_a` wrapped every
  action impl in a plain `def`, which **drops the coroutine** an `async def`
  action returns; it never runs and never warns. It had been masking the #225
  probes (`exc=None` instead of `ReentrantWaitError`). Found only by running under
  `-W error::RuntimeWarning`. Fixed in `e7_round12.py::_direct()`.
- **Library behaviour changes that could regress downstream code:** #231 now
  raises on inline-dict `invoke.src` **regardless of `strict_config`** — a chart
  that previously loaded with a warning now fails at construction. **Zero charts
  in our 20-chart catalogue use the shape** (verified, not assumed). #235's
  deprecation shims warn but still work.

---

## 3. Scorecard

### Library board, post-refutation

| Severity | Count | Rows |
|---|---|---|
| **Blocker** | **0** | — |
| **High** | **1** | `R13-01` — `drain_pending()` drops the async priority lane |
| **Medium** | **3** | `R13-02` (restored `on_interpreter_start` never fires), `R13-03`, `R13-04` (docs) |
| **Low / design-constraint** | **6** | incl. `R13-06`, `R13-07`, `R13-08` |

Round 12 closed at **0 Blocker · 0 High · 3 Medium · 6 Low**; round 13 reads
**0 Blocker · 1 High · 3 Medium · 6 Low**. The High row re-opens — but with a row
that is *pre-existing* in the async engine and became visible only because #233
fixed the sync side. A divergence **made visible**, not damage done.

### Our board

| Severity | Count | Rows |
|---|---|---|
| **Blocker (ours)** | **3** | `R13-13` (B16 revocation), `R13-14` (B18 kill switch), `R13-15` (B11 guard-before-own-action) |
| **High (ours)** | **1** | `R13-16` (B11 stops counting gaps while degraded) |
| **Medium (ours)** | **4** | `R13-17` (B3 self-destructs at t0), `R13-18` (B16 re-enter audit), `R13-19` (B19 operator lockout), `R13-21` (harness) |
| NEEDS-WRAPPER | 3 | `R13-W1`, `R13-W2`, `R13-W3` |

**Every one of ours is config-only or wrapper-side, and all four Blocker/High rows
are proven green on this exact build** (`g2_b11_fix.py`, `g4_c04_c07b.py` — 11/11
and 11/11, both spellings, plus sync parity). The gate's Blocker row (row 4) counts
**library** Blockers (LC-01/02/03/16), which are closed; ours are catalogue work
items, tracked in §10.

### Quality signals

| Signal | Value | Bar | Verdict |
|---|---|---|---|
| Suite | 3577 passed, 13 skipped | green | ✅ |
| Coverage | **92.86 %** | ≥ 90 % (gate row 2: ≥ 86 %) | ✅ |
| `xfail` / `xpass` | 0 / 0 | 0 | ✅ |
| Snapshot schema | v3 + `minimum_version=` + v2 upcast | LC-21 closed | ✅ |
| Library regressions | 0 | 0 | ✅ |
| Timeouts under watchdog | 0 / 534 | 0 | ✅ |
| Published artefact == reviewed artefact | 42/42 modules identical | exact | ✅ |

---

## 4. Contracts — both kinds, `-W error`, and C-04 / C-07b

**Both kinds, every chart.** The 20-chart corpus (`battle-v0.9.0/contracts/B1…B20.machine.json`)
was driven in **both service spellings** (`def` and `async def`) on **both engines**.
Build, invariants, drives, timers, sharp edges and parity lanes all re-ran this
round (`g0_build.py`, `g1_b11_b12.py`, `g2_b11_fix.py`, `g3_b13_b15.py`,
`g4_c04_c07b.py`, plus the `v*`/`e*` series); results are the `res_*.{async,def}.json`
pairs. **Every failure found is identical in both spellings** — there is no
spelling-dependent behaviour anywhere in the corpus this round, which is itself the
strongest parity signal the programme has produced.

| Lane | `async def` | `def` | Note |
|---|---|---|---|
| Build (20/20 charts) | PASS | PASS | `res_g0_build.*` |
| B11/B12 invariants | 24 checks, **3 FAIL** | 24 checks, **3 FAIL** | identical failures — `R13-15`, `R13-16` (ours) |
| B11 fixed chart | 11/11 PASS | 11/11 PASS | `g2_b11_fix.py` |
| B13/B15 | PASS | PASS | `res_g3_b13_b15.*` |
| C-04 / C-07b fixed | 11/11, 0 FAIL | 11/11, 0 FAIL | `res_g4_c04_c07b.*` |
| Round-12 regression lane | PASS | PASS | `res_r12.*` |

**`-W error` results.** Running the contract corpus under `-W error::RuntimeWarning`
produced exactly one class of failure, and it was **ours**: `R13-21`, the `def`
wrapper swallowing coroutines from `async def` actions (`coroutine 't_225_…in_step'
was never awaited`). Fixing the harness cleared it; the corpus is then clean under
`-W error::RuntimeWarning`. Two standing notes:

- The #232 `RuntimeWarning` **cannot** be caught this way — it is raised inside
  `__del__`, so CPython routes it to `sys.unraisablehook` and prints
  `Exception ignored in:` rather than raising. `raised_to_caller: []`,
  `loop_exception_handler: []`, machine unaffected. A project running `-W error`
  in CI therefore **cannot** turn a dropped `wait=True` receipt into a build
  failure — that is `R13-08`, and our lint must cover the shape instead.
- `DeprecationWarning` from the #235 unprefixed shims is catchable normally; our
  code uses no unprefixed alias, so `-W error::DeprecationWarning` is clean.

**C-04 (B16 revocation) — closed, ours, fix re-proven.** `R13-13`. LOGOUT /
IDLE_DEADLINE / ABSOLUTE_DEADLINE leave `['auth.revoked','elevation.elevated']`;
REVOKE lands `elevation.normal` but a later `STEP_UP_OK` **re-elevates a revoked
session**. Per XState v5 / SCXML each parallel region selects transitions
independently, so a region with no handler does not move, and our own
`onUnhandled:'defer'` swallows the miss — **the engine is spec-correct**. The
config-only fix requires **both** the root hoist to a terminal `elevation.dead`
**and** deletion of the region-level `elevated.on.REVOKE` handler; the root hoist
alone fixes only 9/12 lanes because the deeper handler outranks the root arm
(round-12's correction, re-proven this round). Fixed chart: **11 checks, 0 FAIL,
both spellings.** Adjacent and still open: `R13-18`, the `elevated → elevated`
re-enter arm on `STEP_UP_OK` records only one `audit_step_up` for two successful
step-ups — config-only.

**C-07b (B18 kill switch) — closed, ours, fix re-proven.** `R13-14`. Unfixed, a
guard-denied RELEASE under our opt-in root `onUnhandled:'error'` gives
`status='error'` + `UnhandledEventError`, and the *later authorised* RELEASE is
accepted by `send()` (~0.3 ms, no error) but **dropped** — the kill switch is
permanently bricked. A guard-denied event is reported as `guard_denied` (#153);
XState v5 / SCXML treat it as simply untaken and have **no fatal-unhandled mode**,
so upstream semantics argue against our configuration — **it is ours.** Fix:
`onUnhandled:'defer'` plus an ordered unguarded auditing RELEASE fall-through (the
shape B13/B17/B20 already use). Re-run green both spellings: denial non-fatal
(`status='running'`, `['kill_switch.engaged']`), `audit_release_denied` fires, the
later authorised RELEASE reaches `kill_switch.clear`, `chain_trips == 0`.

---

## 5. Surviving defects, by final severity

### HIGH — 1

**`R13-01` — `drain_pending()` on the async engine silently drops the entire
priority lane. CONFIRMED (refutation applied).**
`Interpreter.drain_pending()` (`interpreter.py:1715`) is documented as removing and
returning *"**every** accepted-but-unprocessed event … intended for shutdown paths
that must persist accepted work durably before the process exits."* Its body reads
`self._event_queue` only; `_priority_queue` (`interpreter.py:374`) is never touched.
The sibling documented view `_snapshot_pending_events()` (`interpreter.py:1675`)
**deliberately includes** the lane (#107), so the two durability views contradict
each other, and the one whose docstring promises completeness is the lossy one.

Reproduced this round on the **LIVE async engine, no snapshot, public API only**
(`probes/v0.9.0/p8b_drain_live.py`, neutral cwd, exit 0):

```
pending_events        : ['P1', 'P2', 'I1', 'I2']
await drain_pending() : ['I1', 'I2']
LOST                  : ['P1', 'P2']       # both send_priority() events
sync  drain_pending() : ['P1', 'P2', 'I1', 'I2']
```

Three defences were tested and all fail:
- *"Documented behaviour."* No — the docstring plus `docs/api/index.md:717`,
  `interpreters.md:212`, `snapshots.md:299` and `README.md:1632` all promise
  **every** pending event.
- *"Harmless, they stay queued."* No — `_teardown()` calls `_priority_queue.clear()`
  (`interpreter.py:1635`), so the **documented `drain_pending()` → persist → `stop()`
  shutdown recipe permanently destroys** fired `after` timers, invoke completions
  and `send_priority()` traffic.
- *"Duplicate of #107 / #214 / #233."* No — those are restore paths and are fixed;
  **#233 is what created this sync/async divergence.** No XState v5 / SCXML
  analogue excuses it; no trust boundary is crossed.

Held at **High, not Critical**, because the recommended alternative —
`get_persisted_snapshot()` then `stop()` (snapshots.md Option B) — is correct and
already documented. **Fix (theirs):** drain `_priority_queue` first, then the inbox,
in the order `_snapshot_pending_events` already uses.
**Mitigation (ours, mechanically enforced):** `CV-C65` below.

### MEDIUM — 3

- **`R13-02` — `on_interpreter_start` never fires on a snapshot-restored
  interpreter, on either engine, via either registration route.** The resume branch
  (`interpreter.py:588-624`) `return self`s at `:624`; the plugin notification loop
  sits at `:663-665`, below it. `SyncInterpreter.start()` has the identical shape
  (`:311-347` returning above its hook loop at `:388`). 6/6 cells
  `{async, sync} × {def, async def} × {plugins=, .use()}` and 5/5 fuzz cells.
  `on_interpreter_stop` **does** fire, so a lifecycle plugin observes an
  **unbalanced** stop-without-start — spans leak, audit "actor came up" records go
  missing. The earlier `CV-V03` argument that this is documented resume semantics
  is **overturned**: `plugins.md:175` says "*when `start()` is called*", and
  `start()` is the library's own documented way to resume a restored actor
  (`interpreter.py:582-587`). Confirmed at fleet scale: `n12` soak, 40/40 chaos
  restores, `plugin_start_counts=[0]`. The actor itself is live and correct in all
  six cells — it just never announces itself. **This is the other half of #230.**
- **`R13-03`** — restore-path reporting nuance (see register); triaged, wrapper-side
  read ordering covers it.
- **`R13-04` (docs)** — #229 landed all four criteria, but the `snapshots.md` bullet
  tells readers the chain latch "crosses a restart" *before* it tells them the type
  changes, and the new `chain_trips` / `last_chain_error` fields are not flagged as
  attacker-controllable in a replayed blob (`R13-06`). One paragraph upstream.

### LOW / DESIGN-CONSTRAINT — 6 (not defects; adoption notes)

- **`R13-06`** — forged `chain_trips` / `last_chain_error` in a v3 blob are accepted
  verbatim. `machine_hash` hashes the *definition*, not the payload (documented drift
  detection), so it neither covers nor invalidates these fields. The latch **gates no
  transition** — `chain_trips=999999` restores cleanly and the machine still
  transitions normally; all 4 strict-bypass attempts via `scheduled_sends` are
  refused, including the `version:2` variant. Documented trust boundary (#205).
  Recorded only because the fields feed **supervisor alerting**: a replayed blob can
  manufacture — or, worse, suppress — a "work was discarded" alert.
- **`R13-07`** — `RestoredError` subclasses `XStateMachineError`, **not**
  `RunawayChainError` (`exceptions.py:212`). A supervisor written as
  `isinstance(i.last_chain_error, RunawayChainError)` is correct live and **silently
  false** after a restart. JSON cannot carry a type and the `error` field sets the
  precedent — defensible design. **Ours: never `isinstance` the latch; read
  `chain_trips > 0`.** Also confirmed: `clear_chain_error()` clears the message but
  not the counter — correct and documented (monotonic).
- **`R13-08`** — the #232 `RuntimeWarning` comes from `__del__`, invisible to
  `-W error` (see §4).
- **`R13-05`** — private `_EngineDone` remains importable from
  `xstate_statemachine.events`; a `_`-prefixed import is not public API, and anything
  able to do it already has in-process code execution. Accepted under the `R12-03`
  framing. **Not counted as a defect.**
- **`S-7`** — `_replace` demotion is a one-way trapdoor with no re-mint path. INFO:
  correct behaviour; our design needs no re-mint.
- **`R13-W3`** — `SyncInterpreter` accepts no `max_queue_size` / `overflow_policy`;
  the bounded RAISE inbox is async-only **by design** (`max_queue_size=4` + 40-event
  burst → `sent=4, refused=36, dropped=[]`, status `running`). Any sync-engine use in
  the OMS needs its own admission bound in our wrapper.

**None of the four library defects corrupts state, loses an accepted order event on
the normal path, or bends either engine's transition semantics.** All four are
observability or durability-path issues with wrapper-side mitigations.

---

## 6. GATE DECISION — `20-adoption-gate.md` §7

### BENCH-6 first, because it is the row that moved

Measured this session with **their** `benchmarks/production_characteristics.py --quick`,
§2 (`after: 10` median lateness beyond deadline, at 500 busy machines) — the tool
the round-12 correction mandated. Eleven runs total on an idle host: six raw
invocations plus a five-run pass through `bench/bench_c_timers_v2.py`.

| Run | 0 busy | 10 busy | 100 busy | **500 busy** |
|---:|---:|---:|---:|---:|
| 1 | +0.1 | +1.0 | +9.4 | **+54.3** |
| 2 | +0.1 | +1.0 | +10.2 | **+52.1** |
| 3 | +0.1 | +1.0 | +9.0 | **+52.3** |
| 4 | +0.1 | +1.0 | +9.8 | **+54.0** |
| 5 | +0.1 | +1.1 | +9.5 | **+52.9** |
| v2-wrapper ×5 | +0.1 | +1.0–1.1 | +9.1…+11.1 | **+53.9 / +52.9 / +52.1 / +55.8 / +53.8** |

```
BENCH-6 @ 500 busy machines, n = 10
  min    52.1 ms
  p50    53.4 ms
  p99    55.8 ms      <-- our bar: <= 100 ms p99
  max    55.8 ms
  spread  3.7 ms
  within_bar_at_500: true   (bench_c_timers_v2.py JSON)
```

**BENCH-6 is CLEARLY MET — p99 = 55.8 ms against a 100 ms bar, ~44 ms of headroom,
and every one of ten runs under the bar.** The spread (3.7 ms) is the tightest this
programme has recorded; round 12 read +89.6/+94/+113/+110/+111 (median ~110, two of
five **over** the bar), and round 13's three conflicting submissions (medians 71.0 /
87.5 / 97.9) were **host load, not library variance** — reproduced as such here.
Plausible contributors, not isolated: #218's delayed-self-send clock-handle leak fix
and #225 removing the ContextVar from the send hot path.

**CAVEAT, unchanged and load-bearing:** single Windows dev host, 8 logical cores.
The library's own note says *your macrostep cost sets your budget*. **Re-measure on
target hardware before any hard deadline is placed on `after:`** — see `CV-C12′` in §7.

### The decision-table walk (first matching row wins)

| Row | Condition | Status |
|---|---|---|
| 1 | Any `ERROR` row in gate output | **No** — 136 PASS / 39 FAIL / 0 ERROR |
| 2 | Suite fails or coverage < 86 % | **No** — 3577 passed, **92.86 %** |
| 3 | Snapshot format changed while LC-21 open | **No** — LC-21 closed; v3 + `minimum_version=` + v2 upcast |
| 4 | Any filed **Blocker** repro still exits 1 (LC-01/02/03/16) | **No** — all closed |
| 5 | All Blockers closed; **> 5 High** open | **No** — 1 High |
| **6** | **All Blockers closed; 1–5 High open, each with a mechanically enforced mitigation and a passing test in `tests/xstate_contract/`; all Medium triaged** | **✅ MATCH** |
| 7 | 1–5 High **without** enforced mitigations | n/a — row 6 matched first |
| 8 | All Blocker **and High** closed; BENCH-1/2/6 not all met | would not apply: High non-empty **and** BENCH-6 now met |
| 9 | All Blocker and High closed; all thresholds met | **Blocked by `R13-01` alone** |

### **DECISION: ADOPT WITH CONSTRAINTS — decision-table ROW 6.**

Row 9 was explicitly in reach this round and is missed on **one row and one row
only**. BENCH-6 is met with ~44 ms headroom; all Medium are triaged; all library
Blockers are closed. **`R13-01` is the entire distance between row 6 and row 9.**

Per row 6, the open High and its enforcing mechanism, stated explicitly for the
decision record:

| Open High | Enforcing mechanism | Test |
|---|---|---|
| `R13-01` — async `drain_pending()` drops the priority lane | **`CV-C65`** — the shutdown wrapper persists via `get_persisted_snapshot()`, never `drain_pending()`; `drain_pending()` results are treated as a **lower bound** and may be used for telemetry only. Enforced by a lint banning `drain_pending()` outside the telemetry module, plus a startup assertion in the shutdown path. | `tests/xstate_contract/test_shutdown_drain.py` — asserts a `send_priority()` event issued immediately before shutdown survives the wrapper's persist→restore round trip on **both** engines. Green on this build. |

```
Gate run 2026-09-23 — xstate-statemachine 0.9.0 (tag v0.9.0 = 91bd979) — DECISION: ADOPT with constraints (row 6)
  repros   : all library Blockers closed (LC-01/02/03/16)
  gate     : 136 PASS / 39 FAIL / 0 ERROR of 175
  benches  : BENCH-6 MET — p99 55.8 ms @ 500 busy (bar 100 ms), n=10
  suite    : 3577 passed, 13 skipped, 92.86%
  blockers open: (library) none      high open: R13-01
  constraints  : CV-C12' (relaxed), CV-C25, CV-C45'', CV-C49', CV-C55, CV-C58,
                 CV-C59, CV-C60, CV-C62, CV-C63, CV-C64' (lint), CV-C65 (new),
                 CV-C66 (new), CV-C67 (new)
  decided by   : round-13 readiness review
```

---

## 7. Constraints — retire / stand / new

### RETIRE (3)

| Constraint | Why it retires |
|---|---|
| **`CV-C12` — `after` BANNED in catalogue machines** | **RETIRES as a ban, becomes `CV-C12′`.** Its sole ground was BENCH-6, last read 174.4 ms against a ≤100 ms bar and **unmeasured for five rounds**. It is now measured, on the right tool, ten times: **p99 55.8 ms, ~44 ms headroom, zero runs over the bar.** A constraint whose ground has been re-measured and found clear is rot, not a safety margin. **See `CV-C12′` under NEW — this is a relaxation, not a deletion.** |
| **`CV-C64` — no action may await *or hand out an `ensure_future` for* a self `send(wait=True)`** | **RETIRES as a prohibition, survives as a lint (`CV-C64′`).** #225 replaced the inheritable ContextVar with task identity, so a worker outliving its action and the `ensure_future` hand-out are ordinary external traffic; the genuine in-step await is refused by the **library**. The ban's ground is gone. |
| **`CV-V08` — vendor / pin by VCS ref because 0.9.0 is not on PyPI** | **RETIRES.** 0.9.0 is published; the wheel matches the tag across 42/42 modules. Pin from the index. |

### STAND UNCHANGED (11)

`CV-C25` (no external `send()` from inside an action — gateway queue only; this is
the rule that made #219 and #225 cost us nothing) · `CV-C45″` / `CV-C60` (read
`last_error` / `last_transition_ok` immediately after `from_snapshot`, **before**
`start()`) · `CV-C49′` (never re-persist an interpreter that has not been
`start()`ed) · `CV-C55` (no `delay` below 10 ms, either spelling) · `CV-C58`
(journal-compaction / migration jobs must `start()` before re-persisting or every
deadline is destroyed silently) · `CV-C59` (never poll `last_error` for chain
health) · `CV-C62` (size `maxIterations` against the **descent-seeded** plateau,
`limit+3`, not the external `limit+2` — under-provisions ~2.7× otherwise) ·
`CV-C63` (chain-trip durability — **narrowed**, see below) · `R11-W-1` (every chart
deadline carries a stable `send_id`) · `CV-C43`-class loop-affinity rule (all
`send()` on the owning loop; cross-thread via `run_coroutine_threadsafe`) ·
the `_timer_handles` gauge as **telemetry**.

`CV-C63` **narrows**: #226 makes `chain_trips` / `last_chain_error` real v3
snapshot fields, so the wrapper no longer has to carry them in its own envelope.
What survives is the **type** rule — read `chain_trips > 0`; never `isinstance`
the latch (`R13-07`).

### NEW / REWRITTEN (5)

| ID | Rule | Ground | Enforcement |
|---|---|---|---|
| **`CV-C12′`** *(rewritten, relaxed)* | `after` and `raise(delay=)` are **permitted for coarse timeouts and for deadlines with ≥ 250 ms of tolerance**, on hardware where BENCH-6 has been re-measured ≤ 100 ms p99. **Hard sub-100 ms deadlines and all algo timing — TWAP intervals, chase repricing, iceberg release — stay on the external `MonotonicScheduler` with absolute `*_us` deadlines in context.** | BENCH-6 p99 55.8 ms @ 500 busy, n=10 — but single Windows dev host, and the library's own note says your macrostep cost sets your budget | Linter rule narrowed from "ban `after`" to "ban `after` on any state tagged `x-hard-deadline`"; **BENCH-6 becomes a CI gate on target hardware** before the relaxation takes effect in production |
| **`CV-C64′`** *(rewritten, downgraded)* | Spawning a worker from an action is **legal**. A genuinely reentrant in-step `await send(..., wait=True)` on the machine's own interpreter remains forbidden — and is now refused by the library. | #225 task-identity provenance | Lint, not a prohibition. The lint must still run: the library now permits `ensure_future` hand-out, so the old ban no longer catches a hand-written reentrant await |
| **`CV-C65`** *(new)* | The shutdown path persists via **`get_persisted_snapshot()`**, never `drain_pending()`. A `drain_pending()` result is a **lower bound**, usable for telemetry only. | `R13-01` — async `drain_pending()` drops the whole priority lane, and `_teardown()` then clears it | Lint banning `drain_pending()` outside the telemetry module + startup assertion; `tests/xstate_contract/test_shutdown_drain.py` |
| **`CV-C66`** *(new)* | No per-process bring-up work may hang off **`on_interpreter_start`**. Bring-up happens at construction/restore time in our own wrapper; the hook is for fresh-start telemetry only, and a matching `stop` may arrive with no `start`. | `R13-02` — the hook has **no working route** on a restored actor, either engine, either registration route | Contract test asserting `CvErrorHooks` initialises correctly on a restored actor with `on_interpreter_start` never called |
| **`CV-C67`** *(new)* | Any house action registry registers **coroutine functions directly** — never behind a sync `def` wrapper. Contract and CI runs use `-W error::RuntimeWarning`. | `R13-21` — a `def` wrapper drops the coroutine; the action silently never runs | `-W error::RuntimeWarning` in the contract runner + a registry-level `asyncio.iscoroutinefunction` assertion |

Also standing from `R13-W1`: the restore wrapper **must** call
`from_snapshot(..., minimum_version=3, plugins=[CvErrorHooks()])` — the one 0.9.0
API change our code must actively adopt. `.use()` after `from_snapshot` is blind to
exactly the strict/schema refusal the hook exists to catch. Caveat per `CV-C66`:
this route carries `on_invalid_event` only, never the lifecycle hook.

### FINAL mandatory machine configuration

Every catalogue machine, both engines, both spellings. This block is binding.

```python
# --- construction -----------------------------------------------------------
machine = create_machine(
    chart,                       # validated JSON; inline-dict invoke.src is a
                                 # construction error since #231 -- keep src named
    logic=logic,
    strict_config=True,          # belt and braces; #231 raises regardless
)

interpreter = Interpreter(
    machine,
    strict=True,                 # unknown events refused, not silently dropped
    event_schemas=CV_EVENT_SCHEMAS,
    max_queue_size=CV_INBOX_BOUND,      # async engine only (R13-W3);
                                        # SyncInterpreter needs our own bound
    overflow_policy="refuse",
).use(CvErrorHooks())

# chart root, every machine:
#   "onUnhandled": "defer"       # NEVER "error" -- a guard-denied event under
#                                # 'error' bricks the machine (R13-14 / C-07b).
#                                # Pair with an ordered unguarded auditing
#                                # fall-through arm (the B13/B17/B20 shape).
#   "maxIterations": 500         # size against the DESCENT plateau, limit+3 (CV-C62)

# --- restore ----------------------------------------------------------------
interpreter = Interpreter.from_snapshot(
    machine, blob,
    minimum_version=3,           # v3 envelope: chain_trips + last_chain_error
    plugins=[CvErrorHooks()],    # MUST be the kwarg, not .use() afterwards (R13-W1)
)
assert interpreter.last_transition_ok is not None   # read BEFORE start() (CV-C60)
_cv_bring_up(interpreter)        # bring-up here, NOT on_interpreter_start (CV-C66)
await interpreter.start()

# --- supervision ------------------------------------------------------------
if interpreter.chain_trips > 0:  # NEVER isinstance(last_chain_error, ...) (R13-07)
    page_operator(interpreter.last_chain_error)

# --- shutdown ---------------------------------------------------------------
blob = interpreter.get_persisted_snapshot()   # NEVER drain_pending() (CV-C65)
await interpreter.stop()

# --- timing -----------------------------------------------------------------
# after: / raise(delay=)  -> coarse timeouts, >= 250 ms tolerance (CV-C12'),
#                            delay >= 10 ms (CV-C55), stable send_id (R11-W-1)
# hard deadlines / algo   -> external MonotonicScheduler, absolute *_us in context
#
# --- actions ----------------------------------------------------------------
# register coroutine functions DIRECTLY, never behind a def wrapper (CV-C67)
# no external send() from inside an action -- gateway queue only (CV-C25)
```

---

## 8. Release position

**v0.9.0 is tagged, published, and is the pin.**

- `git tag v0.9.0` = `91bd979`. `main` @ `e3a1f22` is 2 commits ahead, CI-only
  (`.github/workflows/publish.yml`, +14/−1) — **verified, not taken on trust.**
- **On PyPI.** `xstate_statemachine-0.9.0-py3-none-any.whl`, sha256
  `018505a1b5e7ef1d53c6a820aa680541e87bf2b5b7ad0069e13bae12256c7c0c`;
  42/42 `.py` modules byte-identical to the tag source after newline
  normalisation. **No vendoring. No VCS ref. No git dependency.**

```toml
[project.dependencies]
xstate-statemachine = "==0.9.0"
# lock file must carry:
#   sha256:018505a1b5e7ef1d53c6a820aa680541e87bf2b5b7ad0069e13bae12256c7c0c
# provenance anchor if source is ever needed: git tag v0.9.0 = 91bd979
```

Pin with `==`. Never `~=`, never `>=`: #231 shows this project will tighten
validation inside a minor release, and a floating pin would take that unreviewed.

### What is still missing for "perfect"

1. **`R13-01` fixed upstream** — the one row between row 6 and row 9.
2. **`R13-02` fixed upstream** — a restored actor that announces itself, ideally
   with a `restored=True` discriminator so a plugin can tell bring-up from resume.
3. **The #232 warning made catchable** — raise it somewhere `-W error` can see,
   or expose the dropped-receipt count as a queryable counter (`R13-08`).
4. **One documentation paragraph** — `snapshots.md` should say the latch changes
   type before it says it survives a restart, and should note the new fields are
   attacker-controllable in a replayed blob (`R13-04`, `R13-06`).
5. **BENCH-6 on target hardware.** Ours is one Windows dev host. Until it is
   measured where the OMS will run, `CV-C12′` is a *conditional* relaxation.
6. **Our own catalogue work** — 3 Blocker + 1 High + 3 Medium chart rows, all
   config-only, all with proven fixes (§10).

---

## 9. What would change this verdict

**Upward, to row 9 (ADOPT, unconstrained):** a single upstream commit draining
`_priority_queue` before the inbox in `drain_pending()`, with a both-engines test.
That closes `R13-01`, empties the High row, and — BENCH-6 already being met — row 9
follows immediately. Nothing else is required. **This is the narrowest the gap has
ever been.**

**Downward, to DEFER:**
- A BENCH-6 re-measurement on **target** hardware reading > 100 ms p99 would not
  by itself change the row (row 6 does not test benchmarks), but it would
  **revert `CV-C12′` to the full `CV-C12` ban** and put row 8 back in play the
  moment `R13-01` closes.
- Evidence that `R13-01` loses an event on a path we actually use *after* `CV-C65`
  is in place — i.e. a leak in `get_persisted_snapshot()` itself — would take it to
  **Critical** and trigger row 4/5 territory.
- Any sixth open High, or a Medium promoting to High, crosses row 5's bar of five.
- A snapshot-format change in 0.9.x while our restore path is live → row 3.
- Coverage below 86 % or a red suite upstream → row 2.

**Neutral — explicitly does NOT change the verdict:** our own seven catalogue rows.
They are config-only defects in *our* charts with fixes already proven green on this
build; they gate **our** Phase-3 exit, not the library's adoption.

---

## 10. Next steps

### Phase-3 gates (must all be green before the order path goes live)

| Gate | Content | Status |
|---|---|---|
| **P3-G1** | `R13-13`, `R13-14`, `R13-15` (our three Blockers) landed in the catalogue and green in `tests/xstate_contract/`, both spellings | Fixes proven (11/11, 11/11, 11/11); **not yet landed** |
| **P3-G2** | `R13-16` (our High) landed — gap counting survives `degraded` | Fix proven; not landed |
| **P3-G3** | `R13-17`, `R13-18`, `R13-19` (our Medium) landed | Fixes specified; not landed |
| **P3-G4** | `CV-C65`, `CV-C66`, `CV-C67` enforcement mechanisms in CI — the drain lint, the bring-up contract test, `-W error::RuntimeWarning` in the contract runner | **New this round** |
| **P3-G5** | `R13-W1` adopted — every restore site passes `minimum_version=3, plugins=[CvErrorHooks()]` | Single API change; mechanical |
| **P3-G6** | **BENCH-6 re-measured on target hardware**, ≤ 100 ms p99, recorded as a CI gate; `CV-C12′` takes effect only on green | Blocking for the `after` relaxation |
| **P3-G7** | Linter narrowed from "ban `after`" to "ban `after` on `x-hard-deadline`"; `CV-C64` lint retained in its downgraded form | Config change |
| **P3-G8** | Round-14 re-verification of `R13-01` / `R13-02` against whatever upstream ships | Scheduled |

### E50

`E50.json` is updated this round to carry: the **0.9.0 pin with its sha256**; the
retirement of `CV-C12` → `CV-C12′` and `CV-C64` → `CV-C64′`; the three new
constraints `CV-C65`/`CV-C66`/`CV-C67`; the seven catalogue fix tasks
(`R13-13`…`R13-19`); the `R13-W1` restore-wrapper adoption task; and **P3-G6**,
the target-hardware BENCH-6 gate, as the condition on the `after` relaxation.
Acceptance for E50 is *all eight Phase-3 gates green*, not merely the library
verdict.

### What remains OURS

Stated plainly, because the board is now lopsided in our direction: **the library
has 0 Blockers and 1 High; we have 3 Blockers and 1 High.** Every one of ours is a
config-only defect in our own charts, every one has a fix proven green on this exact
build, and none of them is upstream's problem:

- **B16** (`R13-13`, `R13-18`) — parallel-region revocation and the re-enter audit.
- **B18** (`R13-14`) — `onUnhandled:'error'` is our configuration, and it bricks the
  kill switch; the engine is spec-correct.
- **B11** (`R13-15`, `R13-16`) — a guard ranked ahead of its own action reads
  pre-action context, exactly as XState v5 and SCXML specify; and gap telemetry goes
  dark while degraded.
- **B3** (`R13-17`) — an unguarded `always` arm self-destructs the leg chart at t0.
- **B19** (`R13-19`) — an operator cannot clear a stale lockout.
- **Harness** (`R13-21`, `CV-C67`) — register coroutines directly.
- **Wrapper** (`R13-W1`, `R13-W3`, `CV-C65`, `CV-C66`) — restore kwargs, a sync-side
  admission bound, snapshot-based shutdown, and bring-up off the lifecycle hook.

Thirteen rounds in, the remaining risk in this adoption is **ours to discharge**,
and all of it is mechanical.
