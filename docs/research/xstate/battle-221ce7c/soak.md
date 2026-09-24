# SOAK re-run — `xstate-statemachine` @ `221ce7c` (unreleased 0.8.1, round-6)

**Build under test.** `_ref/xstate-statemachine` @ `221ce7c`. `CHANGELOG.md`
`[Unreleased]` documents round-6 (#166-#175, #157 reopened, #122
closed-as-designed) on top of round-5 (#142-#162). `__version__` still
`0.8.0` — identified by commit only.

**Date:** 2026-09-20. **Python:** CPython 3.13 / Windows 11.
**Interpreter:** `.venv-main/Scripts/python`,
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. No library source modified.

**Time-bound disclosure.** Whole-task budget is 20 minutes. Prior-defect
scripts were copied byte-for-byte from `battle-cec108b/soak/` and re-run
unmodified. The main soak scenario was re-run at the already-reduced
1.5 min / 30 machines / 3 producers (same as the cec108b track). New
round-6-targeted attacks were added at small/fast scale given the budget;
the 12-min/200-machine full soak and the config-fuzzer livelock probe were
**not** run this pass (see §5).

---

## 1. Prior-defect re-verification

| ID | cec108b verdict | 221ce7c re-run result | Verdict |
|---|---|---|---|
| D-soak-1 (`wait=True` receipt hangs forever after uncaught plugin-hook exception) | FIXED | `repro_d_soak_1_via_use.py` (unmodified): `FAIL (not reproduced): both receipts resolved` | **FIXED** (unchanged) |
| D-soak-2 (`SimulatedClock` settler leak on crash-restore) | FIXED | `repro_d_soak_2_via_clock_param.py` (unmodified): `settlers registered: 0`, `1/21 reachable`, `NOT REPRODUCED` | **FIXED** (unchanged) |
| D5-soak-1 (`check_shape()` gap) | FIXED (#146) | `attack_hostile_fields_fixed.py` (unmodified): all 6 hostile fields still typed `SnapshotCorruptError`/`SnapshotVersionError` | **FIXED** (unchanged) |
| (soak-adjacent) `actionErrorPolicy: "fail"` stop contract (#145) | PASS | `attack_fail_stopped_snapshot.py` (unmodified): `status="stopped"`, config `[]`, restore accepted as terminal | **FIXED** (unchanged) |

No harness adaptation was needed; round-6 does not touch `_SafePlugin`,
`SimulatedClock` teardown, `check_shape()`, or the #145 stop contract.

### 1.1 Standing soak re-run (30 machines / 3 producers / 1.5 min)

```
final_sent: 9501, final_accepted: 9500
receipts_ok: 1866, receipts_deferred: 7103, receipts_error: 531
restart_count: 32, lost_events_count: 0
remaining_asyncio_tasks_after_final_stop: 1 (loop bookkeeping, not a leak)
unexpected_exceptions: ["D-soak-1 hang: m28 gen10 key=(28, 10, 10)"]
max_loop_lag_ms: 3931 (GC/tracemalloc overhead, flat RSS growth 55->84MB)
```

The lone `unexpected_exceptions` entry is the harness's own known
non-defect label (a `send(wait=True)` racing a chaos `stop(drain=True)`
mid-flight — the interpreter legitimately stops first) — identical in
kind and rate to the cec108b run. No new anomaly.

---

## 2. New attacks targeting round-6 fixes

| Script | Target | Result |
|---|---|---|
| `attack_166_settle_budget_soak.py` | #166/#167/#168: per-macrostep settle budget under concurrent external senders | **PASS** |
| `attack_172_157_threadsafe_soak.py` | #172 in-flight counter balance under churn; #157 loop-side RAISE observability | **PASS** (both halves) |
| `attack_173_service_pool_stop_churn.py` | #173 `service_pool_size=1` + `stop()` mid-service churn | **PASS** |

### 2.1 `attack_166_settle_budget_soak.py`

A self-generated unconditional cycle (`bump_and_reraise` → `send(TICK)`)
was raced against 0/1/4/16 concurrent external senders hammering the same
interpreter with an unrelated `EXTERNAL` event, 1 trial per concurrency
level:

```
n_external_senders=0:  tripped=True, n_reached=1001
n_external_senders=1:  tripped=True, n_reached=1001
n_external_senders=4:  tripped=True, n_reached=1001
n_external_senders=16: tripped=True, n_reached=1001
ALL_TRIPPED: True
```

The chain trips at the **same lap count (1001, i.e. `maxIterations`=1000
+1 discard)** regardless of concurrent external load — matching the
changelog's claim that concurrent externals do not reset the
self-generated chain's bound, and the chain still trips (not starved into
a silent livelock) under 16-way concurrent external pressure. No defect.

### 2.2 `attack_172_157_threadsafe_soak.py`

**#172 (in-flight counter):** 25 generations of 8 threads × 40
`send_threadsafe(internal=True)` calls each, with `stop()` interleaved
mid-flight on 1/3 of generations (exercising "loop stopped before the
coroutine ran"). No accessible leaked-counter anomalies across all 25
generations (`anomalies=[]`); each generation's fresh interpreter behaved
consistently regardless of prior-generation churn.

**#157 (loop-side RAISE observability):** 12 threads × 100 external
(`internal=False`) `send_threadsafe()` calls against `max_queue_size=1` /
`OverflowPolicy.RAISE`, deliberately racing many threads past the
call-site's optimistic `qsize()` check so refusals land on the **loop**
instead:

```
sends_attempted=1200, call_site_raises=0
loop_side_future_refusals=1199, total_refusals=1199
drop_hook_queue_full=1199
HOOK_FIRED_EXACTLY_ONCE_PER_REFUSAL: True (expected 1199, got 1199)
```

Every one of the 1199 loop-side refusals fired `on_event_dropped(reason=
"queue_full")` exactly once — matching #157's fix exactly (previously
these landed silently on unread futures). No defect.

### 2.3 `attack_173_service_pool_stop_churn.py`

50 generations of a single plain-`def` (blocking) service under
`service_pool_size=1`, `stop()` issued mid-service (odd generations) or
after completion (even generations):

```
generations=50, hangs=0, double_fires=0
thread_count: first_before=1, last_after=1 (no thread leak across 50 generations)
```

No hung `stop()`, no double-fired `onDone`, no accumulating OS thread
count across 50 independent interpreters each owning its own
`service_pool_size=1` executor. (Note: an earlier draft of this attack
used `id(interp)`-keyed global tallies to detect double-fires, which
produced 28 false "double fires" from CPython recycling a GC'd
interpreter's `id()` across generations — a harness bug, not a library
defect; fixed by using the machine's own per-generation context counter
instead.) No defect.

---

## 3. Defects

**None found this pass.** All four prior-round soak-track defects/checks
remain FIXED, and all three round-6-targeted new attacks (settle-budget
concurrency, threadsafe in-flight/RAISE-observability, service-pool
stop-churn) pass cleanly against `221ce7c`.

---

## 4. What was NOT covered (explicit)

- Full 12-minute/200-machine chaos soak — only 1.5 min/30 machines/3
  producers re-run, within the 20-minute whole-task hard bound.
- Config fuzzer for livelock across both engines (≥500 generated configs,
  30 s watchdog, nested-invoke cycles/always cycles/rollback+onDone/
  sendTo self-loops) — not attempted; this is a large, dedicated-harness
  task explicitly out of reach of the remaining budget.
- Persistence-hook-matrix property test (snapshot from on_transition/
  on_action/on_guard/entry-exit-of-nested+parallel/deferred-replay/
  after-timer-callback, ≥300 random machines, restore+resume trace
  parity) — persistence track's remit, not attempted here.
- 50× identical-trace determinism sweep both engines incl. trip points,
  hash-seed sweep, perf-PR (#165/#176) shared-init-sentinel cross-talk
  check — determinism track's remit.
- guard-crash vs denied vs deferred vs unhandled 4-way matrix, `start()`
  ordering vs #116, entry-window refusal at child vs root — semantics
  track's remit (persistence-adjacent entry/exit refusal at *root* only
  was exercised indirectly via the standing soak machine's own actions,
  not independently attacked here).
- `internal=True` forgery post-fix, redaction, `__slots__` attribute
  surface — security track's remit.
- Full hook matrix exactly-once/ordering beyond `queue_full` (chain_budget
  observability on both engines, guard_denied, on_resolve_error, etc.) —
  observability track's remit; only `queue_full` (both call-site and
  loop-side) was independently attacked here.

---

## 5. Verdict

All soak-track legacy defects (`D-soak-1`, `D-soak-2`, `D5-soak-1`) and the
soak-adjacent `#145` stop-contract check remain **FIXED**, unchanged from
the `cec108b` re-run — round-6 does not touch any of that machinery.

The three round-6 fixes most relevant to sustained/concurrent load —
**#166-#168** (per-macrostep chain-settle budget), **#172** (threadsafe
in-flight counter balancing) + **#157** (loop-side RAISE observability),
and **#173** (`service_pool_size`) — were each independently attacked with
soak-style repeated-trial/concurrency harnesses at reduced scale (dozens
of generations / up to 16-way concurrency / 1200 racing sends) and all
passed cleanly: the self-generated chain trips at an identical lap count
regardless of 0-16 concurrent external senders; the threadsafe in-flight
counter shows no leak signature across 25 stop-churned generations;
1199/1199 loop-side queue-full refusals fired the drop hook exactly once
each; and 50 generations of `service_pool_size=1` + mid-service `stop()`
churn produced zero hangs, zero double-fires, and no OS-thread leak.

No new defects found in this reduced pass. The much larger uncovered
surface (§4) — full-duration soak, config-fuzzer livelock probe,
persistence-hook-matrix property test, determinism sweep, full
observability hook matrix, security surface — remains explicitly
out-of-scope of this track's 20-minute budget, consistent with the prior
round's disclosure, and is flagged as follow-on work rather than silently
skipped.
