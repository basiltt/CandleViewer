# Observability, Error Surface & Operability — re-run @ `cec108b` (round-5)

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit `cec108b` (unreleased 0.8.1, round-5 fixes #142-#162 + reopened
#118/#122/#125/#133/#134). `__version__` still reports `0.8.0`; identified
by commit only, per the project's standing rule.

**Date:** 2026-09-19. **Interpreter for every run:**
`_ref/xstate-statemachine/.venv-main/Scripts/python` with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. No library source was modified. No
`git` command was run in the CandleViewer repository. GitHub was not touched.

**Time-bound reductions** (mandate: state, don't silently apply):
- Service-executor concurrency: 200 requested -> **40** concurrent plain-def
  services (wall-clock budget).
- `send_threadsafe` RAISE-under-contention: 16 threads x 200 sends against a
  `max_queue_size=2` inbox with a slowed-down (5ms) action, run once (not
  replicated); no queue-full RAISE was observed at this depth/speed, see
  coverage gap below — a genuine backpressure-saturation probe (larger N,
  faster producers, no slowdown) was not attempted given the time bound.
- Hypothesis-based parallel-persistence property (>=300 cases), fuzzers (5k
  mutations), 50x determinism reruns, and the 12-minute soak specified in
  the mandate were **NOT RUN THIS PASS** — see Coverage section. This report
  covers the prior-defect re-run plus a set of new, single-run (not
  statistically replicated) targeted attacks on round-5's fixes only, given
  the 20-minute wall-clock bound for this task.

All scripts are under `battle-cec108b/observability/`: `rerun_prior.py` (the
9 prior defects, copied from `battle-3ed3099/observability/rerun_prior.py`
with one addition -- `on_resolve_error` added to the `Recorder` plugin to
check whether the sync engine now fires it per #134), `new_attacks.py`
(attacks A-H on round-5 fixes). Raw output in `rerun_out.txt` / `out.txt`.

---

## 1. Prior-defect re-run (`rerun_prior.py`)

| ID | 3ed3099 result | cec108b result | Verdict |
|---|---|---|---|
| D-observability-1 (guardErrorPolicy naming) | UNCHANGED (design-constraint) | Enum unchanged in `models.py`; not independently re-attacked this pass either. | **UNCHANGED** |
| D-observability-2 (guard raise absorbed into `Receipt`) | STILL-PRESENT | `policy="raise"`: `Receipt(changed=False, error=ValueError(...))`, `last_transition_ok=False`, `last_error` set, `on_guard_error` fires. This is now the *documented, correct* shape (R5-11 fixed the ambiguous no-op/denied/errored cases via `Receipt.denied` + `on_unhandled_event(disposition=...)`, verified fresh in attack A below) -- a raising guard was never silently swallowed on this engine/policy combination in the first place; the prior "STILL-PRESENT" label described the *general* Receipt-ambiguity problem R5-11 targeted, which is now resolved for the guard-denied case specifically. | **FIXED** (for the guard-denied/errored distinction R5-11 targeted; the naming-only D-observability-1 concern is separate and unchanged) |
| D-observability-3 (deferred replay folds into triggering Receipt) | STILL-PRESENT | Identical repro: `r2` (ARM's own receipt) already shows `state_ids=['m_defer_replay.b']` -- i.e. **not** folded with the replay's `c`. This differs from the 3ed3099 run, where `r2.state_ids` was reported as reflecting the post-replay state. #125 was reopened and re-fixed specifically for `SyncInterpreter` this round ("a deferred event's replay is its own macrostep on `SyncInterpreter` too -- the caller's `Receipt` is final before any replay runs"). | **FIXED** |
| D-observability-4 (`SyncInterpreter(..., max_queue_size=1)` -> `TypeError`) | STILL-PRESENT | Identical `TypeError`. | **UNCHANGED** (documented design asymmetry) |
| D-observability-5 (`StateNotFoundError` has no dedicated hook on sync engine) | FIXED on async only | Now **FIXED on sync too**: `hooks=['on_transition', 'on_event_received', 'on_resolve_error']` -- `on_resolve_error` fires on `SyncInterpreter` per #134's reopened sync-parity fix. | **FIXED** (both engines now) |
| D-observability-6 (`.use()` vs `.plugins=` parity) | CONFIRMED NOT A DEFECT | Re-confirmed identical again. | **CONFIRMED NOT A DEFECT** |
| D-observability-7 (`has_dormant_invocations` only clears on `.start()`) | STILL-PRESENT (documented) | Identical: `True` before `.start()`, `False` after. Still documented behavior. | **UNCHANGED** (documented, not a regression) |
| D-observability-8 (`stop()` drops pending queue silently) | FIXED | Identical: `on_event_dropped` fires 5x for 5 abandoned events on `stop()`. | **UNCHANGED (still fixed)** |
| D-observability-9 (no `to_dict`/`to_json`/`config` re-export) | (not scored, informational) | Identical: absent; `to_mermaid`/`to_plantuml` present. | **UNCHANGED** |

---

## 2. New attacks on round-5 fixes (`new_attacks.py`)

| Attack | Target | Result |
|---|---|---|
| A: `Receipt.denied` / `on_unhandled_event(disposition=...)` for a guard-denied transition | #153 | **PASS** -- `Receipt.denied=True`, `disposition=['guard_denied']`, `changed=False`. Guard-denied is now cleanly distinguishable from unhandled/errored, closing the exact gap D-observability-2/R5-11 was about. |
| B: `actionErrorPolicy="fail"` — hook count/ordering and terminal state | #145 | **PASS** -- `status="stopped"` (not the old `"error"`-but-still-`running`-looking state), `current_state_ids` is empty (configuration cleared as documented), `on_transition_failed` fires exactly once, `on_error` fires exactly once, `on_transition` does **not** fire (transition never committed), and `receipt.error` carries the original `ValueError`. Matches the CHANGELOG's "fail: rolled back, then the interpreter stops with `status == 'error'`" *docstring* language loosely but the observed status string is `"stopped"` per the top-level CHANGELOG bullet ("`status` is `'stopped'`"), not `"error"` -- this is a **doc/docstring inconsistency** between `PluginBase.on_action_error`'s docstring (says `status == "error"`) and the actual/CHANGELOG-described behavior (`status == "stopped"`), noted as D6-observability-1 below (Low, cosmetic, does not affect operability). |
| C: `RootTargetError` non-downgradable under `strict_targets=False` | #147 | **PASS** -- raised at build time regardless of the flag, typed as `RootTargetError` (subclass of `InvalidConfigError`), clear message naming the offending transition and a remediation suggestion. |
| D: chain-budget / nested-invoke-onDone-into-ancestor livelock (#144) | #144 | **PASS (bounded)** -- `start()` returns immediately (`status="running"`, no hang) for a nested-invoke `onDone` -> ancestor `always` -> re-invoke cycle with `maxIterations=50`; the machine settles rather than looping, consistent with "a chain now ends only when nothing self-generated remains queued." No `RunawayChainError` was needed because the cycle in this reduced repro terminates naturally (the `invoke` only fires once per macrostep entry) -- a genuinely infinite variant was not constructed in the time available (see coverage gap). |
| E: `SnapshotCorruptError` for a torn parallel-region configuration | #142/#143 | **PASS** -- a snapshot with one region's leaf stripped out (`r1` left with no active atomic child while `r2` still has one) is refused on restore with a typed `SnapshotCorruptError` whose message names the malformed region set, exactly matching `_configuration_is_legal`'s "exactly one active leaf per region" contract. |
| F: `service_executor` under 40 concurrent plain-`def` services | #149 | **PASS** -- all 40 completed (`done=40/40`); no deadlock, no service starving the event loop (each interpreter polled its own status independently and progressed). Reduced from the requested 200 for wall-clock budget. |
| G: `send_threadsafe(internal=True)` forgery from a plain, non-owned `threading.Thread` | #150 | **INCONCLUSIVE / not a defect as attacked** -- the single-generation repro (one self-trigger, capped at 10000) completed with `status="running"` and no `RunawayChainError`, which is *expected*: `internal=True` is a documented, deliberate escape hatch for exactly this case ("a plain `threading.Thread` does NOT inherit the context ... an action that hands its own re-trigger to one must pass `internal=True`"). This is not a forged bypass of accounting, it is the library's own recommended idiom being exercised correctly. **A real forgery attack** (an *unrelated*, non-self-send caller passing `internal=True` to dodge `maxIterations` on a chain it did not originate) was not constructed in the time available — flagged as a coverage gap, not a finding. |
| H: `QueueOverflowError` raised at the `send_threadsafe()` call site under contention (16 threads x 200 sends, `max_queue_size=2`, `OverflowPolicy.RAISE`) | #157 | **NOT REPRODUCED THIS PASS** -- 3200/3200 sends succeeded, zero `QueueOverflowError` observed even with a 5ms action added to slow draining. The bounded inbox (`max_queue_size=2`) was evidently never observed full from the calling threads' vantage point in this single run — likely an artifact of `asyncio.Queue`'s put path draining faster than 16 GIL-bound Python threads can produce, even under a slowed handler. Not evidence of a regression (the underlying "raise at call site, not on an unread future" claim was previously exercised satisfactorily elsewhere in the round-5 test suite per the CHANGELOG); simply an unreplicated single run that didn't hit the saturation window. Needs a purpose-built producer/consumer imbalance (e.g., pause the interpreter's own loop, or use `max_queue_size=0`/1 with zero slack) to force the race — not attempted given the time bound. |

---

## 3. New defects filed

**D6-observability-1** (Low, cosmetic/documentation only)
`PluginBase.on_action_error`'s docstring says: *`"fail" — rolled back, then
the interpreter stops with `status == "error"`.`* The actually-observed
(and CHANGELOG-documented) behavior for `actionErrorPolicy: "fail"` is
`status == "stopped"` (confirmed live in attack B: `interp.status ==
"stopped"`). The CHANGELOG bullet itself is correct ("`status` is
`'stopped'`"); only the docstring in `plugins.py`'s `PluginBase` class is
stale, still describing the pre-#145 `"error"` status string. Not filed
against operability/observability of the *hooks themselves* (those fire
correctly and in the right order/count) — purely a stale-docstring
inconsistency that could mislead a plugin author checking
`interpreter.status == "error"` after `on_action_error` under `"fail"`, when
they should check for `"stopped"`.
- Repro: `new_attacks.py::b_fail_stops_once` — `interp.status` after
  `on_error` fires reads `"stopped"`, contradicting the hook's own
  docstring.
- File/line: `src/xstate_statemachine/plugins.py:201-202` (the
  `on_action_error` docstring's `"fail"` bullet: `"fail" — rolled back,
  then the interpreter stops with status == "error".`) — verified by grep,
  this is the only place in the source that asserts `status == "error"`
  for the `"fail"` policy; every runtime code path (`interpreter.py`,
  `persistence.py`, `sync_interpreter.py`) and the CHANGELOG agree the
  real value is `"stopped"`.

No other new defects found in this pass's reduced attack set; all
round-5-relevant fixes attacked (A, C, E, F) held up cleanly, and B/D/G/H
are either passes or inconclusive-not-reproduced rather than confirmed
regressions.

---

## 4. Not covered this pass (explicit, per the reproduce-before-you-count standard)

- Hypothesis property test over random PARALLEL machines (>=300 cases,
  snapshot-at-every-quiescent-point round-trip) — **not run**.
- Snapshot-mutation fuzzer vs `SnapshotCorruptError` typing (5k mutations),
  event-type fuzz vs `InvalidEventError`, config fuzzer for livelock with a
  30s watchdog — **not run**.
- 50x identical-trace determinism cross-check (both engines, hash-seed
  sweep) — **not run**.
- `guardErrorPolicy="raise"` fallback-candidate semantics, `Receipt.denied`
  vs deferred vs unhandled full matrix, `"fail"` parent `onError` on both
  engines, escalate paths — **not independently re-attacked** this pass
  (guard-denied only, attack A).
- History+parallel restore, v1-upcast-with-torn-configuration refusal,
  "fail"-stopped snapshot refusal, actors+deferred-buffer legality — **not
  attacked**.
- `_die` under double cancel, leaked threads/tasks after 500 cycles,
  `service_executor` + `stop()` mid-service — **not attacked** (F only
  covers steady-state concurrency, not mid-flight cancellation).
- Genuine `send_threadsafe` queue-saturation (H) and a real `internal=True`
  forgery from an unrelated caller (G) — attempted but **inconclusive**,
  see notes above; both need a purpose-built race/adversarial harness this
  pass's budget did not allow.
- Redaction of `get_snapshot()` DEBUG output, executor thread-context
  leakage, exported API surface diff — **not attacked** (I1/I2 from the
  3ed3099 pass were not re-run this round for the cec108b redaction-key
  expansion, #160).
- 12-minute soak — **not run at all** this pass (not even the reduced
  15s smoke variant the round-4 pass used), given the 20-minute overall
  wall-clock bound for this task.

## 5. Verdict

Round 5's observability-relevant fixes hold up under the reduced,
single-run attack set exercised here: `Receipt.denied` (#153) cleanly
resolves the guard-denied ambiguity that was the single biggest carried-over
defect from prior rounds (D-observability-2), `RootTargetError` (#147) is
correctly non-downgradable, `SnapshotCorruptError` (#142/#143) correctly
refuses a torn-parallel configuration, sync-engine parity for `on_resolve_error`
(#134) and deferred-replay-as-own-macrostep (#125) are both confirmed fixed
against their exact prior repros, and 40 concurrent `service_executor`-backed
plain-`def` services (#149) completed without incident. One low-severity,
purely cosmetic documentation defect was found (stale `status == "error"`
claim in `PluginBase.on_action_error`'s docstring vs the actual/documented
`"stopped"`). Two attacks (G: `internal=True` forgery, H: `send_threadsafe`
RAISE-under-contention) did not reproduce anything in a single run and need
a more adversarial harness than this task's time budget allowed — flagged as
gaps, not passes. No Blocker/High-severity observability regressions were
found in this pass; this is a narrow, time-boxed slice of the requested
matrix and should not be read as full confirmation of round 5's
observability surface — see §4 for what remains genuinely unverified.

