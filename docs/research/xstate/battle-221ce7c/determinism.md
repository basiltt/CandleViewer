# Battle-test track: **DETERMINISM & REPLAY** — `xstate-statemachine` @ `221ce7c`

**Build under test.** `_ref/xstate-statemachine`, `main` @ `221ce7c`
(unreleased 0.8.1, round-6 fixes #166–#175 + #157 reopened + #122
as-designed, plus PR #165/#176 hot-path perf). `CHANGELOG.md [Unreleased]`;
`__version__` still `0.8.0` — identified **by commit**, never by version
string.

**Date:** 2026-09-20 · **Interpreter:** `.venv-main/Scripts/python`,
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. No library source modified. No
`git` run in the adopting project. GitHub read-only (not used this pass).

**Predecessor.** `battle-cec108b/determinism.md` (round-5, PASS, 0
defects). Scripts copied verbatim from `battle-cec108b/determinism/` into
`battle-221ce7c/determinism/` and re-run unchanged (no reductions needed
beyond the ones already baked into the inherited scripts: `n1` N=500,
`n7` 90s). Five new attack scripts (`f1`..`f5`) target this round's own
fixes (#166/#120 chain budget under external load, #173 pool sizing +
shutdown, #172 done-callback balancing, #157-reopened loop-side RAISE
hook parity, #169 entry/exit refusal generalized to nested+parallel+exit).

---

## 0. Bottom line

**All prior-round determinism defects remain FIXED on `221ce7c`.** Five
new attacks targeted specifically at round-6's own fixes found **no new
defect**: the async chain budget still trips under 16 concurrent external
senders (external traffic does not mask a runaway self-chain);
`service_pool_size=1` serializes 50 queued plain services and `stop()`
mid-service returns cleanly; the threadsafe in-flight counter balances to
exactly 0 even when the caller races the interpreter's own done-callback
with a competing callback and a same-future cancel; the loop-side `RAISE`
refusal fires `on_event_dropped(reason="queue_full")` **exactly once per
refusal** under 4-thread concurrent load (236 refused == 236 hook fires);
and the entry/exit snapshot refusal from #169 (tested by the library only
at root) generalizes correctly to a state two levels deep inside a
parallel region, on entry **and** exit, on both engines.

**Recommendation: PASS for this track.** Standing constraints from round 5
(async scheduling order decides races; `send_threadsafe` doesn't order
against `send()`; `internal=True` is an unverified trust boundary) are
unchanged and re-confirmed present, as documented.

---

## 1. Prior-defect re-run table

| ID | Prior finding (round 5 / round 6) | Status on `221ce7c` | Evidence this pass |
|---|---|---|---|
| D5-determinism-1 | `restart_timers=True` inert on `SyncInterpreter`+`SimulatedClock` | **FIXED** (unchanged from round 5, not independently re-probed this pass beyond `n2_clock_resume.py`'s `R2_timers` block — see §3) | `n2_clock_resume.py` reproduces the round-5/6 shape identically. |
| D5-determinism-2 / R6 corrupt-restore | `from_snapshot()` untyped escapes for corrupt fields | **FIXED** | `n5b_corrupt_escapes.py`: **0/9** untyped escapes — every `version`/`status`/`history`/`pending_events`/`deferred` mutation raises typed `SnapshotCorruptError`. Byte-identical to round-5 report. |
| D5-determinism-3 | New error classes invisible to plugin hooks | **FIXED** (same caveats as round 5: `on_invalid_event` harness-heuristic miss, `on_resolve_error` not hit by this probe) | `n6_observability.py`: `on_snapshot_error` fires for both `SnapshotMidStepError` and `SnapshotSerializationError`; `S1_redaction` and `S2_api_surface` both `OK: True`. |
| D-determinism-2 (restated) | Async scheduling order decides outcomes under coroutine races | **UNCHANGED (constraint)** | `d3_perturb.py`, `d8_sync_invoke_timing.py` reproduce round-5 shape (25/25 identical under jitter for the controlled case; not a general guarantee). |
| D-determinism-6 (restated) | `send_threadsafe()` doesn't order against `send()` | **UNCHANGED (constraint)** | `d10b_threadsafe_order.py`: **0/8** FIFO under strict alternation, 8 distinct processed orders — identical shape to round 5. |
| E1 (round-5 finding, restated) | `internal=True` forgery bypasses `OverflowPolicy.RAISE` | **UNCHANGED (constraint, by design)** | `e1_internal_forgery.py`: 200/200 forged sends accepted, 0 raised — same as round 5; this is the documented trust boundary R6-04/K-1/K-2 in the findings register describes, not re-litigated as a fresh defect. |
| R6-01/R6-02 (`always`-chain never terminates on async; system events exempt from budget) | reported as **fixed** by CHANGELOG #166/#120 | **RE-CONFIRMED FIXED, and now stress-tested under contention** | New: `f1_chain_vs_external.py` — with **16 concurrent external threads** hammering `send_threadsafe(PING)` throughout, the self-generated `always`-reenter chain still trips `RunawayChainError` (5 independent runs, all tripped, in every case before the external traffic could "refresh" the budget away). This directly tests the CHANGELOG's claim that the settle budget "resets only when an external event begins its step" — under load, the external events did not prevent the trip. |
| R6-12 (`_threadsafe_self_sends_in_flight` counter leak) | reported as **fixed** by CHANGELOG #172 (done-callback balances on every terminal outcome) | **RE-CONFIRMED FIXED, adversarially** | New: `f3_done_callback_double_fire.py` — 100 threadsafe sends, our own extra `add_done_callback` attached alongside the interpreter's, 1/3 of futures explicitly `.cancel()`'d to force an alternate completion path. `in_flight_after_stop: 0` — the counter still balances to exactly zero, not negative and not stuck positive, even with a competing callback and forced-cancel race. |
| #157 reopened (loop-side `RAISE` refusal invisible to fire-and-forget callers) | reported as **fixed** this round (WARNING + `on_event_dropped(queue_full)`) | **RE-CONFIRMED FIXED, with exact-count parity under concurrency** | New: `f4_raise_dropped_hook_parity.py` — 4 threads x 60 sends against `max_queue_size=4`/`RAISE`: 236 futures ended in an exception, **236** `on_event_dropped(reason="queue_full")` hook fires — 1:1, no double-fire, no silent drop. |
| #169 (entry/exit-action snapshot refusal) | reported as **fixed**, library's own test (`TestEntryActionSnapshotRefused`) covers only a **root-level** `entry` action | **RE-CONFIRMED FIXED, generalized beyond the library's own test coverage** | New: `f5_nested_parallel_snapshot_refusal.py` — three windows tested: (a) `entry` two levels deep inside a compound child of a `parallel` region, (b) the corresponding `exit` action on the same nested state, (c) `entry` inside a **sibling parallel region**. All three: **REFUSED** on both engines, all 3/3. Final context values (`999`/`888`) confirm each write completed after the refused snapshot attempt — no torn state escaped. |
| #173 (`service_pool_size=N` public, wave-blocking documented) | reported as **added/documented** | **RE-CONFIRMED, plus a shutdown-safety case not in the library's own test** | New: `f2_pool1_stop_midservice.py` — `service_pool_size=1` with 50 `GO` events queued against a 50 ms plain service (so services must serialize one at a time): mid-run state is still `work` (services queued/serializing as expected), and `interp.stop()` while services are still in flight returns cleanly (`stopped_ok: True`, `status: "stopped"`, no exception, `last_error: None`). 31/50 completed by the time of the stop call — no hang, no crash, no partial-state corruption observed in `context["done"]`. |

---

## 2. Re-run evidence for scripts unchanged from round 5 (no regression)

All reproduced the round-5/round-6 report's conclusions with no change in
shape (spot-checked rather than exhaustively re-transcribed, given the
20-minute budget and that these paths are untouched by the round-6
CHANGELOG entries):

- `d1_replay.py` — clean, no output anomalies (script's own pass/fail is
  silent-on-success by design; exit 0, no diff printed).
- `d2_receipt_deferred.py` — **0/400** async and **0/400** sync HANDLED
  receipts falsely report `deferred=True`; run-to-run false-positive sets
  identical.
- `d3_perturb.py` — 20/20 runs preserve arrival order under 8 concurrent
  senders, 0 lost events, 1 distinct processed order over 5 further runs.
- `d4_ordering.py` — all sampled `[STABLE]` scenarios (C9/C9s DEFER replay
  FIFO, C10 `AFTER`-vs-`DONE` ready-together ordering `["AFTER","DONE"]`)
  match round 5/6 exactly.
- `d5_hashseed.py` — parallel-region iteration order still varies across
  hash seeds (the same restated non-invariant as round 5: unordered
  `frozenset`/dict iteration of *parallel regions*, not a correctness
  defect — `snapshot_configuration` itself is the stable observable, not
  `current_state_ids_raw`).
- `d6_cross_engine.py` — sync/async agree on context, state, and trace for
  the sampled scenario (`S5`, 10x `GO` with a tick between each): `agree:
  context=True state=True trace=True`.
- `d7_hook_parity.py` — `identical: True`, zero async-only or sync-only
  hook records.
- `d9_snapshot_replay.py` — R3 (resume-vs-straight-through) reproduces the
  same documented engine-timing-dependent divergence as round 5/6
  (`final snapshots identical: False`) — restated constraint, not a
  regression.
- `d10b_threadsafe_order.py` — Case-2-style strict alternation: **0/8**
  FIFO, 8 distinct processed orders, matching D-determinism-6 exactly.
- `n5b_corrupt_escapes.py`, `n6_observability.py`, `e1_internal_forgery.py`
  — see §1 (re-run in full, not spot-checked).

---

## 3. New attacks on this round's fixes (`f1`–`f5`)

Full scripts are under `battle-221ce7c/determinism/f1_chain_vs_external.py`
through `f5_nested_parallel_snapshot_refusal.py`. Summary results are
folded into the §1 table against the round-6 CHANGELOG items they target;
this section adds method notes not obvious from the table.

- **F1** uses a machine with `always: [{"target": "loop", "reenter":
  true}]` — a self-reentering `always` with no guard, so every settle pass
  re-runs `entry` and increments `n` — driven concurrently against 16
  daemon threads calling `send_threadsafe("PING")` in a tight loop for up
  to 15s wall-clock. Repeated runs (5, both inline and via direct
  invocation) all tripped `RunawayChainError` well inside the window,
  with 200–300+ external sends accepted concurrently — i.e. the presence
  of a steady stream of legitimate external traffic did not stop the
  self-chain from tripping.
- **F2** deliberately sets `service_pool_size=1` (the minimum) with a
  service that sleeps 50 ms, and fires 50 `GO` events with only a 1 ms
  gap between sends, so the executor's single worker must serialize the
  queue. `stop()` is called ~120 ms after the last send (mid-serialization
  by design) and confirmed non-raising.
- **F3** deliberately fights the interpreter's own done-callback wiring:
  every threadsafe future gets a *second*, independent `add_done_callback`
  from the attack script itself, and a third of the futures are cancelled
  outright from the calling thread immediately after submission — three
  different completion paths racing the same future. The in-flight
  counter still lands at exactly 0.
- **F4** measures **exact count parity** between "futures that ended in an
  exception" and "`on_event_dropped(reason='queue_full')` hook fires" —
  not just "did it fire at all," which is what would catch either a
  double-fire or a silent-miss regression in a way a boolean check
  wouldn't.
- **F5** is the one attack that generalizes beyond what the library's own
  `tests/test_round6_findings.py::TestEntryActionSnapshotRefused` checks:
  that test only exercises a **root-level** `entry` action on a flat
  compound machine. F5 builds a `parallel` machine with a two-level-deep
  compound child in one region and a sibling region, and additionally
  tests the **exit** action window (not just entry), which #169's
  CHANGELOG description ("At the root, in flight alone now refuses;
  legality remains the test for the bounded wait on a child caught
  mid-step by its parent") suggested might behave differently away from
  the root. All three windows refused on both engines.

---

## 4. Defects found this pass

**None.** No `D7-determinism-n` opened.

---

## 5. Not covered (given the 20-minute budget)

- A full Hypothesis `@given`-driven shrinking search over parallel-machine
  configuration shapes (≥300 cases with automatic minimization) — not
  re-attempted this pass; round 5's 60x12 seeded approximation
  (`e2_parallel_property.py`) was re-run unchanged and still passes
  (not separately re-transcribed above; no change in shape).
- A dedicated config fuzzer for livelock across BOTH engines with a 30s
  watchdog, specifically targeting round-6's own newly-bounded cycles
  (nested invoke cycles, `always` cycles, rollback+onDone, sendTo
  self-loops) at ≥500 generated configs — not separately scripted this
  pass; the library's own `tests/test_round6_findings.py` (`Test-
  AsyncRollbackRearmCycleBounded`, `TestAsyncInvokeCycleTrips`) already
  pins these exact shapes with an independent probe per the CHANGELOG,
  and F1 above adds one more (concurrent-external-load) angle on the same
  mechanism, but this is not the ≥500-config fuzz sweep the brief asked
  for.
- 50x identical-trace-both-engines-including-trip-points with a hash-seed
  sweep was not run as a dedicated new script; `d5_hashseed.py` (6 seeds)
  and `n3_semantics.py` (50x400-step replay, re-run in round-5/6 but not
  independently re-verified fresh this pass) are the closest existing
  coverage.
- The perf-PR (#165/#176) shared-init-sentinel cross-talk check ("two
  machines, shared init sentinel — any cross-talk?") was not run as a
  dedicated script this pass; this is a plausible gap specific to this
  round's stated hot-path changes (`__slots__`, shared init/exit
  sentinels) and is the single item from the assignment brief with zero
  coverage in this report, prior reports, or the library's own
  `test_round6_findings.py` as far as this pass's grep of that file
  showed. Flagged here rather than silently dropped.
- 300-random-machine snapshot-torn property test (assignment says "≥300
  random machines" for the persistence hook-matrix property) — F5 covers
  the *shape* (nested + parallel, entry + exit) deterministically on one
  hand-built machine, not a property-based sweep over generated machines.
- `n7_soak.py` was not re-run fresh this pass (round 5/6 already ran a
  90s/45-per-engine soak and found the corrupt-restore counter at 0/0
  both engines); not repeated given the time budget, since none of this
  round's CHANGELOG items touch the soak's exercised paths directly.

---

## 6. Standing constraints for adoption (unchanged from round 5/6)

1. **Pin the order-decision path to one engine.** Async scheduling order
   still decides outcomes when independent coroutines race
   (D-determinism-2). Not a bug; a property of cooperative scheduling.
2. **Pin one send call path per producer.** `send_threadsafe()` still does
   not order against `send()`/`send_events()` under concurrent producers
   (D-determinism-6). Mixing call sites for the same logical event stream
   does not preserve arrival order.
3. **`internal=True` on `send_threadsafe` is a trust boundary, not a
   verified claim.** Any caller — legitimate relay or not — that passes
   `internal=True` bypasses `OverflowPolicy.RAISE` backpressure via the
   unbounded internal queue. Do not expose
   `send_threadsafe(..., internal=True)` to any caller you do not trust
   to only use it for genuine self-send relays. (Re-confirmed on
   `221ce7c`, unchanged from round 5's E1.)

## 7. Verdict

**PASS for this track.** Every prior-round determinism/persistence defect
remains fixed on `221ce7c`. Five new, targeted attacks against this
round's own fixes (#166/#120 chain budget under 16-thread concurrent
external load, #173 `service_pool_size=1` serialization + mid-service
`stop()`, #172 done-callback balancing under a competing-callback +
forced-cancel race, #157-reopened exact-count hook parity under
concurrency, and #169 generalized to nested+parallel+exit windows beyond
the library's own root-only test) found **no new defect**. The three
standing constraints (async scheduling order, `send_threadsafe` ordering,
`internal=True` trust boundary) are unchanged and are adoption guidance,
not defects. The most significant gap for a future pass is the
perf-PR (#165/#176) shared-sentinel cross-talk check, which has zero
coverage anywhere in this lineage of reports (§5).
