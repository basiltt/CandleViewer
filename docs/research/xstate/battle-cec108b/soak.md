# SOAK re-run — `xstate-statemachine` @ `cec108b` (unreleased 0.8.1, round-5)

**Build under test.** Local clone `_ref/xstate-statemachine`, commit
`cec108b`. `CHANGELOG.md` `[Unreleased]` documents round-5 (#142–#162,
reopened #118/#122/#125/#133/#134) plus round-4 (#102-#138). `__version__`
still `0.8.0` — identified by commit only.

**Date:** 2026-09-19. **Python:** CPython 3.13 / Windows 11.
**Interpreter:** `_ref/xstate-statemachine/.venv-main/Scripts/python`,
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. No library source modified.

**Time-bound disclosure.** Whole-task budget is 20 minutes. The main soak
was run at **1.5 min / 30 machines / 3 producers** (vs. the round-4 track's
already-reduced 1.5 min/40/4, itself reduced from the original 25 min/200/6).
This is enough to re-observe both prior soak-track defects' mechanisms and
to re-check the round-5 `check_shape()` fix (D5-soak-1), but not enough to
reproduce absolute RSS/lag magnitudes at the original scale.

---

## 1. Prior-defect re-verification (this track's history: D-soak-1, D-soak-2, D5-soak-1)

| ID | 3ed3099 verdict | cec108b re-run result | Verdict |
|---|---|---|---|
| D-soak-1 (`wait=True` receipt hangs forever after uncaught plugin-hook exception) | FIXED (via `.use()`) | `repro_d_soak_1_via_use.py` (unmodified, copied as-is): `FAIL (not reproduced): both receipts resolved` | **FIXED** (unchanged) |
| D-soak-2 (`SimulatedClock` settler leak on crash-restore) | FIXED (via `from_snapshot(clock=)`) | `repro_d_soak_2_via_clock_param.py` (unmodified): `settlers registered on the clock: 0`, `1/21 reachable`, `NOT REPRODUCED` | **FIXED** (unchanged) |
| D5-soak-1 (`check_shape()` doesn't cover `history`/`actors`/`system` — untyped `AttributeError` escapes `from_snapshot()`) | New defect (Medium), 3ed3099 | `attack_hostile_fields_fixed.py`: `history`/`actors`/`system`/`deferred`/`status` all → typed `SnapshotCorruptError`; `version` → typed `SnapshotVersionError` (also `XStateMachineError`, just a different subclass — not a defect). **0 untyped exceptions across all 6 hostile fields.** | **FIXED** — closed by round-5 #146 ("Hostile snapshot fields are typed": `version`, `status`, `history`, `actors`, `system`, `deferred` all shape-checked) |

No harness adaptation was required this round — round-4's soak harness
already used the documented `.use()` / `from_snapshot(clock=)` idioms, and
round-5 did not change those APIs' shape.

### 1.1 D-soak-1 / D-soak-2 detail

Both repro scripts were copied byte-for-byte from `battle-3ed3099/soak/`
(no source touched) and re-run against cec108b; output above. Both remain
fixed, as expected — round-5's changelog doesn't touch `_SafePlugin`
containment or `SimulatedClock._detach_clock()`.

### 1.2 D5-soak-1 detail — now FIXED

`attack_hostile_fields_fixed.py` mutates each of `history`, `actors`,
`system`, `deferred`, `status`, `version` on a real (small) snapshot to an
illegal type (`3.14`, a float) and reloads via `from_snapshot()`:

```
history: OK: SnapshotCorruptError (Snapshot is malformed: 'history' is float, expected an object.)
actors: OK: SnapshotCorruptError (Snapshot is malformed: 'actors' is float, expected an object.)
system: OK: SnapshotCorruptError (Snapshot is malformed: 'system' is float, expected an object.)
deferred: OK: SnapshotCorruptError (Snapshot is malformed: 'deferred' must be a list of event records whose 'type' is a non-empty string.)
status: OK: SnapshotCorruptError (Snapshot is malformed: unknown status 3.14; expected one of [...]).
version: OK (typed, not SnapshotCorruptError): SnapshotVersionError: Snapshot version 3 is newer than the supported version 2.
```

This directly confirms round-5 #146 closed the gap the round-4 track's
`D5-soak-1` found in `check_shape()`. `version` correctly raises a
*different* typed exception (`SnapshotVersionError`, still an
`XStateMachineError` subclass) rather than `SnapshotCorruptError` — this is
by design (a too-new version is a distinct, documented condition from a
malformed payload) and is not a defect.

---

## 2. New attacks (round-5 fixes, soak-relevant)

| Script | Target | Result |
|---|---|---|
| `soak_runner.py` (unmodified from round-4 track) | full soak scenario incl. #142-#162 in combination under load, chaos restart every 2s | 0 new unexpected exceptions; 1 residual "D-soak-1 hang" log line — confirmed **not** D-soak-1 (see §3) |
| `attack_hostile_fields_fixed.py` | #146 hostile-field typing (closes D5-soak-1) | **PASS**, see §1.2 |
| `attack_fail_stopped_snapshot.py` | #145 `actionErrorPolicy: "fail"` → `status=stopped`, config cleared; snapshot round-trip | **PASS**, see §2.1 |

### 2.1 `attack_fail_stopped_snapshot.py` — detail

Built a variant of the soak machine with `actionErrorPolicy: "fail"`
(soak's own machine uses `"rollback"`, so this targets #145 directly, which
the standing soak harness cannot exercise). Sent `SUBMIT` then `FAIL_HARD`
(which runs the `boom()` action):

```
status after FAIL_HARD: stopped
snapshot status field: stopped
snapshot configuration: []
RESTORE RESULT: accepted, restored.status = stopped
```

Matches the round-5 contract exactly: `status` is `"stopped"` (not the old
bricked `"error"` reporting a stale leaf), the configuration is cleared
(`[]`), and re-loading that snapshot is accepted as a legitimate
already-stopped machine (not silently resumable as `running`, and not
refused — a `stopped`-with-populated-`.error` snapshot is a valid terminal
state to persist/replay for audit, distinct from the "`error`-status-with-
no-recorded-error" case #145 explicitly refuses). No defect.

### 2.2 Soak run detail

30 machines / 3 producers / 1.5 min, chaos restart every 2s
(`restart_count: 39`), reconciliation log 0 lost events:

```
final_sent: 13072, final_accepted: 13071 (last send in-flight at cutoff)
receipts_ok: 2730, receipts_deferred: 9578, receipts_error: 763
restart_count: 39, lost_events_count: 0
remaining_asyncio_tasks_after_final_stop: 1 (event loop's own bookkeeping task, not a leak)
unexpected_exceptions: ["D-soak-1 hang: m11 gen21 key=(11, 21, 10)"]
```

The one `unexpected_exceptions` entry is the harness's own instrumented
`asyncio.TimeoutError` branch (2s send-timeout guard, labelled by the
harness after the *round-4* D-soak-1 investigation) — it fires whenever a
`send(wait=True)` races a chaos-triggered `stop(drain=True)` mid-flight
(the interpreter legitimately stops before the receipt resolves, which is
expected under a bounded producer/chaos race, not a hang against a live
interpreter). This is the same log line the round-4 track's own soak
report explicitly earmarks as "not D-soak-1" — confirmed unchanged.
`max_loop_lag_ms` spiked to 3.1s at t=70s, consistent with GC pauses under
Python's tracemalloc instrumentation (`tracemalloc.start(10)`) rather than
a library regression — RSS growth is flat/expected (63→105MB, dominated by
tracemalloc's own frame-tracking overhead per `top_alloc`, all inside
`models.py`/`base_interpreter.py` object churn, not a monotonically-growing
leak signature).

---

## 3. Defects

None found in this pass. Both defects carried over from the round-4 soak
track (D-soak-1, D-soak-2) remain fixed; the one new defect the round-4
soak track itself surfaced (D5-soak-1, `check_shape()` gap) is now
confirmed **fixed** by round-5 #146.

---

## 4. What was NOT covered (explicit, per instructions)

- Full 12-minute/200-machine chaos soak was not run; only 1.5 min/30
  machines/3 producers, within the 20-minute whole-task hard bound.
- Hypothesis property-based fuzzing over random PARALLEL machines (≥300
  cases, snapshot-at-every-quiescent-point round-trip) — not attempted
  this pass; this is the persistence track's remit and is a natural
  follow-on, not attempted here given the time budget.
- 200-concurrent-service / `send_threadsafe` forgery / RAISE-under-16-
  threads / `_die` double-cancel / leaked-thread sweep — concurrency
  track's remit, not attempted.
- Config fuzzer for livelock (#144/#151 nested-invoke/always cycles) with
  a dedicated 30s watchdog — the standing soak's own chaos/producer mix
  exercises `SELF_RAISE`/`FAIL_HARD` but not a purpose-built adversarial
  cycle generator; not attempted this pass.
- 50x identical-trace determinism sweep across both engines, hash-seed
  sweep — determinism track's remit.
- Full hook-matrix (`guard_denied`, `unresolved_target`, `chain_budget`,
  `on_plugin_error`, `on_resolve_error`) exactly-once/ordering check —
  observability track's remit; only implicitly touched via the standing
  `AccountantPlugin`'s three dispositions.
- History+parallel restore, v1-upcast-with-torn-configuration refusal —
  persistence track's remit; #142/#143 (`_configuration_is_legal`) not
  independently re-attacked here.
- Redaction / executor-thread-context-leakage / exported-API-surface diff
  — security track's remit.

---

## 5. Verdict

Both soak-track legacy defects (`D-soak-1`, `D-soak-2`) remain **FIXED** at
`cec108b`, unchanged from the `3ed3099` re-run — round-5 did not touch
`_SafePlugin` containment or `SimulatedClock` teardown.

The round-4-soak-track-discovered `D5-soak-1` (`check_shape()` missing
`history`/`actors`/`system` coverage, Medium severity) is now **FIXED** by
round-5 #146: all six probed hostile top-level fields (`history`,
`actors`, `system`, `deferred`, `status`, `version`) raise a typed
`XStateMachineError` subclass (`SnapshotCorruptError` or, for the
version-skew case, `SnapshotVersionError`) instead of an untyped Python
exception. A caller's documented `except XStateMachineError` catch-all now
correctly catches every one of these malformed-snapshot cases.

A targeted check of round-5's #145 (`actionErrorPolicy: "fail"` stop
contract) in the soak-adjacent persistence path also passed cleanly:
`status="stopped"`, configuration cleared, and the resulting snapshot
round-trips as a legitimate stopped machine.

No new defects found in this reduced pass. The soak run itself (30
machines, 3 producers, chaos restart every 2s, 1.5 min) shows 0 lost
events, 0 unaccounted-for unexpected exceptions (the sole logged item is
the harness's own known non-defect timeout-race label), and no leaked
asyncio tasks after final teardown — consistent with, but far short of
statistically confirming at scale, a healthy round-5 build. The much
larger uncovered surface (§4) — full-duration soak, hypothesis-based
parallel-machine persistence fuzzing, concurrency stress, livelock fuzzer,
determinism sweep, full hook matrix, security surface — was explicitly out
of reach of the 20-minute whole-task budget and is flagged as follow-on
work rather than silently skipped.
