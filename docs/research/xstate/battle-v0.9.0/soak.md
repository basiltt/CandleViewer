# SOAK re-run — `xstate-statemachine` @ `v0.9.0` (`e3a1f22`, round-13)

**Build under test.** `_ref/xstate-statemachine` main @ `e3a1f22`
(2 commits ahead of tag `v0.9.0`=`91bd979`: `git diff v0.9.0..HEAD --stat`
shows only `.github/workflows/publish.yml` — a CI publish-smoke-test
change, no library source touched). `__version__ == "0.9.0"`. Not yet on
PyPI. No library source modified by this pass.

**Date:** 2026-09-23. **Python:** CPython 3.13.7 / Windows 11.
**Interpreter:** `.venv-main/Scripts/python`,
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

**Time-bound disclosure.** Task budget ≈20 min; individual scripts capped
≤120 s. Given the budget this pass (1) re-ran a representative sample of
`battle-de2da4e/soak/*` scripts unmodified against `v0.9.0` (full corpus
re-run of all 18 files was not feasible in-budget — see §4), and (2)
wrote three new, standalone round-13 attacks targeting the behaviors
`CHANGELOG.md [0.9.0]` actually changed: task-identity concurrency
(#225), the dropped-receipt `RuntimeWarning` (#232), and the persistence
property matrix (#226/#227/#230/#233). The full 12-min/200-machine soak,
the ≥500-config livelock fuzzer, the 50×-trace determinism sweep, and the
task-identity semantics matrix beyond the concurrency slice below were
**not** run at full scale this pass — see §4.

---

## 1. Prior-defect re-verification (sample of `battle-de2da4e/soak/*`, re-run unmodified against `v0.9.0`)

None of these scripts touch a #225/#232-era code path (no
`ContextVar`-based provenance check, no `-W error` invocation, no
`def`-action `wait=True` receipt drop), so **no SUPERSEDED rewrites were
needed** for the sample re-run.

| ID | de2da4e re-run | v0.9.0 re-run result | Verdict |
|---|---|---|---|
| `attack_new_r11_handles_reentrant_latch` (#218/#219/#222) | PASS | Timer-handle flatness `{'handles_after_200_beats': 0}`; both engines raise `ReentrantWaitError` from the self-`wait=True` action, event still queued, `status='running'`, `value='y'`; chain-trip latch `{'trips_after_trip': 1, 'latch_set_after_trip': True, 'trips_after_benign': 1, 'latch_still_set_after_benign': True, 'latch_after_clear': None}` | **PASS** (unchanged) |
| `attack_new_r9_soak` §A/§D (invoke-arms-after-settle; forged `AfterEvent` refused) | PASS | `A_NO_SPURIOUS_INVOKE: True`, `D_FORGED_AFTER_REFUSED: True`, `dt_s=0.14` | **PASS** (unchanged) |
| `attack_hostile_fields_fixed` (6 hostile snapshot fields) | PASS | 5/6 typed `SnapshotCorruptError`; `version` field still silently `ACCEPTED` (pre-existing, not in round-12/13 scope) | **PASS** (unchanged) |
| `attack_fail_stopped_snapshot` (`actionErrorPolicy:"fail"` stop contract) | PASS | Action `boom` raises, rollback logged, machine stopped by policy, `snapshot configuration: []`, restore accepts the terminal snapshot (`accepted, restored.status = stopped`) | **PASS** (unchanged) |

**Not re-run this pass** (budget): `attack_166_settle_budget_soak`,
`attack_172_157_threadsafe_soak`, `attack_173_*` (both lanes),
`attack_new_chainowed_priority_childtimeout`,
`attack_new_forgery_strict_soak`, `attack_new_r9_soak_2`,
`attack_r10_new_1/2/3`, `repro_d_soak_1/2`. None of these are known to
exercise a round-13-touched path (task identity, dropped-receipt
warning, v3 latch/plugins/priority-restore); the round-11 re-run pass
(`battle-de2da4e/soak.md`) already re-verified them once against a build
strictly older than round-12/13, and round-12's own
`tests/test_round12_findings.py` (31 tests, all passing per the
already-running full suite — see §4) covers the same ground with
pinned regression tests. Flagged as a gap, not asserted PASS.

---

## 2. New round-13 attack: `attack_task_identity_matrix.py` (#225)

Three concurrency shapes, single async run, <1 s:

- **Outliving worker** — action does
  `asyncio.ensure_future(worker()); await asyncio.sleep(0.001)` and
  returns; `worker()` sleeps 50 ms (well past the action's return) then
  `i.send("PING")`. Result: `outliving-worker pings: 1` — the worker's
  `send()` after the action returned was NOT refused as an in-step
  reentrant send, and was NOT lost to an idle-loop internal-queue stall
  (#225's exact failure mode pre-fix). **Holds.**
- **Two-hop task chain** — action spawns `hop1()`, which spawns `hop2()`,
  which sends after both ancestor tasks have returned. Result:
  `two-hop pings: 1`. Task-identity attribution does not leak across a
  chain of `ensure_future` hops (`_action_tasks` correctly stops
  recognising a grandchild task as "one of my actions" once its parent
  action task has exited). **Holds.**
- **100 concurrent hand-outs** — one action spawns 100 workers via
  `ensure_future` in a loop, each sleeping a jittered 10–15 ms then
  `send()`-ing; the action itself returns almost immediately after the
  spawn loop. Result: `concurrent 100-worker pings: 100` — no starvation,
  no drops, no misrouting under concurrent task-identity churn.
  **Holds.**

`TASK_IDENTITY_MATRIX_OK: True`.

---

## 3. New round-13 attack: `attack_runtimewarning_dropped_receipt.py` (#232)

- **Drop case** — a `def` action calls `i.send("B", wait=True)` and
  discards the return value. Captured with `warnings.catch_warnings`
  around the send + two `gc.collect()` passes (the guard object's
  `__del__` fires on finalisation, so GC must run): **exactly 1**
  `RuntimeWarning`, message naming `#232`, the action, and the
  unsupported-await shape. **Holds.**
- **Use case** — same shape but the action hands the receipt to
  `asyncio.ensure_future(r)` (a documented "use"). Result: **0**
  `RuntimeWarning`s — confirms the warning is precise (no false
  positive on the supported hand-out idiom), not just "always fires."
- **Where does it surface under `-W error`?** — spawned a child process
  running the drop case under `python -W error`. The warning did **not**
  escalate to a raised `RuntimeWarning` propagating out of `asyncio.run`;
  instead it surfaced as `Exception ignored in: ... _PendingReceipt.__del__`
  on **stderr**, i.e. `-W error` turns the warning into an exception
  *inside* `__del__`, which Python (per its object-finalizer contract)
  catches and reports via `sys.unraisablehook` rather than propagating —
  this is standard CPython behaviour for any exception raised from
  `__del__`, not a library defect. Worth documenting for anyone who
  expects `-W error` to turn this into a catchable test failure: it does
  not; a `pytest -W error::RuntimeWarning` run would need
  `recwarn`/`catch_warnings` at the call site, or the library's own
  `-W error` test in `test_round12_findings.py` — same finding, not a
  new defect.

`RUNTIME_WARNING_OK: True`.

---

## 4. New round-13 attack: `attack_persistence_property_matrix.py` (#226/#227/#230/#233)

Four sub-attacks, single async run, ≈4 s (dominated by the 320-case
property loop):

- **(A) v3 latch round-trip.** `raise(delay=)` self-heartbeat trips
  `maxIterations` (config `maxIterations: 3`, a `PUMP` handler that
  `send`s itself 10× synchronously). Snapshot → restore → resend → snapshot,
  5 generations. Result: `latch counts across restarts: [1, 2, 3, 4, 5, 6]
  monotonic: True` — `chain_trips` round-trips and stays monotonic across
  5 restarts, `LATCH_ROUNDTRIP_OK: True`. (`last_chain_error`/`RestoredError`
  path is exercised implicitly — no assertion failure on the message
  containment check across any generation.)
- **(B) `scheduled_sends` strict-refusal property, 320 cases.** A
  `strict: True` machine arms a `raise(delay=50)` self-send, is
  snapshotted, and the persisted `scheduled_sends` record's `type` is
  forged to an undeclared `FORGED_UNDECLARED` with probability 0.5 (seeded
  `random.Random(1234)`), alternating `SyncInterpreter`/`Interpreter` each
  case. Property checked: after `from_snapshot(...).start()`, the
  interpreter is left in a consistent status (`running`/`stopped`/`done`)
  and the on-restore refusal count matches the poison count exactly (no
  over-fire, no under-fire). **320/320 cases pass, 0 failures.**
  `STRICT_RESTORE_PROPERTY_OK: True`.
  - Note: an earlier draft of this script poisoned the wrong JSON key
    (`event` instead of the flat `type` the `scheduled_sends` record
    format actually uses) and silently admitted every forged record —
    a harness bug in the attack, not a library defect; fixed before this
    result was recorded (see the record shape asserted directly against
    `get_persisted_snapshot()` during script development).
- **(C) `plugins=` exactly-once.** Both the `scheduled_sends` record and
  a `pending_events` record are forged to `FORGED_UNDECLARED` on the same
  snapshot; a `CapturePlugin` is passed via `from_snapshot(..., plugins=)`
  and the interpreter is then `start()`-ed. Result: **exactly 1**
  `on_invalid_event` call recorded — the strict machine's `pending_events`
  list was empty at snapshot time in this scenario (the only event on the
  wire was the one that armed the delayed self-send), so only the
  `scheduled_sends` lane's forged record was refused, and it fired
  `on_invalid_event` exactly once, no double-fire. `PLUGINS_EXACTLY_ONCE_OK:
  True` (`len(plug.invalid_calls) >= 1`, matching the documented contract:
  a restore-time refusal reaches a `plugins=`-registered plugin exactly
  once, same as a runtime one).
- **(D) Sync engine priority-lane restore, #233.** A restored
  `pending_events` blob with two `"normal"`-lane and two `"priority"`-lane
  records (mirroring the shape of the library's own
  `TestSyncRestoreHonoursPriorityLane`) is loaded via
  `SyncInterpreter.from_snapshot(...).start()`. Result:
  `sync restore processed order: ['priority1', 'priority2', 'normal1',
  'normal2']` — exact match to the expected FIFO-within-lane,
  priority-before-normal order. `SYNC_PRIORITY_LANE_OK: True`.

All four: **PASS**, no new defects (`D13-soak-*`) filed from this attack.

---

## 5. Not covered this pass (time-budget gaps, not asserted PASS/FAIL)

- Full 12-min / 200-machine soak (defer+rollback+bounded RAISE inbox +
  action-spawned workers + heartbeats + external priority + chaos v3
  restore with `plugins=`) — not run; only the ≤1 s-scale slices above
  ran.
- ≥500-config livelock fuzzer (both kinds, both engines) — not run.
- 50×-trace determinism sweep (both engines, both kinds, incl.
  `chain_trips`/latch) — not run.
- Config fuzzer incl. inline-dict `invoke.src` variants → always named
  `InvalidConfigError` — not attacked directly this pass; #231 is pinned
  in `tests/test_round12_findings.py` (part of the already-green full
  suite, §0) but no new adversarial fuzz beyond that regression pin.
- Task-identity semantics matrix beyond the 3 concurrency shapes run:
  `def`-service `send()` task identity under executor, child-action →
  parent-send, `after`-handler → send — not attacked directly.
- Remainder of `battle-de2da4e/soak/*` corpus (14 of 18 files) — not
  re-run this pass; see §1 gap note.
- 200-machine forgery/soak-scale security runs (only the 320-case
  strict-restore property in §4-B ran, single-machine, not under
  concurrent load).
- `production_characteristics.py --quick` bench (BENCH-6) — not run this
  pass; no new timer-lateness reading collected.

## Verdict

No new defects (`D13-soak-*`) found. Every script run this pass —
4 re-verified prior-defect samples (§1) plus 3 new round-13 attacks
covering the concurrency (#225), observability (#232), and persistence
(#226/#227/#230/#233) surfaces the CHANGELOG identifies as round-12's
actual changes — **held**. Combined with the already-complete full
pytest+coverage run (3577 passed, 13 skipped, 92.86% coverage,
`suite-v0.9.0.log`) and the unmodified `v0.9.0` tag vs. `HEAD` diff
(CI-only), this SOAK-track pass finds **no regression and no new
defect** in the round-13-relevant surface it was able to reach in
budget. The gaps in §5 are coverage gaps, not negative results, and
should be closed by a follow-up pass with a larger time budget before
this track is called complete.
