# Observability, Error Surface & Operability — re-run @ `f28719c` (round-8)

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit `f28719c` (unreleased 0.8.1; round-8 fixes #192-#201, reopening
#181/#186). `__version__` still `0.8.0`; identified by commit only.

**Date:** 2026-09-22. **Interpreter for every run:**
`_ref/xstate-statemachine/.venv-main/Scripts/python` with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. No library source modified. No `git`
run in the CandleViewer repo. GitHub not touched.

**Time-bound reductions** (stated up front, per the standing mandate). The
20-minute overall wall-clock bound made the full requested matrix (>=300-case
persistence property, 10k/s external-priority soak, 50-slow-children load,
>=500-config x {def,async}x{sync,async-engine} livelock fuzzer, 50x
determinism/hash-seed sweep, 12-min soak) infeasible this pass. What was
run:
- Both 6db65d8-round scripts (`rerun_prior.py`, `new_attacks.py`,
  `rerun_prior_async.py`), **unmodified**, re-run verbatim against
  `f28719c` — §1.
- One new script, `new_attacks_r8.py`, seven attacks (U1-U7) built
  specifically against round-8's new machinery (priority-lane provenance
  shedding #192, `def`-service rollback unwinding #193, per-child
  `children_timeout` #194, engine-event provenance/forgery #195, `always`
  eventless-selection #196, `on_interpreter_start` in-flight window #199) —
  §2.
- **NOT RUN** this pass (§4, unchanged in kind from the 6db65d8 report):
  the >=300-case persistence property test, the configuration/state_ids
  contradiction fuzz at scale, the null-`machine_hash` fuzz, the 10k/s
  external-priority-vs-self-chain soak (concurrent, not sequential), the
  50-slow-children `children_timeout` load test at full N, the >=500-config
  livelock fuzzer, the 50x determinism/hash-seed sweep, the 5-way
  guard-disposition matrix, the strict+wildcard matrix, the `__slots__`
  surface probe, and the 12-minute soak.

---

## 1. Prior-defect re-run (`rerun_prior.py`, `new_attacks.py`,
`rerun_prior_async.py` — all unmodified from 6db65d8/221ce7c)

| ID | 6db65d8 result | f28719c result | Verdict |
|---|---|---|---|
| D-observability-1 (guardErrorPolicy naming) | UNCHANGED (design) | Identical enum, identical 3 receipts (`false`/`true`/`raise`). | **UNCHANGED** |
| D-observability-2 (guard raise / Receipt shape) | FIXED | Identical: `raise` -> `Receipt(changed=False, error=ValueError(...))`. | **UNCHANGED (still fixed)** |
| D-observability-3 (deferred replay fold) | FIXED | Identical `state_ids` split (`r1`=`a`, `r2`=`b`). | **UNCHANGED (still fixed)** |
| D-observability-4 (`SyncInterpreter(max_queue_size=)` TypeError) | UNCHANGED | Identical `TypeError`. | **UNCHANGED** |
| D-observability-5 (`StateNotFoundError` hook, sync) | FIXED | Identical hook set (`on_transition`, `on_event_received`, `on_resolve_error`). | **UNCHANGED (still fixed)** |
| D-observability-6 (`.use()` vs `.plugins=`) | CONFIRMED NOT A DEFECT | Identical. | **CONFIRMED NOT A DEFECT** |
| D-observability-7 (`has_dormant_invocations`) | UNCHANGED (documented) | Identical. | **UNCHANGED (documented)** |
| D-observability-8 (`stop()` drops queue silently) | FIXED | Identical: `on_event_dropped` x5. | **UNCHANGED (still fixed)** |
| D-observability-9 (no `to_dict`/`to_json`) | informational | Identical (`to_mermaid`/`to_plantuml` present). | **UNCHANGED** |
| I: loop-side `RAISE` `on_event_dropped` (#157) | PASS 638/638 | PASS, identical 638/638 exactly-once. | **UNCHANGED** |
| J/J′: entry-window snapshot refusal, both engines (#169) | PASS | PASS, identical `SnapshotMidStepError` text both engines. | **UNCHANGED** |
| K/K′: `always`-chain trips at same lap, both engines (#166/#168) | PASS, `n=25` | PASS, both trip at `n=25` still. | **UNCHANGED** |
| L: chain budget not reset by external senders (async) | PASS | PASS, trips at `n=480` despite 16 concurrent `PING` senders. | **UNCHANGED** |
| M: `service_pool_size=1`, 50 `def` services, `stop()` mid-flight | PASS, 3/50 done | PASS, 0/50 done at stop, 0.09s, no hang. | **UNCHANGED (behavioral — see note)** |
| M-async: same, 50 `async def` services | PASS, ~50/50 done (not pool-bound) | PASS, ~50/50 done, 0.23s, no hang. | **UNCHANGED** |
| N: `start()`/invoke-registration ordering (#171/#116) | PASS (behavioral, no public `children`) | Identical: `children_attr_present=False`. | **UNCHANGED** |
| O: `send_threadsafe` in-flight counter settles through a chain trip | PASS, counter->0 | PASS, `in_flight_counter=0`, chain trips cleanly (`n=16`, discarded 1). | **UNCHANGED** |

No regressions among any of the 17 legacy checks between 6db65d8 and
`f28719c`. (M's `completed_before_stop` count is timing-noise, not a
regression — it was 3/50 at 221ce7c/6db65d8 and 0/50 here; all three runs
independently satisfy the actual assertion, "no hang, no crash, count in
`[0,50]`".)

---

## 2. New attacks on round-8's machinery (`new_attacks_r8.py`)

Seven attacks (U1-U7), each targeting one of #192-#201's code paths.
Standalone script, raw output in `new_attacks_r8.txt`.

| Attack | Target | Result |
|---|---|---|
| **U1**: forge `"engine": true` on a plain hand-built dict `{"kind":"done","type":"done.invoke.svc","data":...,"src":"svc","engine":True}`, `restore_event()` it, then `send()` it into a real machine whose real `svc` invoke is still pending | #195 (engine-only minting via `engine_done`) | **See finding D9-observability-1 below** — the forged dict *is* accepted as a trusted engine completion (`is_system_event`→`True`) and, sent while the real `svc` was still in flight, silently produces `changed=False, error=None` (it targets an `onDone` transition that the real state, having already left `arm`-equivalent context, no longer has — see detail). |
| **U2**: v1 (no `kind`) restore of the init sentinel vs. a plain named event (`after.hours`); malformed empty-`type` and non-dict records | #162/#198 | **PASS** — `___xstate_init___` restores as system (`is_system_event=True`), `after.hours` restores as **user** traffic (`is_system_event=False`, not laundered by name), and both malformed shapes raise `SnapshotCorruptError` as documented. |
| **U3**: `start(children_timeout=0.1)` against N=1 vs N=50 parallel regions, each invoking an `async def` child that sleeps 0.3s | #194 (per-child, not aggregate) | **PASS** — wall time flat in N: `[0.102s, 0.11s]` for N=1 vs N=50, both bounded near the 0.1s timeout, spread 0.009s. Confirms the aggregate-bound defect (R8-03) is fixed. |
| **U4**: a self-generated `always` cycle (`maxIterations=30`) tripping `RunawayChainError`, with 60 external `send("PING", priority=True)` fired concurrently | #192 (shed by provenance, not position) | **PASS** — chain trips (`RunawayChainError`, "discarded 0 of them"), and **all 60/60** external priority PINGs were delivered (`count_ping` fired 60 times) — none shed as `chain_budget`. |
| **U5**: an action self-sends `SPIN` via `send(priority=True)` in a loop, `maxIterations=20` | #192 (action-issued priority send is charged like a `raise`) | **PASS** — `RunawayChainError` fires, `n_loop_calls=21` (bounded at the limit, not unbounded); message explicitly says "discarded 1 of them," i.e. the tripping event itself is the one shed. |
| **U6**: async engine, entry action `boom` raises after `busy`'s `invoke` armed a `def` service, `actionErrorPolicy: "rollback"` | #193 (def-service unwound by rollback before executor handoff) | **PASS** — `final_state=idle`, `svc_called_count=0`. The armed `def` service was never submitted; matches `test_rollback_unwinds_invoke_arming`. |
| **U7/U7′**: a `PluginBase.on_interpreter_start` hook calls `get_persisted_snapshot()` on a trivial one-state machine, both engines | #199 (in-flight flag covers `on_interpreter_start`) | **PASS**, both engines — identical `SnapshotMidStepError("...is mid-macrostep...")`, no torn blob returned. |

---

## 3. Detail on U1 (the one attack that surfaced something worth flagging)

The script built the *record* by hand (a plain `dict`, no import of any
private engine class) and called only the public `restore_event()`. Per
`events.py`'s own documented trust boundary (comment above `restore_event`,
quoted verbatim): *"A caller who can write arbitrary snapshot records
already controls `state_ids` and `context` outright (#185), so this is the
correct trust boundary."* — i.e. the library's stated position is that the
`"engine": true` flag is not meant to be secret or resistant to a
snapshot-writer forging the *whole record*; it exists to stop a
*genuine round-trip* of a real completion from being demoted to user
traffic, and to stop a *casually shaped* dict (e.g. one built by a caller
who doesn't know about the flag at all) from being *promoted* to a trusted
completion by accident. U1 confirms the flag does exactly what is
documented — nothing more — and the observed "harmless" result
(`changed=False, error=None`) was because the target `onDone` transition
already had a different active state by the time the forged event was
sent, not because of any additional validation. **This is not a regression
or a new defect**: it is the documented, already-disclosed trust model
(the report treats it as informational, not filed as D9-observability-n).
The prompt's request ("construct `engine_done` via ... snapshot
`'engine': true' → must be refused under strict") describes a
*stronger* guarantee than the library documents or than #195's changelog
entry claims; #195 only promises the flag round-trips a *real* completion
correctly and refuses a *hand-built* `DoneEvent`/`ErrorEvent`/`AfterEvent`
(the public classes) under `strict` — which a separate, unattempted check
(constructing the public `DoneEvent` directly, not the persisted-record
path) would need to verify. That specific check (public-class construction
+ `strict`) is listed under §4 not-covered, since U1 attacked the
persisted-record path only.

---

## 4. Defects filed

**No new `D9-observability-n` defects were confirmed this pass.** All 17
legacy checks reproduced identically (or within timing noise) on `f28719c`,
and all seven new attacks against round-8's machinery (priority-lane
shedding/charging by provenance, per-child `children_timeout`, def-service
rollback unwinding, `on_interpreter_start` in-flight coverage, v1/user-event
restore discrimination) held exactly as the changelog claims. U1's result
is documented library behavior, not a defect (§3).

---

## 5. Not covered this pass

- **Persistence property test** (>=300 random machines, every hook,
  nested/parallel/invoked children, both engines, both service kinds) —
  **not run**. Only the single documented `on_interpreter_start` shape
  (U7/U7′) and the legacy root-entry-action shape (J/J′) were checked.
- **Configuration/state_ids contradiction fuzz** (#198/#186) — not
  independently fuzzed; no adversarial mismatched-field blob was
  constructed this pass (U2 covered only the `kind`-absent v1 shape, not
  the v1-vs-v2 both-present-but-contradictory shape).
- **Null/absent `machine_hash` fuzz** across v0/v1/v2 — not attacked.
- **External priority sends at 10k/s concurrent, 0 dropped** — U4 ran 60
  sequential (non-`wait`) priority sends, not 10k/s concurrent producers;
  correctness at low/no-contention volume only.
- **`children_timeout` with 50 def + 50 async children mixed, and the
  full 50-slow-children load case with contention** — U3 used 50
  **async** children only (uniform), not a 50-def+50-async mix; the `def`
  non-yielding-entry-action honesty case (WARNING-always-fires, bound
  can't preempt a single thread) from the 6db65d8 pass's attack R was not
  re-run standalone here (folded into U3's async-only scaling check).
- **Def-service arm-then-rollback under 200 concurrent** — U6 ran a single
  sequential instance, not 200 concurrent.
- **RAISE loop-side exactly-once, round-8-specific variant** (interleaved
  with an armed coroutine service's completion landing at the same
  instant) — relied on the unmodified legacy attack I, which still passes
  verbatim; no round-8-specific interleaving variant was built.
- **Livelock fuzzer >=500 configs x {def, async def} x both engines** —
  not run.
- **Determinism**: 50x identical-trace check, hash-seed sweep — not run.
- **Guard-crash/denied/deferred/unhandled/error-kill 5-way receipt
  matrix** and **strict+wildcard matrix** (#190) — not attacked this pass
  beyond the legacy 3-way `guardErrorPolicy` check (D1/D2).
- **Private-subclass `isinstance` semantics beyond the persisted-record
  path** — U1 attacked forgery via `restore_event()` only; constructing the
  *public* `DoneEvent`/`ErrorEvent`/`AfterEvent` directly and sending it
  under `strict` (the stronger claim #195 actually makes) was **not**
  separately attacked this pass — see §3.
- **Redaction, `__slots__` attribute surface** — not attacked.
- **12-minute soak** (200 machines, async services, external priority
  producer, rollback+onDone, `always`->invoke, chaos snapshot at
  quiescence) — **not run**, given the 20-minute overall bound.

---

## 6. Verdict

Round-8's observability-relevant fixes hold up under the reduced,
single-run attack set exercised here. All 17 legacy checks (9 defects +
8 round-6/7 attacks, including the async-service M-variant) reproduced on
`f28719c` with no regressions. Of the seven attacks purpose-built against
round-8's own changelog claims:

- **#192** (priority lane charges *and* sheds by provenance) holds on both
  halves — an action-issued priority send is charged like a `raise` (U5),
  and external priority sends are never shed even while a self-generated
  chain is actively tripping and discarding its own items (U4, 60/60
  delivered).
- **#193** (`def`-service rollback unwinding) holds — a `def` service armed
  then rolled back by a raising entry action is never submitted (U6,
  `svc_called_count=0`).
- **#194** (`children_timeout` per child, not aggregate) holds — wall time
  is flat from N=1 to N=50 concurrent slow async children (U3).
- **#199** (`on_interpreter_start` inside the in-flight window) holds on
  both engines (U7/U7′) — identical `SnapshotMidStepError`, no torn blob.
- **#162/#198**-adjacent v1/user-event restore discrimination holds (U2) —
  the one true engine sentinel restores as system, a plausibly-named user
  event does not get laundered by name, and malformed records are refused.
- **U1** surfaced a result worth recording but **not a defect**: forging a
  persisted-record dict with `"engine": true` by hand (no private-class
  import) is accepted as trusted, exactly as `events.py`'s own documented
  trust boundary states (the flag defends the *round-trip*, not a
  snapshot-writer who already controls the whole blob per #185). No
  `D9-observability-n` filed for it; flagged in §3/§5 as a stronger check
  (public-class construction under `strict`) the task's phrasing implies
  but this attack did not perform.

**No Blocker/High-severity observability regressions were found.** This
remains a narrow, time-boxed slice of the requested matrix — the
persistence property test at scale, the concurrent 10k/s priority soak,
the 50-mixed-children load case, the >=500-config livelock fuzzer, the
50x determinism/hash-seed sweep, the 5-way guard/strict matrices, the
public-class-forgery-under-strict check, and the 12-minute soak were
**not run this pass** (§5) and must not be read as confirmed by this
report. Consistent with the standing caution in the 6db65d8 report: a
single-shot probe closing a documented repro shape is evidence the
*specific* shape no longer reproduces, not that the *class* of defect
(silent, load-dependent, only-visible-under-a-fuzzer failure) is closed at
scale.
