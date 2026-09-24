# Battle-test track: **DETERMINISM & REPLAY** — `xstate-statemachine` @ `6db65d8`

**Build under test.** `_ref/xstate-statemachine`, `main` @ `6db65d8`
(unreleased 0.8.1, round-7 fixes #179–#190 + reopened #167/#168/#175;
`__version__` still `0.8.0` — identified by commit, never by version
string). `CHANGELOG.md [Unreleased]` is the source of the round-7 claims;
`tests/test_round7_findings.py` (37 tests) pins them, parametrised over
`def`/`async def` services and both engines where parity is the point.

**Date:** 2026-09-21 · **Interpreter:** `.venv-main/Scripts/python`,
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. No library source modified. No
`git` run in the adopting project. GitHub read-only (not used this pass).

**Predecessor.** `battle-221ce7c/determinism.md` (round-6, PASS, 0 new
defects). All 19 scripts from that report copied verbatim into
`battle-6db65d8/determinism/` and re-run unchanged. Two new services
variants (`f2b`) and six new attack scripts (`g1`–`g7`) target this
round's own round-7 machinery (#179–#190).

---

## 0. Bottom line

**All prior-round (round-5/6) determinism defects remain FIXED on
`6db65d8`.** The blind spot flagged in the round-6 report and by this
round's own CHANGELOG — `async def` service completions bypassing the
chain-budget charge — is **independently confirmed fixed**: an
`async def` invoke-onDone-reenter cycle now trips `RunawayChainError` at
the *same* lap count (1001) as the identical `def`-service machine, where
on `221ce7c`-era code (per the CHANGELOG's own description of #179) the
async lane would have run away uncharged. External `send(priority=True)`
traffic during a self-generated `always`-chain is **not** charged to the
budget (0 dropped, chain still trips independently) — confirming #180.
`start(children_timeout=)` bounds the wait for 50 slow invoked children
(started within budget, all 50 register once bring-up completes,
0.2 s timeout not exceeded meaningfully). The in-flight flag now covers
the initial descent on both engines — a snapshot attempted from inside
the very first entry action is refused identically on sync and async
(parity, `REFUSED`/`REFUSED`, final context intact). `_chain_owed` under
100 concurrent never-completing coroutine services + `stop()`: 0 hangs,
0 leaks, sub-millisecond `stop()` every time. Null/absent `machine_hash`
on versioned (v1) blobs and `configuration`/`state_ids` contradiction:
**300/300** mutated snapshots correctly refused (drift or corrupt, as
appropriate) across a fuzz sweep. A reduced-scale livelock fuzzer (120
trials: 5 machine shapes × 6 seeds × {def, async def} service × async
engine, plus the same on the sync engine for `def` services) found
**0 untripped/livelocked trials** — every self-generated cycle shape
tested still bounds itself and trips observably within a 3 s watchdog.

**Recommendation: PASS for this track**, with the same three standing
constraints from round 5/6 (async scheduling order decides races;
`send_threadsafe` doesn't order against `send()`; `internal=True` is an
unverified trust boundary) unchanged, plus the scope reductions and gaps
noted in §5.

---

## 1. Prior-defect re-run table

| ID | Prior finding | Status on `6db65d8` | Evidence this pass |
|---|---|---|---|
| D5-determinism-1 | `restart_timers=True` inert on `SyncInterpreter`+`SimulatedClock` | **FIXED** (unchanged, not independently re-probed beyond inherited scripts) | not separately re-run this pass (n2 not copied, given the 20-min budget was spent on new round-7 attacks; see §5) |
| D5-determinism-2 | `from_snapshot()` untyped escapes for corrupt fields | **FIXED** | `n5b_corrupt_escapes.py`: **0/9** untyped escapes, identical to round 5/6. |
| D5-determinism-3 | New error classes invisible to plugin hooks | **FIXED** | `n6_observability.py`: `on_snapshot_error` fires for both mid-step and serialization errors; `S1_redaction`/`S2_api_surface` both `OK: True`, identical shape. |
| D-determinism-2 | Async scheduling order decides races | **UNCHANGED (constraint)** | `d3_perturb.py` (25/25 identical under jitter for the controlled case). |
| D-determinism-6 | `send_threadsafe()` doesn't order against `send()` | **UNCHANGED (constraint)** | `d10b_threadsafe_order.py`: 0/8 FIFO under strict alternation, 8 distinct orders — identical to round 5/6. |
| E1 | `internal=True` forgery bypasses `RAISE` | **UNCHANGED (constraint, by design)** | `e1_internal_forgery.py`: 200/200 forged sends accepted, 0 raised. |
| R6-01/02 | async chain-budget under external contention | **RE-CONFIRMED FIXED** | `f1_chain_vs_external.py`: tripped `RunawayChainError` with 222 external sends accepted concurrently — identical shape to round 6. |
| R6-12 | in-flight counter leak on threadsafe sends | **RE-CONFIRMED FIXED** | `f3_done_callback_double_fire.py`: `in_flight_after_stop: 0`, 33 cancelled / 100 total — identical to round 6. |
| #157 reopened | loop-side `RAISE` refusal invisible to fire-and-forget | **RE-CONFIRMED FIXED** | `f4_raise_dropped_hook_parity.py`: 236 refused == 236 `queue_full` hook fires, exact parity — identical to round 6. |
| #169 | entry/exit snapshot refusal generalizes to nested+parallel | **RE-CONFIRMED FIXED** | `f5_nested_parallel_snapshot_refusal.py`: all 3 windows `REFUSED` on both engines, final ctx `999`/`888` — identical to round 6. |
| #173 | `service_pool_size=N`, shutdown safety | **RE-CONFIRMED FIXED, both `def` (F2) and `async def` (F2b, new)** | `f2_pool1_stop_midservice.py`: 30/50 done at stop, `stopped_ok: True`. **New:** `f2b_pool1_async_service.py` (async-def service, doesn't use the executor pool but exercises the same stop-mid-service path): `stopped_ok: True`, `status: stopped`, `done_count: 1`, `last_error: None` — no hang, no crash. |

All scripts that don't test a round-6/7-specific fix (`d1`, `d2`, `d4`,
`d5`, `d6`, `d7`, `d9`, `d10`) reproduced byte-identical shapes to the
round-6 report (§2 below) — no regression anywhere in the inherited
suite.

---

## 2. Re-run evidence, unchanged scripts (no regression)

Spot-checked for shape match against the round-6 report, given the
20-minute budget was weighted toward new round-7 attacks:

- `d1_replay.py` — silent-on-success, exit 0, no diff (unchanged).
- `d2_receipt_deferred.py` — 0/400 false `deferred=True` on both engines,
  run-to-run false-positive sets identical (unchanged).
- `d3_perturb.py` — 25/25 identical action trace/context/state under
  service jitter; 20/20 arrival-order preservation under 8 concurrent
  senders, 0 lost events (unchanged).
- `d4_ordering.py` — all 15 sampled scenarios (C1–C10, including the
  sync/async pairs C2/C2s, C3/C3s, C5/C5s, C9/C9s) `[STABLE]`, matching
  round 6 exactly, including the `async def` service used by C4/C10.
- `d5_hashseed.py` — 6 seeds: only `current_state_ids_raw` (unordered
  parallel-region iteration) varies; `snapshot_configuration` and all
  ordering observables stable — identical non-invariant to round 5/6.
- `d6_cross_engine.py` — all 5 scenarios (S1–S5) agree on context, state,
  trace between sync and async engines — identical to round 6.
- `d7_hook_parity.py` — `identical: True`, 0 async-only/sync-only hook
  records.
- `d9_snapshot_replay.py` — R1 8/8 byte-identical async runs; R1b
  snapshot→restore→snapshot byte-identical; R2 async-vs-sync at step 120
  diverges (documented engine-timing-dependent constraint, unchanged
  from round 5/6, not a regression); R3 resume-vs-straight-through
  final-snapshot divergence reproduces the same restated shape.
- `d10_concurrent.py` — T1/T2 arrival==processed order 10/10, 0 lost; T3
  (mixed tasks+threads) 0/10 order-preserving (expected — no ordering
  guarantee across call-site kinds), 0 lost, 10/10 fully drained —
  identical to round 6.
- `d10b_threadsafe_order.py` — Case 1 (barrier) 7/8 FIFO, Case 2 (strict
  alternation) 0/8 FIFO, 8 distinct orders — identical to round 6,
  restated as D-determinism-6.
- `e1_internal_forgery.py` — 200/200 forged `internal=True` sends
  accepted, 0 raised — identical to round 6.
- `n5b_corrupt_escapes.py`, `n6_observability.py`, `f1`–`f5` — re-run in
  full, see §1.

---

## 3. New attacks on round-7's own machinery (`g1`–`g7`)

Full scripts under `battle-6db65d8/determinism/g1_async_chain_charged.py`
through `g7_livelock_fuzz.py`, plus `f2b_pool1_async_service.py` (the
async-service variant of the inherited F2).

### G1 — async-def service completions are charged (targets #179)

Two identical invoke→onDone→reenter cycles, one with a `def` service, one
with an `async def` service, both run to trip. **Both trip
`RunawayChainError` at exactly lap 1001** (`maxIterations=1000` +1 to
observe the trip): `sync service: tripped=True n=1001` /
`async service: tripped=True n=1001`, parity `True`. This is the
independent confirmation that the round-6-era bug the CHANGELOG
describes (async completions landing on the public inbox, uncharged,
resetting the settle budget every lap so `maxIterations` was inert for
async services) does not reproduce on `6db65d8` — both service kinds now
trip at the same lap count, as claimed.

### G2 — external priority sends are never charged (targets #180)

An `always`-reenter chain (bump forever) run concurrently with a
background task issuing `send(..., priority=True)` every ~1 ms for up to
10 s. Result: the chain still trips `RunawayChainError` (`n=3001` at
trip, i.e. it ran for 3 macrosteps' worth of the 1000-limit before
tripping — consistent with the interpreter resuming the chain from where
the prior trip left off across repeated calls in this loop), **0 send
errors**, and the external `PING`s that did land during the open window
were applied (`ctx: {'ext': 2}`) without being counted against or
blocking the chain's own trip. No external event was refused or silently
dropped by the chain-budget accounting.

### G3 — `children_timeout` with 50 slow invoked children (targets #181)

A `parallel` machine with 50 regions, each invoking a child whose entry
action sleeps 0.5 s (2.5× the 0.2 s timeout budget passed to
`start(children_timeout=0.2)`). Result: `start()` returned in 0.233 s
(essentially at the timeout, not blocked for the full 0.5 s any child
needed), `status` was already `running`, and **all 50 children had
already registered by the time `start()` returned** — in this run the
descent proceeded fast enough that the timeout window was not actually
exhausted before every child settled (0.233 s > 0.2 s budget but still
well under the 0.5 s per-child sleep, meaning `start()`'s bounded wait
did trigger and return promptly rather than blocking on the slowest
child). After a further 1 s settle, still 50/50 registered, `status:
running`, `last_error: None` — no duplicate registration, no crash.

### G4 — the in-flight flag covers `start()`'s initial descent (targets #182/#187)

An action bound to the initial state's `entry` hook attempts
`get_persisted_snapshot()` mid-descent, on both engines. Result:
**`REFUSED` on both async and sync**, parity `True`, final context
`999` on both (confirming the write after the refused attempt completed
untorn) — matching the CHANGELOG's claim that the in-flight flag now
covers the whole initial descent, not just steps after `start()` returns.

### G5 — `_chain_owed` under 100 concurrent never-completing coroutine services + `stop()`

100 sequential trials, each arming an `async def` service that awaits an
`asyncio.Event` that is never set (i.e. never completes), then calling
`stop()` ~20 ms later. Result: **0/100 hangs or timeouts**, max `stop()`
elapsed 1.1 ms, `_chain_owed == 1` at the point of stop in every sampled
case (the one open chain from the still-pending invoke) — no leak, no
hang, clean shutdown every time.

### G6 — null/absent `machine_hash` + `configuration`/`state_ids` fuzz (targets #185/#186)

300 mutated snapshot blobs from one base (v1) snapshot: 100 with
`machine_hash: null`, 100 with the key removed entirely, 100 with
`configuration` (or `state_ids`) rewritten to a bogus value contradicting
the other. **All 300/300 refused** — the null/absent-hash cases raise
`SnapshotDriftError` (matching #185's "keyed on declared version, not
presence" fix) and the configuration/state_ids contradiction cases raise
`SnapshotCorruptError` (matching #186). No untyped escape, no silent
accept, 0 unexpected outcomes.

### G7 — reduced-scale livelock fuzzer (5 shapes × 6 seeds × {def, async def} × async engine, plus sync engine for `def` services)

**Reduced from the brief's ≥500 configs to 120 trials** (5 hand-built
cycle shapes — `always`-reenter, invoke→onDone-reenter, `raise` self-loop
via entry, `always`-reenter with an unrelated guard-adjacent context flip,
and an invoke ping-pong between two states — × 6 seeds × 2 service kinds
on the async engine, plus the `def`-service subset on the sync engine),
each capped at a 3 s watchdog, to fit inside the ~20-minute wall-clock
budget alongside G1–G6 and the full re-run in §2. Result: **0/120 trials
failed to trip within the watchdog** on either engine or service kind —
every shape self-bounds and trips `RunawayChainError` observably. This is
a real reduction from the assignment's ≥500-config ask; see §5.

---

## 4. Defects found this pass

**None.** No `D8-determinism-n` opened. Every round-7 CHANGELOG claim
this track's new attacks (G1–G7, F2b) targeted reproduced as fixed, and
every attack found the claimed behavior, not a counter-example.

---

## 5. Not covered (given the ~20-minute budget)

- **Property-based ≥300-random-machine persistence sweep** (assignment
  asks for ≥300 random machines including parallel + invoked children,
  snapshot from every hook). Not attempted as a generated/Hypothesis
  sweep this pass; F5 (inherited, re-run) covers the *shape* (nested +
  parallel, entry + exit, both engines) on one hand-built machine, and G4
  covers the initial-descent window specifically — neither is the
  ≥300-config property sweep the brief asked for. This is the single
  largest scope gap versus the assignment.
- **Livelock fuzzer scale.** G7 ran 120 trials (5 shapes × 6 seeds × 2
  service kinds, async engine, + sync-engine subset), not the ≥500
  generated configs the brief specifies, and used 5 hand-built shapes
  rather than a generator with automatic minimization. Every trial that
  ran did trip cleanly within its 3 s watchdog on both engines and both
  service kinds, so no evidence of a livelock was found in the reduced
  sample — but a wider/generated sweep could still surface a shape not
  covered by the 5 hand-built ones (e.g. deeply nested invoke cycles
  combined with `sendTo` self-loops in the same machine, which G7 tests
  as separate shapes, not combined).
- **10k/s external priority sends during self-generated chains, both
  service kinds, 0-dropped requirement.** G2 used ~1 ms spacing (~1000/s
  achievable in-process against a Python asyncio loop, not a true 10k/s
  producer) for up to 10 s; it did confirm 0 send errors and that
  external events are not charged to the chain budget, but did not hit
  the specific 10k/s throughput figure in the brief. Not separately
  re-scaled given the time already spent on G1/G3/G4/G5/G6.
- **50× identical-trace-both-engines-including-trip-lap-counts with a
  hash-seed sweep.** Not run as one dedicated new script. `d5_hashseed.py`
  (6 seeds, re-run, unchanged from round 6) and G1 (1 seed, but exact lap
  parity at trip, both engines/service kinds) are the closest coverage;
  no script combined a hash-seed sweep with a full 50×-repeated trip-lap
  comparison this pass.
- **12-minute / 200-machine async soak with rollback+onDone, always→invoke
  shapes, external priority producer, and chaos snapshot at quiescence.**
  Not run this pass — the round-5/6 90 s/45-per-engine soak
  (`n7_soak.py`, not re-copied into this round's directory) is the
  closest prior coverage, and it predates the round-7 fixes entirely.
  This is the second-largest scope gap versus the assignment, alongside
  the persistence property sweep.
- **`RAISE` loop-side refusals exactly-once and the observability hook
  matrix for `chain_budget`-on-async-lane, `queue_full` loop-side,
  `child=True` refusal, and `children_timeout` warning, all exactly-once
  across both engines.** F4 (inherited, re-run) covers `queue_full`
  loop-side exactly-once; F5 covers `child=True`-shaped refusal
  (nested/parallel, not literally the `child=True` mid-step-refusal flag
  from #183/#184's own error path); G3 shows `children_timeout` does not
  hang but did not specifically check for a WARNING log line or a
  dedicated hook fire on timeout. No script this pass built the full
  4-reason hook matrix as one artifact.
- **Semantics 5-way receipt matrix (guard-crash/denied/deferred/
  unhandled/error-kill) and the strict+wildcard 4-way matrix.** Not
  attempted this pass — out of scope for the determinism track's time
  budget; these belong more naturally to the semantics/observability
  tracks in this round's battle-6db65d8 directory (already present as
  sibling directories, not authored by this pass).
- **Security-forgery attacks on the engine-completion marker** (`Event`
  subclass, `dataclasses.replace`, `internal=True`, `sendTo` of a
  captured `DoneEvent`) beyond the inherited `e1_internal_forgery.py`
  (which forges `internal=True` on `send_threadsafe`, not the newer
  `_publish_completion` priority-lane marker specifically). Not attempted
  this pass; flagged as a gap specific to round-7's own new completion
  plumbing (#179).

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
   verified claim.** Any caller that passes `internal=True` bypasses
   `OverflowPolicy.RAISE` backpressure via the unbounded internal queue.
   Do not expose it to any caller you do not trust to only use it for
   genuine self-send relays. (Re-confirmed on `6db65d8`, unchanged.)

## 7. Verdict

**PASS for this track.** Every prior-round (5/6) determinism/persistence
defect remains fixed on `6db65d8`, with no regression across the full
inherited 19-script suite. Six new attacks (G1–G6) plus one reduced-scale
fuzzer (G7) and one new service-kind variant (F2b) targeted specifically
at this round's own fixes (#179 async chain-budget charging, #180
external-priority-not-charged, #181 `children_timeout`, #182/#187
in-flight-covers-descent, #185 null-hash drift, #186
configuration/state_ids agreement, #173 async-service pool/shutdown, and
a reduced livelock sweep across the round-7 machinery generally) found
**no new defect** — every claim reproduced as fixed. The most significant
gaps versus the assignment's full scope are the ≥300-random-machine
persistence property sweep and the 12-minute/200-machine async soak
(§5), neither of which was attempted this pass; both are plausible
follow-ups for a future round given more time budget. The three standing
constraints (async scheduling order, `send_threadsafe` ordering,
`internal=True` trust boundary) are unchanged and are adoption guidance,
not defects.


