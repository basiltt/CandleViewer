# Observability, Error Surface & Operability — re-run @ `221ce7c` (round-6)

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit `221ce7c` ("Merge pull request #178 from basiltt/fix/157-loop-side-raise-observable";
unreleased 0.8.1, round-6 fixes #166-#175 + #157 reopened + #122-as-designed).
`__version__` still reports `0.8.0`; identified by commit only, per the
project's standing rule.

**Date:** 2026-09-20. **Interpreter for every run:**
`_ref/xstate-statemachine/.venv-main/Scripts/python` with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. No library source was modified. No
`git` command was run in the CandleViewer repository. GitHub was not touched.

**Time-bound reductions** (mandate: state, don't silently apply):
- `send_threadsafe` RAISE-under-contention (attack I): 16 threads x 40 sends
  (reduced from cec108b's 200/thread) against `max_queue_size=2` with a 3ms
  slowed action — enough to force the loop-side race this round, unlike the
  prior pass's inconclusive attempt (see §2, attack I).
- Config fuzzer for livelock across both engines (>=500 generated configs,
  30s watchdog per the mandate) — **NOT RUN THIS PASS**, see §4.
- Hypothesis-based parallel-persistence property (>=300 cases), 50x
  determinism reruns, hash-seed sweep, and the 12-minute soak — **NOT RUN
  THIS PASS**, see §4.
- All scripts under `battle-221ce7c/observability/`: `rerun_prior.py` (the 9
  legacy defects, copied unmodified from `battle-cec108b/observability/`),
  `new_attacks.py` (attacks I-O targeting round-6's #157/#166-175 fixes).
  Raw output in `rerun_out.txt` / `out.txt`.

---

## 1. Prior-defect re-run (`rerun_prior.py`, unmodified from cec108b)

| ID | cec108b result | 221ce7c result | Verdict |
|---|---|---|---|
| D-observability-1 (guardErrorPolicy naming) | UNCHANGED (design) | Enum unchanged. | **UNCHANGED** |
| D-observability-2 (guard raise / Receipt shape) | FIXED (for guard-denied/errored distinction) | Identical: `raise` policy → `Receipt(changed=False, error=ValueError(...))`, `last_transition_ok=False`, `on_guard_error` fires. | **UNCHANGED (still fixed)** |
| D-observability-3 (deferred replay folds into triggering Receipt) | FIXED | Identical: `r1` (deferred) `state_ids=['m_defer_replay.a']`, `r2` (ARM's own receipt) `state_ids=['m_defer_replay.b']` — not folded with replay's `c`. | **UNCHANGED (still fixed)** |
| D-observability-4 (`SyncInterpreter(max_queue_size=...)` → `TypeError`) | UNCHANGED (design asymmetry) | Identical `TypeError`. | **UNCHANGED** |
| D-observability-5 (`StateNotFoundError` hook, sync engine) | FIXED (both engines) | Identical: `hooks=['on_transition','on_event_received','on_resolve_error']` on `SyncInterpreter`. | **UNCHANGED (still fixed)** |
| D-observability-6 (`.use()` vs `.plugins=` parity) | CONFIRMED NOT A DEFECT | Re-confirmed identical. | **CONFIRMED NOT A DEFECT** |
| D-observability-7 (`has_dormant_invocations` only clears on `.start()`) | UNCHANGED (documented) | Identical: `True` before, `False` after `.start()`. | **UNCHANGED (documented)** |
| D-observability-8 (`stop()` drops pending queue silently) | FIXED | Identical: `on_event_dropped` fires 5x for 5 abandoned events. | **UNCHANGED (still fixed)** |
| D-observability-9 (no `to_dict`/`to_json`/`config` re-export) | (informational) | Identical: absent; `to_mermaid`/`to_plantuml` present. | **UNCHANGED** |

No regressions among the 9 legacy defects; all findings from the cec108b
pass carry forward identically onto 221ce7c.

---

## 2. New attacks on round-6 fixes (`new_attacks.py`)

| Attack | Target | Result |
|---|---|---|
| I: `on_event_dropped(reason="queue_full")` fires for a **loop-side** `RAISE` refusal (i.e. one the future carries, not the caller-side `qsize()` check) | #157 (reopened) | **PASS, and reproduced this time** — 16 threads x 40 `send_threadsafe("GO")` against `max_queue_size=2` with a 3ms slowed action: 0 caller-side raises, 638 future-side `QueueOverflowError`s, and **exactly 638** `on_event_dropped(reason="queue_full")` hook firings — a 1:1 match, confirming "exactly once per refusal" holds even at this concurrency. This is the saturation window the cec108b pass's attack H could not force (that run saw 0/3200 refusals); the fix is confirmed working as designed. |
| J / J′: `get_persisted_snapshot()` refused from inside an **entry action**, at the ROOT, on both engines | #169 | **PASS on both engines** — sync: `snap_err=SnapshotMidStepError(...)`, `snap_ok=None`; async: identical. The #169 in-flight-alone-refuses-at-root rule holds; no torn snapshot escaped through the entry-action window on either engine. |
| K / K′: `always`-chain trips `RunawayChainError` at the same lap count on both engines, observable via `last_error` | #166/#168 (sync/async parity) | **PASS, same lap count** — both `SyncInterpreter` and `Interpreter` trip at `n=25` for `maxIterations=25` (i.e., 25 `inc` actions ran before the trip on both), `status="running"`, `last_error` is `RunawayChainError` on both. Confirms the CHANGELOG's "invoke cycle now trips at the same lap count on both engines" for the plain `always`-self-loop case too. |
| L: async chain/settle budget is **not reset** by 16 concurrent external `send_threadsafe("PING")` senders racing a self-generated `always` chain | #166 (per-macrostep settle budget, external-event-only reset) | **PASS (trips)** — `RunawayChainError` fires (`last_error` set) despite continuous external `PING` traffic throughout the 1s window; `n` grew large (43,110) because each external `PING` legitimately starts a **new** macrostep with its own fresh budget (that is the documented, correct reset trigger — "reset only when an external event begins its step") and the `always` re-fires from `a` every time. The important assertion — that the *chain itself* still traps `RunawayChainError` and does not spin forever silently even under sustained external pressure — holds. |
| M: `service_pool_size=1` with 50 invoked plain-`def` services, `stop()` mid-flight | #173 | **PASS** — no hang, no crash: `stop()` returned in 0.07s with `status="stopped"`, 3/50 services had completed by the time `stop()` was called (consistent with a pool of 1 serialising them), `last_error=None`. Cutting the pool to the documented minimum did not surface a deadlock or an unhandled exception on shutdown. |
| N: `await Interpreter.start()` returns with the initial state's `invoke` children registered; `start(); send("CANCEL")` ordering matches `SyncInterpreter` | #171/#116 | **PASS (ordering)** — `status_after_start="running"`, the immediate `CANCEL` receipt shows `changed=True` and the machine reaches `cancelled` cleanly with no dropped/ignored event; consistent with the initial invoke registering before the first inbox read. Direct inspection of a `children` registry attribute was **not possible** (`Interpreter` has no public `children` attribute; the probe's `hasattr` check returned `False`), so child-registration-*by name* was not independently confirmed — only the *behavioral* consequence (no missed `sendTo`/ordering glitch) was verified. Flagged as a probe limitation, not a defect. |
| O: `send_threadsafe(internal=None)` self-issue from inside an action, in-flight counter settles cleanly through a chain-budget trip (no leak) | #172/#150 | **PASS** — `_threadsafe_self_sends_in_flight` reads back `0` after the chain trips `RunawayChainError` at `n=16` (budget 15, +1 for the one in-flight send that was "discarded" per the log: "discarded 1 of them"); the counter did not leak positive, which is what would have suppressed future chain-budget resets per R6-12's prior root cause. |

All eight new attacks (I, J, J′, K, K′, L, M, N, O) held up; the loop-side
`RAISE` observability fix (#157) was the one prior-pass attack that
**newly reproduced its target condition this round** (0/3200 → 638/638 in
this run), closing out that gap from the cec108b report's own coverage
notes.

---

## 3. New defects filed

No new defects were confirmed this pass. Every round-6 observability-relevant
fix attacked (I, J/J′, K/K′, L, M, N, O) held under the reduced, single-run
attack set exercised here; no Blocker/High/Medium-severity regression was
reproduced.

One **probe limitation** (not a library defect) is worth recording: attack N
could not directly enumerate `Interpreter`'s registered child actors —
there is no public `children`/`actors` attribute exposed on the interpreter
for a test harness to introspect synchronously right after `start()`
returns. The behavioral proxy (immediate `send("CANCEL")` resolving with
`changed=True` and no dropped/ignored-event signal) is consistent with
#171's fix but is one level removed from directly counting registered
invoke-children. Not filed as `D7-observability-n` since it is a test/API
observability *ergonomics* gap in what a caller can introspect, not a
defect in the fix itself — flagged here for whoever picks up a deeper #171
re-verification.

---

## 4. Not covered this pass (explicit, per the reproduce-before-you-count standard)

- Persistence property test: snapshot from every hook (`on_transition`,
  `on_action`, `on_guard`, entry/exit of nested+parallel, inside deferred
  replay, inside an `after`-timer callback) must be refused-or-legal, never
  torn, across **>=300 random machines** — **not run**. Attacks J/J′ cover
  only the single documented entry-action-at-root case, not the full hook
  matrix or nested/parallel shapes.
- Restore+resume trace parity (persist mid-run, restore, resume, compare
  trace to an uninterrupted run) — **not attacked**.
- `service_pool_size=1` + done-callback double-fire under concurrent
  cancellation races — attack M covers `stop()` mid-service at steady
  concurrency but not a deliberately adversarial double-fire (e.g., two
  overlapping `stop()` calls, or cancelling a future mid-callback).
- Config fuzzer for livelock across **both** engines (nested invoke cycles,
  `always` cycles, rollback+`onDone`, `sendTo` self-loops), **>=500**
  generated configs with a 30s watchdog, trip observable via
  `last_error`/receipt — **not run** (the R6-01/02/03 livelock class from
  the prior findings register was not independently re-fuzzed this pass;
  only the plain single-state `always`-loop case was exercised in K/K′/L).
- 50x identical-trace determinism cross-check (both engines, same lap
  count at trip points, hash-seed sweep) — **not run** beyond the
  single-run same-lap-count check in K/K′.
- Perf-PR (#165/#176) sentinel-aliasing cross-talk check (two machines,
  shared init/exit sentinel) — **not attacked**.
- Guard-crash vs denied vs deferred vs unhandled 4-way disposition matrix
  (R6-10's `onUnhandled:"defer"` shadowing `guard_denied`) — **not
  independently re-attacked** this pass; the findings register's R6-10
  claim was not re-verified against 221ce7c.
- Security: `internal=True` forgery from an unrelated (non-self-send)
  caller post-fix, redaction, `__slots__` attribute surface — **not
  attacked** this pass (see prior pass's attack G, also inconclusive).
- 12-minute soak (200 machines, rollback+onDone, always-into-invoke,
  executor services, chaos-snapshot-at-quiescence, CPU-bounded/no-livelock
  assertion) — **not run at all**, given the 20-minute overall wall-clock
  bound for this task.

## 5. Verdict

Round 6's observability-relevant fixes hold up under the reduced,
single-run attack set exercised here. The headline result is **#157's
loop-side `RAISE` refusal observability now reproduces cleanly** (638/638
loop-side refusals fired `on_event_dropped(reason="queue_full")` exactly
once each) — the one gap the prior pass (cec108b) explicitly flagged as
"not reproduced this pass" is closed with a purpose-built saturation
harness (16 threads x 40 sends, 3ms slowed action, `max_queue_size=2`).
`RunawayChainError` observability for a plain `always`-self-loop is
confirmed at the **same lap count on both engines** (#166/#168), the
per-macrostep settle budget correctly resists reset by sustained external
`send_threadsafe` traffic while still trapping the self-generated chain
(#166), the entry-action snapshot refusal at the root holds on both
engines (#169), `service_pool_size=1` survives a mid-service `stop()`
without hanging or crashing (#173), and the `send_threadsafe` in-flight
counter settles to zero even when the chain trips mid-flight (#172).
`start()`/`invoke`-registration ordering (#171) behaved correctly in the
one behavioral probe run, though direct child-registry introspection was
not possible with the public API surface (flagged, not filed).

No Blocker/High-severity observability regressions were found in this
pass. This remains a narrow, time-boxed slice of the requested matrix —
the persistence property test (>=300 cases), the both-engine config
fuzzer (>=500 configs), the 50x determinism sweep, the 4-way guard-crash
matrix, the security forgery/redaction attacks, and the 12-minute soak
were **not run this pass** (see §4) and should not be read as confirmed
by this report.


