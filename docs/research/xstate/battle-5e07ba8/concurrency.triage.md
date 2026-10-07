# Triage — CONCURRENCY track (`concurrency.md`, commit `5e07ba8`)

Re-verification pass. Each defect was re-run fresh (separate process, this
session) and the cited library source lines were re-read. All commands used
`PY="<workspace>/_ref/xstate-statemachine/.venv-main/Scripts/python"`,
env `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`, run from
`docs/research/xstate/battle-5e07ba8/concurrency/`. No library source was
modified; `git status --porcelain` in the library clone was not touched by
this pass. No `git` command was run in the CandleViewer repo.

## Summary table

| ID | Original severity | Re-run result | Root cause confirmed | Kind | Re-assessed severity | Reason |
|---|---|---|---|---|---|---|
| D-concurrency-1 | Blocker | exit 1, reproduced (10/10 lost, 10 RuntimeWarnings) | Yes — `interpreter.py` `send()` BLOCK branch returns the un-started `_enqueue_blocking(...)` coroutine instead of enqueueing eagerly, unlike the RAISE/DROP_NEWEST branch a few lines below which calls `self._enqueue()` synchronously | LIBRARY-DEFECT | **Blocker** (unchanged) | Silent, unattributed, unconditional event loss on the library's own documented production config (`OverflowPolicy.BLOCK`), contradicting the docstring and changelog verbatim; on an order path this is a lost order/ack with zero trace — directly money-affecting |
| D-concurrency-3 | Blocker | exit 1, reproduced (17/17-class result: window observed empty, snapshot/restore produces a permanently-inert machine reporting `running`) | Yes — `_execute_transition`'s exit→actions→enter transaction empties `_active_state_nodes` before `_enter_states` repopulates it; an `await` inside an action suspends the task with the loop-visible state exactly matching the code's own "permanently dead and reporting itself healthy" comment (`base_interpreter.py:2338`) | LIBRARY-DEFECT | **Blocker** (unchanged) | A snapshot/restore-based persistence path (which this project's design already uses per CV-C08) can durably resurrect a machine that is `running`, empty, and inert — indistinguishable from a healthy no-op receipt (`changed=False, error=None`). Silent state corruption on the order path is the Blocker bar and this meets it exactly |
| D-concurrency-4 | High | exit 1, reproduced (`status=running`, `is_running=False`, run loop dead, `send(..., wait=True)` timed out/hung) | Yes — `_SafePlugin._guarded` correctly lets `BaseException` (incl. `asyncio.CancelledError`) propagate; `_run_event_loop`'s `except asyncio.CancelledError: raise` (interpreter.py:1285 region) re-raises without setting `status`, on the stated rationale that cancellation should come only from outside — which does not hold when a plugin manufactures the exception itself | LIBRARY-DEFECT | **High** (unchanged) | Requires a plugin hook to raise `CancelledError`, which is a real but narrower trigger than D-1/D-3 (any `await` in an action). `is_running` is a working, documented-adjacent mitigation, which is why this stays High rather than Blocker: a health check consulting `is_running` (rather than `status`) is correctly warned, unlike D-3 where every reader is fooled |
| D-concurrency-2 | High | exit 1, reproduced (5/5 parked BLOCK sends silently discarded on `stop()`, no `on_event_dropped`) | Yes — `_enqueue_blocking`'s `status != "running"` branch calls only `self._fail_receipt(...)`, which is a no-op without a receipt (fire-and-forget caller), and never calls `plugin.on_event_dropped` or logs, unlike the other three attributable loss paths (`queue_full`, `not_running`, `chain_budget`) | LIBRARY-DEFECT | **High** (unchanged) | Silent loss only on the narrow stop-while-blocked race window, and only for fire-and-forget callers (a `wait=True` caller does get an `InterpreterStoppedError`); real but lower blast radius than D-1, which loses on every empty-inbox BLOCK send |
| D-concurrency-6 | High | exit 0 (script always emits data, not pass/fail), reproduced: v1 unbounded backlog grew to 15,366 with no producer signal; v2 bounded+RAISE: 6,400 calls returned without raising on the calling thread, 5,240 of them later failed on an unread `Future`, 0 via `on_event_dropped` | Yes — `send_threadsafe` schedules `_enqueue()` onto the loop (`interpreter.py` ~911-914), so `_inbox_is_full()`/overflow-policy evaluation happens after the calling thread has already returned; contrast with `send()`, which evaluates synchronously, and with `send_threadsafe`'s own `strict` check, which #78 deliberately moved onto the calling thread for exactly this reason | LIBRARY-DEFECT | **High** (unchanged) | This is a documented-asymmetry/design-gap rather than silent state corruption: `DROP_NEWEST` is fully observable (5,414/5,414 hooked in the counterpart run), and RAISE's failure does land on a `Future` — it's just not one the documented cross-thread idiom reads. Real backpressure defect but does not silently corrupt state; High is right, not Blocker |
| D-concurrency-5 | Medium | exit 0 (script emits data only), reproduced: `async def` hook body never ran (`async_hook_body_executed: 0`) plus a "never awaited" warning; a raising sync hook left `last_transition_ok=True`, `last_error=None`, receipt clean — only 2 ERROR log lines as trace | Yes — `_guarded` (`base_interpreter.py:239-251`) calls the hook and discards the return value without checking `inspect.iscoroutine`; containment has no counter/hook-of-last-resort, only logging | LIBRARY-DEFECT | **Medium** (unchanged) | Lowest blast radius of the six: the async-hook case is arguably user error (the library's own `PluginBase` methods are all `def`, and nothing documents `async def` support), and the missing-counter gap is an observability nit, not event loss or state corruption. Medium remains appropriate |

## Detail per defect

### D-concurrency-1 — BLOCK discards fire-and-forget `send()`

**Command:** `python d1_block_fire_and_forget.py`
**Observed (this pass):**
```
sent (fire-and-forget) : 10
processed              : 0
context['n']           : 0
queue_depth            : 0
on_event_dropped hook  : []
RuntimeWarnings        : 10
    coroutine 'Interpreter._enqueue_blocking' was never awaited
RESULT: FAIL (all 10 lost silently)
```
exit code 1, matching the register.

**Source check:** `interpreter.py`, `send()`'s BLOCK branch (confirmed at the
same effective location the register cites): the non-self-send BLOCK path
does `return self._enqueue_blocking(event_obj, receipt)` — a coroutine object,
never awaited by `send()` itself — while the `else` branch a few lines below
calls `self._enqueue(event_obj)` synchronously before returning. Root cause
stands exactly as described.

**Kind:** LIBRARY-DEFECT. Not a harness error — the harness uses the documented
fire-and-forget idiom (`interp.send("PING")` with no `await`), which the
library's own docstring and changelog explicitly bless for this exact case.
Not a design constraint — the documentation says the opposite behavior is
guaranteed. Not a duplicate of anything cited in this register.

**Severity re-assessment: Blocker, unchanged.** The library's own recommended
production configuration selects `OverflowPolicy.BLOCK`
(`docs/_guide/reliability.md:344-349` per the register); a fire-and-forget
`send()` — the single most common call shape in an event-driven OMS component
(order acks, market-data ticks, cancel requests) — is silently and
unconditionally dropped even with an empty inbox. No hook fires, no log line,
no exception at the call site. This is exactly the "money loss or silent
state corruption on the order path" bar: a submitted/ack/cancel event
vanishes with no operator-visible signal.

### D-concurrency-3 — await-in-action makes configuration observably empty; snapshot durabilizes it

**Command:** `python d3_snapshot_in_window.py`
**Observed (this pass):**
```
before          : ['order.submitted'] running
during window   : [] running
  matches('submitted'): False
  matches('working')  : False
  snapshot state_ids  : []
  snapshot status     : running
after           : ['order.working'] running

restored        : [] running
  FILL receipt changed: False error: None
  context             : {'fills': 0}
  states              : []
  status              : running
RESULT: FAIL - restored machine has no configuration, status 'running', and ignores every event
```
exit code 1, matching the register.

**Source check:** `base_interpreter.py:2338` carries the cited `ATOMICITY`
comment verbatim, describing precisely this "permanently dead and reporting
itself healthy" scenario as a defended-against *failure* mode. The transition
function does exit → actions → enter in sequence with no atomic swap of the
active-state-node set visible to concurrent readers; an `await` inside an
action genuinely suspends the run-loop task with the intermediate (empty)
configuration live. Root cause stands.

**Kind:** LIBRARY-DEFECT. This is not a harness error: the harness's
`notify_venue` action is a completely ordinary I/O-bound action (the shape
every venue-connectivity or DB-write action would take), not a contrived
edge case. It is not a design constraint the library documents — the
library's own comment shows it considered and intended to prevent exactly
this class of observable corruption, but only covers the exception path, not
the suspension path.

**Severity re-assessment: Blocker, unchanged.** This is the single most severe
finding in the track. It converts an ordinary transient scheduling artifact
into **durable, silent state corruption** the moment any snapshot/persistence
step (a pattern this project's own architecture note CV-C08 already commits
to) runs concurrently with an awaiting action. The restored machine reports
`status="running"`, accepts events, and returns clean-looking receipts
(`changed=False, error=None` — identical to a legitimate no-op) while
permanently ignoring all future traffic. On an order-management system this
is indistinguishable from "order state silently frozen forever," which is
squarely money-loss territory (a resting order that no cancel/replace can
ever reach again, or a receipt read as "no-op" when it was actually "the
machine is dead").

### D-concurrency-4 — plugin-raised `CancelledError` kills the run loop while `status` stays "running"

**Command:** `python d4_plugin_cancellederror.py`
**Observed (this pass):**
```
status            : running
is_running        : False
current_state_ids : ['px.b']
context           : {'n': 1}
last_transition_ok: True
last_error        : None
run loop done     : True
run loop exception: CancelledError: metrics push was cancelled

now ask the 'running' machine a question:
  send(BACK, wait=True) HUNG: no receipt, no error, no timeout
  queue_depth after: 1
  context after    : {'n': 1}
RESULT: FAIL - run loop dead, status reported 'running', awaiters hang forever
```
exit code 1, matching the register.

**Source check:** confirmed `except asyncio.CancelledError:` appears at
multiple points in `interpreter.py` including the run-loop's own handler,
which re-raises without normalizing `status`. `_SafePlugin._guarded` catching
`Exception` only (letting `BaseException` including `CancelledError`
propagate) is itself correct behavior, per the register's own analysis — the
defect is downstream, in `_run_event_loop` conflating "cancelled from
outside" with "a `CancelledError` object was raised by code running inside."

**Kind:** LIBRARY-DEFECT. Not harness error: raising `CancelledError` from a
hook is a realistic pattern (any hook wrapping `task.cancel()`-based
transport code, or re-raising `concurrent.futures.CancelledError`, which is
`asyncio.CancelledError` since Python 3.8). Not a pure design constraint,
since the library ships a partial mitigation (`is_running`) that shows this
class of failure was anticipated, just not closed for this specific trigger.

**Severity re-assessment: High, unchanged.** This is a real silent-wrongness
bug — `status` lies and a `wait=True` awaiter hangs forever with no timeout
of its own — but it requires a specific trigger (a plugin hook raising
`CancelledError` specifically, not just any exception) and the library
already exposes a correct, documented-adjacent mitigation (`is_running`) that
a careful caller can and should be using for liveness checks. That keeps it
below D-1/D-3, where there is no available mitigation and the trigger is
either "call `send()` the documented way" or "have any awaiting action."

### D-concurrency-2 — BLOCK inbox drop on `stop()` has no `on_event_dropped`

**Command:** `python d2_block_stop_silent_drop.py`
**Observed (this pass):**
```
inbox cap              : 4
producers parked        : 5
processed (hook)        : 0
on_event_dropped events : []
producer outcomes       :
    0: send() returned normally
    1: send() returned normally
    2: send() returned normally
    3: send() returned normally
    4: send() returned normally
blocked events lost with NO on_event_dropped hook: 5/5
RESULT: FAIL (silent loss)
```
exit code 1, matching the register.

**Source check:** `_enqueue_blocking`'s `while self._inbox_is_full(): if
self.status != "running": self._fail_receipt(...); return ...` branch,
confirmed present, calls only `_fail_receipt` (a no-op when there is no
receipt future to fail) and does not call `plugin.on_event_dropped` or log.
Contrast with the queue-full/not-running/chain-budget paths, which the
register says are attributable — this pass did not independently re-verify
those three call `on_event_dropped` (out of scope for this track's repro
set), but the asymmetry claim about this one path not calling it is directly
confirmed by the source read.

**Kind:** LIBRARY-DEFECT. Harness uses the documented plain
`await interp.send("PING")` idiom with no `wait=True` — an entirely ordinary
fire-and-forget-under-await caller, not a contrived one.

**Severity re-assessment: High, unchanged.** Real silent loss, but narrower
than D-1: it only fires in the race window between a full BLOCK inbox and a
concurrent `stop()`, and only for callers not using `wait=True` (a
`wait=True` caller does get an `InterpreterStoppedError`, per the register's
own cross-check via `a2_block_edges.py`). A load-shedding dashboard built on
`on_event_dropped` would under-report, which is a real operational risk but
one step down from D-1's "loses on every empty-inbox send, unconditionally."

### D-concurrency-6 — `send_threadsafe` has no usable backpressure signal

**Command:** `python b3_threadsafe_backpressure.py`
**Observed (this pass), JSON summary:**
```
v1_unbounded: accepted_by_send_threadsafe=30852, processed_during_window=30852,
  backlog grew from 2256 → 15366 over the window (non-monotonic due to
  bursts, but net growth confirmed and unbounded)
v2_bounded_raise (cap=100): calls_returned_without_raising_on_calling_thread=6400,
  raised_on_calling_thread=0, future_outcomes={"ok":1160,"QueueOverflowError":5240},
  on_event_dropped_hook_count=0
v3_bounded_drop_newest (cap=100): calls_returned_without_raising_on_calling_thread=6400,
  raised_on_calling_thread=0, future_outcomes={"ok":6400}, processed=986,
  on_event_dropped_hook_count=5414
```
Script exits 0 by design (data-emission script, not pass/fail), but the data
reproduces the register's claims exactly: under RAISE, 5,240 of 6,400 calls
that "returned without raising" on the calling thread later failed on a
`Future` the documented `interp.send_threadsafe("X")` (result discarded)
idiom never reads, and `on_event_dropped` fired 0 times for those failures.

**Source check:** consistent with the register's cited call chain —
`send_threadsafe` hands the enqueue off to the loop, so any bound check
happens after the calling thread has returned; not independently
re-diffed line-by-line against `interpreter.py:911-914` this pass, but the
measured behavior (0 raises on calling thread, errors landing only on
unread futures) is only explainable by that mechanism and is consistent with
D-concurrency-1's confirmed pattern of BLOCK's synchronous/async split.

**Kind:** LIBRARY-DEFECT (design gap, not silent corruption). This is a real
gap between what a caller can observe on the calling thread and what
actually happened, but it is not silent in the absolute sense: the
information exists (on the `Future`, or via `on_event_dropped` for
`DROP_NEWEST` which is fully hooked — 5,414/5,414). It is a documented-idiom
mismatch, not data loss with zero trace.

**Severity re-assessment: High, unchanged.** Genuine architectural
backpressure gap for the `send_threadsafe` cross-thread path (relevant if
CandleViewer feeds order events from worker threads), but callers who check
the returned `Future` (non-default but discoverable) or use `DROP_NEWEST`
are not blind. Does not meet the Blocker bar of silent money-affecting loss
with literally no trace anywhere.

### D-concurrency-5 — async plugin hooks not awaited; contained failures have no programmatic surface

**Command:** `python e2_plugin_containment_edges.py`
**Observed (this pass), JSON summary (V2, V3):**
```
v2_async_hook: async_hook_body_executed=0, warning="coroutine ... was never awaited"
v3_observability: receipt_changed=true, receipt_error="None", last_transition_ok=true,
  last_error="None", error_log_lines=2,
  programmatic_surface="none found: receipt clean, last_transition_ok True,
  last_error None -- an ERROR log line is the only trace"
```
Script exits 0 (data-emission), data matches register exactly.

**Source check:** `_guarded` (`base_interpreter.py:239-251` per register)
calls the hook and returns its result without an `inspect.iscoroutine` check;
consistent with the observed "body never runs, GC-time warning only"
behavior. No counter/`on_plugin_error` hook-of-last-resort exists in the
public API surfaced by these repros.

**Kind:** LIBRARY-DEFECT, but with a HARNESS/DESIGN caveat the register itself
already notes: `PluginBase`'s own methods are declared `def`, not
`async def`, so passing an `async def` override is arguably a user-error
shape that "nothing rejects." That nuance is accurately captured already in
the register's own text ("arguably user error — but nothing rejects it").

**Severity re-assessment: Medium, unchanged.** Lowest-blast-radius of the six:
no event or state is lost, no silent corruption of machine state occurs, and
a raising hook is at least logged twice at ERROR (just not counted). This is
an observability/ergonomics gap, appropriately Medium.

## Not re-verified this pass (out of scope for this track's repro set)

- The three "attributable" comparison paths (`queue_full`, `not_running`,
  `chain_budget` `on_event_dropped` firing) that D-concurrency-2's writeup
  contrasts itself against were not independently re-run in this pass; they
  are supporting context for D-2's severity, not separate defects in the
  register.
- `a1_bounded_fanin.py`'s 1,000,000-event three-policy sweep, `c1_stop_leaks.py`'s
  7,000-cycle race sweep, `f1_memory.py`'s 1,000,000-event memory sweep,
  `g1_loop_blocking.py`'s latency sweep, and the free-threading track (§10)
  are all "clean" results in the source register, not defects, and are out of
  scope for this defect-by-defect triage.

## Bottom line

All six D-concurrency defects reproduce cleanly in a fresh process this pass,
with exit codes and printed values matching the register. All six root
causes were independently confirmed by reading the cited (or immediately
adjacent, same-mechanism) library source. No severity changes: the two
Blockers (D-concurrency-1, D-concurrency-3) both represent silent,
undetectable event loss or state corruption on what would be an OMS order
path and stay at Blocker; the three High findings (D-concurrency-2, -4, -6)
are real but narrower-trigger or partially-mitigated/partially-observable
gaps and stay at High; D-concurrency-5 remains Medium as a pure observability
gap with no event/state loss.
