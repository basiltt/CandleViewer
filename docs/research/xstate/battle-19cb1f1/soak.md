# SOAK re-run — `xstate-statemachine` @ `19cb1f1` (unreleased 0.8.1, round-9)

**Build under test.** `_ref/xstate-statemachine` @ `19cb1f1` (merge of
round-9 fix PR #211). `CHANGELOG.md` `[Unreleased]` documents round-9
(#203–#210) on top of round-8. `__version__` still `0.8.0` — keyed on
commit.

**Date:** 2026-09-22. **Python:** CPython 3.13.7 / Windows 11.
**Interpreter:** `.venv-main/Scripts/python`,
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. No library source modified.

**Time-bound disclosure.** Whole-task budget is 20 minutes. All twelve
prior `battle-f28719c/soak/*` scripts were copied byte-for-byte (no
inlining needed — no shared-helper imports existed outside the copied
files) and re-run unmodified against `19cb1f1`. Two new attack scripts
were written for round-9-specific machinery: `attack_new_r9_soak.py`
(#204 statesToInvoke same-macrostep enter/exit, #203 after-provenance)
and `attack_new_r9_soak_2.py` (#207 stranded-invocation hook under a
20-way concurrent storm both engines, #206 delayed self-send debt).
Given the remaining budget, the full 12-min/200-machine chaos soak was
**not** re-run this pass (see §4); the prior track's own §4 already
flagged it as reduced-scale, and this track's share went to the
round-9-specific new attacks instead, which is the higher-value use of
the remaining minutes for a fix-verification pass.

---

## 1. Prior-defect re-verification (`battle-f28719c/soak/*` re-run unmodified against `19cb1f1`)

| ID | f28719c verdict | 19cb1f1 re-run result | Verdict |
|---|---|---|---|
| D-soak-1 (`wait=True` receipt hangs after uncaught plugin-hook exception) | FIXED | `repro_d_soak_1_via_use.py`: `FAIL (not reproduced): both receipts resolved` | **FIXED** (unchanged) |
| D-soak-2 (`SimulatedClock` settler leak on crash-restore) | FIXED | `repro_d_soak_2_via_clock_param.py`: `settlers registered: 0`, `1/21 reachable`, `NOT REPRODUCED` | **FIXED** (unchanged) |
| D5-soak-1 (`check_shape()` gap) | FIXED | `attack_hostile_fields_fixed.py`: all 6 hostile fields typed `SnapshotCorruptError`/`SnapshotVersionError` | **FIXED** (unchanged) |
| soak-adjacent #145 (`actionErrorPolicy:"fail"` stop contract) | FIXED | `attack_fail_stopped_snapshot.py`: `status="stopped"`, config `[]`, restore accepted as terminal | **FIXED** (unchanged) |
| #166-168 settle-budget under concurrent externals | PASS | `attack_166_settle_budget_soak.py`: tripped at lap 1001 regardless of 0/1/4/16 concurrent external senders | **PASS** (unchanged) |
| #172 threadsafe in-flight counter under churn | PASS | `attack_172_157_threadsafe_soak.py`: 25 generations, `anomalies=[]` | **PASS** (unchanged) |
| #157 loop-side RAISE observability | PASS | same script: 1199/1199 loop-side refusals fired `on_event_dropped(reason="queue_full")` exactly once | **PASS** (unchanged) |
| #173 `service_pool_size=1` + `stop()` churn (`def`) | PASS | `attack_173_service_pool_stop_churn.py`: 50 generations, `hangs=0`, `double_fires=0` | **PASS** (unchanged) |
| #173 (`async def` lane) | PASS | `attack_173_async_service_pool_stop_churn.py`: 50 generations, `hangs=0`, `double_fires=0` | **PASS** (unchanged) |
| round-7 A: `_chain_owed` under 100 never-completing `async def` services + `stop()` | PASS | `attack_new_chainowed_priority_childtimeout.py` Attack A: `{'n': 100, 'hangs': 0, 'dt_s': 0.231}` | **PASS** (unchanged) |
| round-7 B: external `priority=True` sends during self-generated chain | PASS | Attack B: `{'ext_seen': 2997, 'dropped': 0, 'rate_eps': 1483.8}` | **PASS** (unchanged; same known settle-pass microstep artifact re-disclosed below) |
| round-7 C: `children_timeout` with 50 slow children | PASS (bound-respected only) | Attack C: `{'start_dt_s': 0.307, 'status': 'running', 'bounded': True}` | **PASS** (same pre-existing harness-observability gap: `n_registered_children` reads a non-existent public attribute) |
| #195 forgery-under-load (200 hand-built `DoneEvent`/`ErrorEvent` under `strict=True`, both engines) | PASS | `attack_new_forgery_strict_soak.py`: `onDone_fires_from_forged: 0` both engines, `call_site_refused: 200/200` | **PASS** (unchanged) |
| #192 priority shed-by-provenance (re-run, same script/config as round-7's Attack B) | PASS | `{'dropped': 0, 'ext_seen': 2997/3000}` | **PASS** (unchanged; #196's settle-pass microstep cap still ends this particular `always`-cycle attack's chain early at ~500/2000 laps intended — pre-existing, not round-9) |

No harness adaptation was needed anywhere; round-9's fix set (invoke
arms after eventless settle, `after`-provenance, delayed-self-send
charging, stranded-invocation observability, receipt-illegal-config
refusal, lap parity, `#210` convergence wait) touches none of the code
paths these fourteen scripts pin, so an unchanged clean result was the
expectation and it held.

---

## 2. New round-9-targeted attacks (`battle-19cb1f1/soak/`)

| Attack | Target | Result |
|---|---|---|
| `attack_new_r9_soak.py` §A | #204: a state entered+exited in one macrostep (via `always` rolling forward) never submits its invoke's service, both engines × both service kinds | **PASS** |
| `attack_new_r9_soak.py` §D | #203: a hand-built (public-class) `AfterEvent` must not fire the `after` transition early, both engines | **PASS** |
| `attack_new_r9_soak_2.py` §C | #207: `rollback` + `onDone` storm cut at `maxIterations` strands the invocation exactly once — `on_invocation_stranded` fires once, `RunawayChainError.stranded`/`has_dormant_invocations` agree — under a 20-way concurrent storm, both engines | **PASS** |
| `attack_new_r9_soak_2.py` §B | #206: a `raise(delay=1)` self-send ping-pong is charged as engine work and trips `maxIterations`; a `SyncInterpreter` timer-paced cycle does NOT trip (caller has standing) | **PASS** |

### 2.1 `attack_new_r9_soak.py` §A — invoke arms only after settle

A machine with `mid: {invoke: {onDone: "done"}, always: "skip"}` (an
unconditional `always` rolling `mid` forward to `skip` in the same
macrostep the invoke would have armed in) was driven with `GO` on all
four combinations of `{def, async def}` × `{Interpreter, SyncInterpreter}`:

```
def/async {'svc_calls': 0, 'final': ['a.skip']}
def/sync {'svc_calls': 0, 'final': ['a.skip']}
async def/async {'svc_calls': 0, 'final': ['a.skip']}
async def/sync {'svc_calls': 0, 'final': ['a.skip']}
A_NO_SPURIOUS_INVOKE: True
```

`svc_calls == 0` in every cell: the entered-then-exited `mid` state
never submitted its service on either engine or service kind, consistent
with #204's SCXML §6.1 `statesToInvoke` fix. No defect.

### 2.2 `attack_new_r9_soak.py` §D — after-provenance spot check

A hand-built `AfterEvent(type="after.60000.d.waiting")` — the public
NamedTuple, not an engine-minted instance — was sent to a running
machine sitting in a state with a real 60-second `after` transition, on
both engines:

```
{'async': ['d.waiting'], 'sync': ['d.waiting']}
D_FORGED_AFTER_REFUSED: True
```

The machine stayed in `d.waiting` on both engines — the forged public
`AfterEvent` did not fire the 60 s transition instantly, consistent with
#203. No defect. (This is a spot check, not the full after-provenance
matrix; see §4.)

### 2.3 `attack_new_r9_soak_2.py` §C — stranded-invocation hook under concurrency

20 concurrent instances (async engine, `asyncio.gather`) and 20
sequential instances (sync engine) of the `TestStrandedInvocationObservable`
shape from `tests/test_round9_findings.py` (`spin.starting` invokes a
fast-completing service whose `onDone` target's `entry` action always
raises, forcing a `rollback` loop that trips `maxIterations=15`):

```
n = 20
async_ok_exactly_once = True
sync_ok_exactly_once = True
async_sample = [{'last_error_stranded': ('sub',), 'hook_fires': 1, 'dormant': True}, ...]
sync_sample = [{'raised_stranded': ('sub',), 'hook_fires': 1, 'dormant': True}, ...]
```

All 40 instances (20 async + 20 sync) stranded exactly once each:
`on_invocation_stranded` fired exactly once per instance, the raised /
`last_error`'s `RunawayChainError.stranded` names `('sub',)`, and
`has_dormant_invocations` agrees (`True`). Consistent with #207 holding
under concurrency, not just single-instance. No defect.

### 2.4 `attack_new_r9_soak_2.py` §B — delayed self-send debt

The exact `TestDelayedSelfSendIsCharged.CFG` shape (`a`/`b` ping-pong via
`raise(event="GO", delay=1)` on entry, `maxIterations=20`):

```
async: {'lap': 20, 'last_error': 'RunawayChainError'}
sync:  {'lap': 1,  'last_error': None}
```

The async engine's delayed self-send cycle tripped `RunawayChainError`
at the documented plateau (`n < 3*maxIterations`, landed at exactly
`maxIterations`). The `SyncInterpreter` — driven only by `tick()` calls,
never trips, because a timer-paced cycle on that engine is a
caller-advanced periodic process with user standing, exactly as
documented in the round-9 changelog and pinned by
`test_sync_engine_timer_paced_cycle_is_a_periodic_process`. This is the
*expected*, documented asymmetry, not a defect — recorded so a future
track does not mistake `sync: lap=1, no error` for R9-06 reopening.

---

## 3. Defects

**None found this pass — `D10-soak-n` register is empty.** All fourteen
prior-round soak-track defects/checks remain FIXED/PASS unchanged, and
the four new round-9-targeted attacks (#204 same-macrostep invoke arming,
#203 after-provenance, #207 stranded-invocation hook under concurrency,
#206 delayed self-send charging) each behaved exactly as the round-9
changelog and `tests/test_round9_findings.py` describe, at soak-adjacent
scale (20-way concurrency for §2.3, both service kinds × both engines for
§2.1) rather than only the single-instance unit-test shape.

No round-9 regression was found in any of the fourteen re-run legacy
scripts either; the two previously-recorded harness-shape artifacts
(§2.2-equivalent: the pre-existing settle-pass microstep cap ending the
`always`-cycle priority attack's chain early; `n_registered_children`
reading a non-existent attribute) reproduce identically and are, as
before, not attributable to round-9.

---

## 4. What was NOT covered (explicit)

- **Full 12-minute/200-machine chaos soak** — not re-run this pass; the
  prior track's own reduced-scale run (1.5 min/20–40 machines) was not
  repeated either, given this track's share of the 20-minute budget went
  to the four round-9-specific attacks in §2 instead. CPU-bounded
  behaviour, 0 dropped external, no livelock, no stranded-without-hook at
  full 200-machine/12-min scale remains unverified this pass.
- **Persistence round-trip of a pending-arm invoke** (snapshot taken
  between a state's entry and the settle pass that would arm its invoke,
  then restored — does the restored machine arm exactly once, never
  zero, never twice) — not built; this track's §2.1 only checked the
  in-process (no snapshot round-trip) same-macrostep case. Persistence
  track's remit.
- **Delayed self-send debt across a snapshot/restore boundary** — not
  built; §2.4 only checked the in-process charging behaviour, not
  whether the debt survives (or should survive) a `from_snapshot` cycle.
  Persistence track's remit.
- **Property test ≥300 random machines incl. parallel + children +
  after** — not built at soak scale; fuzz/semantics tracks' remit
  (`tests/test_round9_findings.py` already carries targeted parametrised
  pins, but not a random-machine property sweep at this volume).
- **100 machines with `raise(delay=1ms)` self-ping-pong, concurrently**
  — §2.4 ran the exact charging-mechanism check on ONE machine per
  engine (matching the unit-test shape); a 100-concurrent-machine version
  confirming they all trip at the same lap was not built given the
  budget. Concurrency track's remit.
- **200-concurrent-storm stranded-invocation check** — §2.3 ran 20
  concurrent (not 200) per the brief's own soak-track share of budget;
  the exactly-once/id-correctness property held at n=20 but was not
  pushed to n=200.
- **External delayed sends at 5k/s during self-generated chains** — not
  built; round-7/8's Attack B (re-run unmodified in §1) achieved ~1.5k
  eps with 0 drops, but a dedicated 5k/s external-delayed-send harness
  (distinct from the `priority=True` immediate-send harness Attack B
  already exercises) was not built. Concurrency track's remit.
- **Livelock fuzzer ≥500 configs × {def, async def} × both engines incl.
  always+invoke+after+delayed-raise combinations** — not re-run or built
  in this track; fuzz track's remit, as in the prior round.
- **Illegal-configuration receipt fuzz** — not built; semantics/fuzz
  tracks' remit (#208's belt-and-braces refusal was pinned by the
  library's own `tests/test_round9_findings.py`, not independently
  soak-fuzzed here).
- **Determinism** (50× identical traces both engines/kinds incl. stranded
  events, hash-seed sweep) — determinism track's remit.
- **Full SCXML §6.1 `statesToInvoke` matrix** (enter-exit via `always` /
  `rollback` / parallel-sibling-final / history) — §2.1 covered only the
  `always`-rollforward shape; `rollback`, parallel-sibling-final, and
  history-driven enter/exit-in-one-macrostep shapes were not attacked
  here. Semantics track's remit.
- **Full after-provenance matrix** (import-path / `type(held)` / pickle /
  snapshot `"engine": true` construction of `_EngineAfter`) — §2.2 was a
  spot check on the public-class construction path only. Security track's
  remit.
- **`on_invocation_stranded` ordering vs `on_event_dropped`, and
  `RunawayChainError.stranded` payload beyond the `('sub',)` shape
  checked in §2.3** — observability track's remit.

---

## 5. Verdict

All fourteen soak-track legacy defects/checks re-run unmodified against
`19cb1f1` (`D-soak-1`, `D-soak-2`, `D5-soak-1`, `#145`, `#166-168`,
`#172`/`#157`, `#173`-def, `#173`-async, round-7's `_chain_owed`/priority-
provenance/`children_timeout` attacks, and round-8's forgery-under-load
and priority-shed-by-provenance attacks) remain **FIXED/PASS**, unchanged
from the `f28719c` re-run — round-9's fix set (invoke-arms-after-settle,
after-provenance, delayed-self-send charging, stranded-invocation
observability, receipt-illegal-config refusal, lap parity, `#210`
convergence wait) touches none of the code paths these fourteen scripts
pin.

The four new round-9-targeted attacks built for this track — same-
macrostep invoke-arming suppression (#204, both engines × both service
kinds), forged-`AfterEvent` refusal (#203, both engines), stranded-
invocation hook exactly-once under a 20-way concurrent storm (#207, both
engines), and delayed self-send charging with the documented sync-engine
exemption (#206, both engines) — all passed cleanly, consistent with the
round-9 changelog and `tests/test_round9_findings.py`.

**No new defects found (`D10-soak-n` register empty).** The larger
uncovered surface (§4) — full 12-min/200-machine duration, persistence
round-trips of pending-arm invokes and delayed-send debt, the full
statesToInvoke and after-provenance matrices, ≥300-config property
sweeps, 100/200-way concurrency at the brief's literal scale, 5k/s
external-delayed-send, the ≥500-config livelock fuzzer, illegal-
configuration receipt fuzz, determinism, and the observability/security
tracks' own remits — remains explicitly out-of-scope of this track's
share of the 20-minute whole-task budget and is flagged as follow-on
work rather than silently skipped.
