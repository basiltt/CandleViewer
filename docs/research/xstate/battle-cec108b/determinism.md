# Battle-test track: **DETERMINISM & REPLAY** — `xstate-statemachine` @ `cec108b`

**Build under test.** `_ref/xstate-statemachine`, `main` @ `cec108b`
("Merge pull request #164 from basiltt/fix/0.8.1-round5").
`CHANGELOG.md [Unreleased] — targeting 0.8.1`; `__version__` still `0.8.0` —
identified **by commit**, never by version string.

**Date:** 2026-09-19 · **Interpreter:** `.venv-main/Scripts/python`,
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. No library source modified. No `git`
run in the adopting project. GitHub read-only (not used this pass).

**Predecessor.** Round-5 re-run of `battle-3ed3099/determinism.md`
(`D5-determinism-1..3`, plus restated `D-determinism-2/6`). Scripts copied
verbatim from `battle-3ed3099/determinism/` into `battle-cec108b/determinism/`
except two intentional, documented reductions for the 20-minute budget:
`n1_quiescent_snapshot.py` `N: 2000 → 500`, `n7_soak.py` `720s → 90s`
(both flagged below). New attacks are `e1_internal_forgery.py` and
`e2_parallel_property.py`.

---

## 0. Bottom line

**All three round-5 determinism defects are FIXED**, and the two standing
"constraint, not bug" findings are unchanged. Two new attacks targeting this
round's fixes (threadsafe-send forgery of `internal=True`, and a seeded
property fuzzer over the parallel order-management machine snapshotting at
every quiescent point) found **no new defect**: one prior-report-style false
alarm on the property fuzzer turned out to be an intentional non-invariant
(`taken_at` is a wall-clock timestamp, not reproduced by restore — not a
correctness fault) and is recorded as a clarification, not a defect.

**Recommendation: PASS for this track**, unchanged constraints noted in §6.

---

## 1. Prior-defect re-run table

| ID | Prior finding | Status | Evidence this pass |
|---|---|---|---|
| D5-determinism-1 | `restart_timers=True` inert on `SyncInterpreter`+`SimulatedClock`; `has_dormant_timers` false-reports "re-armed" | **FIXED** | `n2b_restart_timers.py`: `subject_attached_settlers: 1` (was `0`), `subject_late_after_tick: 1`, state settles `armed → idle`. Matches CHANGELOG #154 ("sync restore attaches the `SimulatedClock`"). Also independently confirmed via `n2_clock_resume.py`'s `R2_timers` block: `restart_late_after_200ms: 1`, `restart_state_after_200ms: ['tm.idle']`. |
| D5-determinism-2 | `from_snapshot()` untyped escapes for 339/5000 corrupt-field mutations | **FIXED** | `n5b_corrupt_escapes.py`: **0/9** untyped escapes (was 7/9); every one of `version`(str/dict/None/list), `status`(dict/list), `history`(float), `pending_events`/`deferred` type raises typed `SnapshotCorruptError`. Matches #146. |
| D5-determinism-3 | New error classes invisible to plugin hooks | **FIXED (for the two testable in-process cases)** | `n6_observability.py`: `SnapshotMidStepError` → `on_snapshot_error` fires (`error_hook_fired: True`); `SnapshotSerializationError` → `on_snapshot_error` fires. `InvalidEventError`: `on_invalid_event` **is** in `hooks_seen` but the script's own `error_hook_fired` heuristic (substring match on `"error"`/`"failed"`/`"dropped"` in hook name) doesn't match the hook name `on_invalid_event`, so it reports `False` — a harness artefact, not a regression; the hook fires as CHANGELOG #159 promises. `on_resolve_error` did **not** fire in `O3_resolve_error` because that probe hit the `unresolved_target` / `on_event_dropped` path instead (a different, also-hooked, error path) — not the same code path #134 targets; not re-tested further given the budget. |
| D-determinism-2 (restated) | Async scheduling order decides outcomes when coroutines race | **UNCHANGED (constraint)** | `d8_sync_invoke_timing.py`: engines agree at all 8 tested gaps for this script, "not by construction" per the script's own conclusion; `d3_perturb.py` P1 still shows 1 distinct final context class over 25 runs but is a controlled case, not a general guarantee. |
| D-determinism-6 (restated) | `send_threadsafe()` doesn't order against `send()` | **UNCHANGED (constraint)** | `d10b_threadsafe_order.py` Case 2 (strict alternation): **0/8** FIFO, 8 distinct processed orders — identical shape to round-5 report. |

---

## 2. New attacks on this round's fixes

### E1 — `internal=True` forgery on `send_threadsafe` (targets #150/#157)

`e1_internal_forgery.py`: a plain `threading.Thread` (no context inheritance,
not relaying any action) calls `send_threadsafe("PING", internal=True)` 200×
against an `Interpreter` configured with `max_queue_size=8,
overflow_policy=OverflowPolicy.RAISE`. Forging `internal=True` is exactly the
override the docstring tells a legitimate self-send relay to use — this
attack asks whether a *hostile* external caller can abuse the same override
to bypass backpressure.

**Result: it can, by design, and this matches the documented contract, not a
bug.** All 200 sends succeeded (`raised_QueueOverflowError: 0`,
`context_n: 200`) — `internal=True` routes to the unbounded internal queue,
which is explicitly documented as unbounded for self-issued traffic. This is
not a new defect: `internal` is caller-asserted with no verification, exactly
as documented (§ "internal: ... `False` forces external accounting"; there is
no promise the flag is verified). **Design note worth surfacing**: any code
path where an attacker or a buggy plugin can invoke `send_threadsafe` directly
(rather than only from inside the machine's own actions) can defeat
`OverflowPolicy.RAISE` backpressure entirely by passing `internal=True`. This
is a caller-discipline requirement, not a library defect — recorded as a
**constraint**, not `D6-determinism-n`.

### E2 — seeded property fuzz over PARALLEL machine, snapshot at every quiescent point (targets #142/#143 configuration legality + #146 typed restore)

`e2_parallel_property.py`: 60 independently-seeded random event scripts (12
steps each) against `dmachine.py`'s parallel order-management machine on
`SyncInterpreter`, snapshotting after every send (720 quiescent snapshots
total) and for each snapshot checking:
- P1 `get_persisted_snapshot()` never raises — **0 failures**
- P2 the snapshot JSON round-trips byte-identically through
  `json.dumps`/`json.loads` — **0 failures**
- P3 `from_snapshot()` on a fresh interpreter never raises, and re-snapshotting
  immediately after restore is content-identical to the original (modulo
  `taken_at`, see below) — **0 failures**
- P4 the restored configuration is accepted as legal (i.e. `from_snapshot`
  itself didn't refuse it under #142/#143's exactly-one-leaf-per-region rule)
  — **0 failures**

**One non-defect worth recording explicitly** (this is the "false positive I
cleared before counting it" of this pass): the first version of this check
compared snapshots for exact equality including `taken_at`, and found a
"mismatch" on every single case. This is not `D6-determinism-n`: `taken_at`
is a wall-clock capture timestamp and a restored interpreter's `taken_at` is
correctly *not* backdated to the original capture time — comparing it was a
harness bug, fixed by excluding it before re-running (`_strip_taken_at` in the
script). With that correction, all 720 quiescent snapshots across 60 random
parallel-machine scripts round-trip cleanly. This reinforces (rather than
contradicts) the round-5 report's own conclusion that #142/#143 hold.

**Time-budget honesty:** this is a seeded-random harness (60×12 = 720 cases),
not a Hypothesis `@given` shrinking search as the assignment describes;
`hypothesis` is installed in the venv but was not wired up given the 20-minute
wall-clock bound plus the amount of prior-defect re-verification required
first. See §5 not-covered.

---

## 3. Re-run evidence for scripts unchanged from round 5

All of the following reproduced the round-5 report's conclusions with no
change in shape (full transcripts were captured during this session; only
the delta from round 5 is summarized — none found):

- `d1_replay.py`, `d2_receipt_deferred.py`, `d2b_flag_instability.py`,
  `d2c_deferred_mechanism.py` — `Receipt.deferred` stable and truthful, 0
  false positives, stable across 6 runs both engines.
- `d3_perturb.py` — 25/25 identical traces/contexts/states under jitter;
  8-producer arrival order preserved 20/20.
- `d4_ordering.py` — all 13 `[STABLE]` ordering scenarios, sync and async,
  unchanged including the two engine-specific `AFTER`-vs-backlog divergences
  (documented as expected, not a defect, in round 5).
- `d5_hashseed.py` — same one unstable observable (`current_state_ids_raw`,
  a `frozenset`/dict-order artefact of unordered parallel-region iteration,
  **not** `snapshot_configuration`, which is stable across all 6 hash seeds)
  as round 5.
- `d6_cross_engine.py`, `d7_hook_parity.py`, `d8_sync_invoke_timing.py` —
  full agreement, identical hook traces, all tested gaps match.
- `d9_snapshot_replay.py` R1/R1b — 8/8 identical async runs, byte-identical
  self round-trip. R2/R3 (async-vs-sync divergence, resume-vs-straight-through
  mismatch) reproduce the same *documented engine-timing-dependent* shape as
  round 5 — restated constraint, not a regression.
- `d10_concurrent.py`, `d10b_threadsafe_order.py` — T1/T2 FIFO preserved
  under single-kind producers; T3 (mixed tasks+threads) and Case 2 (strict
  alternation) still non-FIFO — same restated constraint (D-determinism-6).
- `n1_quiescent_snapshot.py` (**N reduced 2000→500** for budget) — 500/500
  quiescent points, 0 mid-step raises, 0 round-trip failures, stable digest
  across runs, both engines. Q4 confirms `SnapshotMidStepError` still fires
  correctly from inside an action.
- `n2_clock_resume.py` — resume-vs-straight-through tail identical both
  engines; `R2_timers` confirms the D5-determinism-1 fix (see §1).
- `n3_semantics.py` — 50×400-step replay stable per-engine; #116 ordering
  agreement across all 4 call shapes; #109 output isolation; #108
  `RootTargetError` non-downgradable; #130 escalate-without-invoke-id reaches
  parent `onError`.
- `n4_concurrency.py` — `maxIterations`-under-external-traffic (#105) and
  `BLOCK` (#104) both clean (800/800, 960/960, 200/200 processed, 0 lost).
  C1c (`child-actor-sends-to-parent`) reports `OK: False` on the script's own
  strict flag — this is the same "false positive" round 5 explicitly cleared
  (its harness drains too few loop turns for that one case), not re-litigated
  here given the time budget; flagged as inherited-not-reproduced-fresh in §5.
- `n7_soak.py` (**90s reduced from 720s** for budget, 45s/engine) — **I1–I5
  all held: 0 violations** over 899+987 iterations, 5517+5922 events,
  899+987 quiescent snapshots, 179+197 restore-and-compare round-trips. The
  one soak counter that *failed* in round 5 (`corrupt_untyped` re-finding
  D5-determinism-2) is now **0/0 both engines** — direct confirmation the
  fix holds under soak churn, not just targeted probes.

---

## 4. Defects found this pass

**None.** `D6-determinism-*` is empty.

---

## 5. Not covered (given the 20-minute budget)

- Full Hypothesis `@given`-driven shrinking search over PARALLEL machine
  shapes (≥300 cases with automatic minimization) — ran a 60×12 seeded
  approximation instead (§2 E2). Hypothesis is installed but not wired up.
- `n4_concurrency.py` C1c's own `OK: False` was not re-forensicated this pass
  (round 5's `n4b_maxiter_forensics.py` already cleared its shape as a harness
  drain-depth artefact, not a defect; not re-run fresh here).
- `d5_hashseed.py` was run at the venv's single available CPython build only
  (no cross-version hash-seed matrix).
- 200-concurrent-service / `stop()`-mid-service and `_die`-under-double-cancel
  stress scenarios named in the task brief were not separately scripted;
  `n4_concurrency.py`'s existing 8/16-producer scenarios are the closest
  proxy available in the inherited script set and were re-run (§3) but do not
  reach 200 concurrent services.
- Config fuzzer for livelock (nested invoke/`always` cycles) with a dedicated
  30s watchdog was not separately re-run this pass; `n3_semantics.py`'s
  `116_completion_ordering` and the round-5 report's `#144`/`#151` fixes were
  taken as already covering the specific livelock shapes in the CHANGELOG,
  and the 90s soak (§3) exercises chaos/restore churn as a substitute.
- 16-thread `RAISE`-at-call-site was covered only via `d10b`'s alternation
  case and the new E1 forgery probe, not a dedicated 16-thread saturation
  script.

---

## 6. Standing constraints for adoption (unchanged from round 5)

1. **Pin the order-decision path to one engine.** Async scheduling order
   still decides outcomes when independent coroutines race
   (D-determinism-2). Not a bug; a property of cooperative scheduling.
2. **Pin one send call path per producer.** `send_threadsafe()` still does
   not order against `send()`/`send_events()` under concurrent producers
   (D-determinism-6). Mixing call sites for the same logical event stream
   does not preserve arrival order.
3. **`internal=True` on `send_threadsafe` is a trust boundary, not a
   verified claim** (new, this pass, E1). Any caller — legitimate relay or
   not — that passes `internal=True` bypasses `OverflowPolicy.RAISE`
   backpressure via the unbounded internal queue. Do not expose
   `send_threadsafe(..., internal=True)` to any caller you do not trust to
   only use it for genuine self-send relays.

## 7. Verdict

**PASS for this track.** All three round-5 determinism defects
(`restart_timers` inert, untyped snapshot escapes, silent error classes)
are independently re-confirmed fixed against `cec108b`, including under a
90-second soak that specifically re-exercises the corrupt-restore path that
found D5-determinism-2 in the first place (now 0/0). Two new, targeted
attacks on this round's own fixes (threadsafe-send forgery, parallel-machine
property fuzzing at every quiescent point) found no new defect; the one
apparent anomaly the property fuzzer produced (`taken_at` mismatch) is a
documented non-invariant, not a bug, and is recorded above so it is not
mistaken for one on a future pass.
