# 33 — R5 findings register (triage + dedupe) — `xstate-statemachine` @ `3ed3099`

**Commit under test:** `3ed3099` ("Merge pull request #139 from fix/0.8.1-round4"),
unreleased 0.8.1 (`__version__` still reports 0.8.0 — keyed on commit).
**Inputs triaged:** all round-5 track submissions (persistence, concurrency, fuzz,
determinism, semantics, observability, security, soak, contracts), the `J-*` set from
`32-r5-diff-review.md`, and the regression rows from `31-r5-gate.md`.
**Method:** every claim re-run by me in a **fresh process** under the main venv
(`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`, ≤120 s per run), source read at the cited
lines, then classified and merged by root cause. Library source untouched; no writes
to GitHub. Re-run harnesses live in `docs/research/xstate/triage-r5/`
(`t1_snapshot.py`, `t2_engine.py`, `t3_receipts.py`, `t4_final.py`, `t5_last.py`)
alongside the original track scripts, which were re-executed verbatim where they
were already minimal.

**Severity scale (OMS):** Blocker = can lose/corrupt order state or disable a safety
control silently · High = wrong behaviour with a weak or absent signal · Medium =
wrong behaviour with a usable signal, or a missing signal on a correct behaviour ·
Low = cosmetic, latent, or narrow-exposure.

---

## 1. Headline

Round 4 shipped 39 fixes of visibly high quality. Round 5 confirms that the **two
hardest ones addressed their reproducers rather than their invariants**, and that a
third theme — *typed* errors on the restore path — was closed only for the fields the
reporters happened to name.

Three blockers stand, and they are the same three shapes an OMS cannot tolerate:

1. **`SnapshotMidStepError` (#102) does not enforce configuration legality on the
   write side** (R5-01) — parallel machines and entry-action windows still persist
   torn state.
2. **Nothing enforces it on the read side either** (R5-02) — a truncated
   `configuration` restores into a `running`, empty, permanently inert machine.
3. **A nested-invoke `onDone` cycle livelocks `SyncInterpreter.start()`** (R5-04)
   with no `maxIterations` value able to break it.

Plus one blocker inherited from the contract surface: **`actionErrorPolicy: "fail"`
reverts to the *source* state, bricks the interpreter, and still lets you snapshot
the result** (R5-12).

**The adoption gate does not move.**

---

## 2. Canonical LIBRARY-DEFECT register

| ID | Sev | Title | Reproduced | Merged from |
|---|---|---|---|---|
| **R5-01** | **Blocker** | `_active_leaf_present()` is an *any-leaf* test, not per-region legality; `SnapshotMidStepError` misses parallel tears and the entry-action window | ✅ | D5-persistence-1, D5-semantics-1, J-1, J-1b, J-10(exit-window) |
| **R5-02** | **Blocker** | No read-side legality check: a truncated/root-only `configuration` restores as `running` with zero leaves and is permanently inert | ✅ | D5-concurrency-1, D5-semantics-3, D5-fuzz-3(restore half) |
| **R5-03** | **High** | `from_snapshot()` leaks raw `TypeError`/`AttributeError`/`ValueError` for `version`/`status`/`history`/`actors`/`system`/`deferred` and for pre-parse payloads, escaping `except XStateMachineError` | ✅ | D5-persistence-3, D5-concurrency-2, D5-fuzz-2, D5-determinism-2, D5-semantics-4, D5-soak-1, D5-security-2, J-10 |
| **R5-04** | **Blocker** | Nested invokes whose `onDone` targets their common compound ancestor livelock `SyncInterpreter.start()`; the chain budget self-resets and no `maxIterations` bounds it | ✅ | D5-fuzz-1 |
| **R5-05** | **High** | `strict_targets=False` reopens the #108 root-target hole verbatim: configuration empties, `last_transition_ok=True`, no error on either engine | ✅ | D5-fuzz-3 |
| **R5-06** | **High** | #114 does not publish an external cancel landing before the run loop's first scheduling turn; machine reports `running` with `is_running=False` and `send(wait=True)` hangs | ✅ | D5-concurrency-3 |
| **R5-07** | **High** | #116 regression: a plain-`def` service now runs inline on the async run loop, stalling every timer, actor and inbound send for its full duration | ✅ | J-3 |
| **R5-08** | **High** | The #105 self-send gate is a `contextvars` read, so `send_threadsafe` from an action-spawned thread is classified external and `maxIterations` becomes unenforceable | ✅ | J-4 |
| **R5-09** | **High** | The settle budget is reset per **drain**, not per macrostep, so one event's legitimate settle starves the next event in the same `send_events` batch | ✅ | J-5 |
| **R5-10** | **High** | A guard raising on an **engine-driven** transition (`invoke.onDone`/`onError`) has no receipt and no error surface; the region strands silently while reporting healthy | ✅ | LD-01, LD-02 |
| **R5-11** | **High** | `Receipt(changed=False, error=None)` cannot distinguish no-op / guard-denied / unhandled-and-errored; `onUnhandled:"error"` is terminal and silent at the call site | ✅ | LIB-01, L-02, C-03b(lib half), D-observability-2 |
| **R5-12** | **Blocker** | `actionErrorPolicy:"fail"` reverts the configuration to the **source** state, bricks the interpreter, and `get_persisted_snapshot()` happily persists it | ✅ | L-01, C-03(lib half) |
| **R5-13** | **High** | `SyncInterpreter.start()`'s restore branch returns before `clock._attach(self.tick)`, so `restart_timers=True` / `from_snapshot(clock=)` re-arm a deadline nothing will ever drain | ✅ | D5-determinism-1, D5-observability-1, J-6 |
| **R5-14** | **Medium** | Any action named `spawn_*` is hijacked by the built-in spawn resolver before user logic is consulted — the one prefix that violates the library's own user-wins rule | ✅ | D-2 |
| **R5-15** | **Medium** | #130 `escalate` reaches the parent's `onError` only when the `invoke` declares an explicit `id` | ✅ | D5-concurrency-4 |
| **R5-16** | **Medium** | `send_threadsafe` has no usable backpressure signal on the calling thread; overflow is evaluated after the call returns | ✅ | D-concurrency-6 |
| **R5-17** | **Medium** | #113's non-`str` event-type guard is enforced on `send()` but not on the restore path — the path facing untrusted storage | ✅ | D5-persistence-2 |
| **R5-18** | **Medium** | `SnapshotMidStepError` / `InvalidEventError` / `SnapshotSerializationError` raise correctly but emit to no plugin hook — invisible to an audit log | ✅ | D5-determinism-3 |
| **R5-19** | **Medium** | `get_snapshot()` logs the full unredacted snapshot at DEBUG, bypassing #126; and `DEFAULT_REDACT_KEYS` misses most financial/session PII | ✅ | D5-security-1, J-7 |
| **R5-20** | **Medium** | `send()` accepts a mapping like `{"type": "GO"}` without routing it through `InvalidEventError` validation | ✅ | D5-security-3 |
| **R5-21** | **Low** | A v1 snapshot re-derives provenance from the event **name**, laundering an engine-shaped user event into a system event | ✅ | D5-persistence-4 |

---

## 3. Evidence per canonical finding

### R5-01 — Blocker — write-side legality is an any-leaf test
`triage-r5/t1_snapshot.py::A` (async, parallel `par.A`/`par.B`, snapshot taken from
`A.a2`'s entry action) → `A_refused: false`. `battle-3ed3099/persistence/d3b_partial_parallel.py`
re-run verbatim → snapshot during the `exchange` region's `onDone` yields
`state_ids=['order.submitted.risk.checking']`, **the whole `exchange` region absent**;
restore gives `status=running`, `error=None`, `dormant=False`, and `filled=0` against
`3` for the uninterrupted run. `semantics/repro/d5s1_entry_action_torn_snapshot.py`
re-run → both engines: `ACCEPTED state_ids=['oms.filled'] ctx={'filled_qty': 0}`
while the live machine settles to `filled_qty=100`.

Root cause (read at source): `base_interpreter.py:1112` —
`any(not node.states or node.is_final for node in self._active_state_nodes ...)` —
consumed at `:1156` as `if self._step_in_flight() and not self._active_leaf_present()`.
"At least one atomic state" is not SCXML legality. Legality is *exactly one active leaf
per region*, and the macrostep also stays open **after** the entry set is applied while
entry actions run, so a leaf is present there too. Both holes follow from the same
conjunct.

### R5-02 — Blocker — no read-side legality check
`triage-r5/t1_snapshot.py::B`: good snapshot `configuration=['fz','fz.b']`,
`state_ids=['fz.b']`; delete the leaf → `B_accepted: true`, `B_ids: []`,
`B_status: "running"`, and `B_ids_after_GO: []` — inert forever.
`persistence.py:186` guards *emptiness* (`configuration or state_ids`), satisfied by
`['fz']` alone; `base_interpreter.py:1442` then prefers `configuration` over the
still-correct `state_ids`, which is never consulted. The engine already owns the right
predicate and applies it only on the write side.

### R5-03 — High — untyped errors escape the documented contract
`triage-r5/t1_snapshot.py::C/E`, 11 single-field mutations → **10 untyped**:
`status=[]`/`{}` → `TypeError: unhashable type` (raised *inside* the check meant to
reject it, `persistence.py:170`); `history=3.14`/`"junk"`, `actors=7`, `system=7` →
`AttributeError` (unchecked `.items()` at `base_interpreter.py:1481/1493/1518`);
`deferred=null` → `TypeError` (`.get` returns the explicit `None`, not the default);
`version="x"/None/{}` → `ValueError`/`TypeError` from the bare `int()` at
`persistence.py:138`, which runs **before** `check_shape()`. Pre-parse: a `None`
payload → bare `TypeError`; `"{not json"` → `InvalidConfigError` (wrong type).
Matches the four independent track fuzzes (339/5000, 432/5000, 906/5000, 545/5000).

### R5-04 — Blocker — nested-invoke livelock
`fuzz/n1_repro.py` re-run under a 40 s cap: sync engine `start_alive=True` at
`maxIterations` of `None`, `10` and `1000`, RSS flat at 43 MB — a true livelock, not a
leak. Async engine `start()` *returns* with `status=running` and no error while the
loop burns ~100% CPU. `sync_interpreter.py:802-807` resets `generated`/`tripped`
whenever a macrostep leaves the queues no longer than it found them; this cycle
consumes exactly what it produces, so the budget resets every iteration.
`validation.py:132-151` `_is_dead_always_loop` requires `target is t.source` and is
structurally blind to an `onDone` targeting an ancestor.

### R5-05 — High — `strict_targets=False` root target
`fuzz/n8_strict_targets_root.py` re-run: sync after one `GO` → `states=[]`,
`status=running`, `last_transition_ok=True`, `last_error=None`; snapshots as
`configuration=['m'] state_ids=[]` and restores into the same inert state; async
identical. #108's rejection lives at `validation.py:293`, which the flag skips
wholesale. A root target is different in kind from the *unresolvable* target the flag
documents: it resolves fine, to a node that cannot be a leaf, so it also evades #31's
runtime `StateNotFoundError` surface.

### R5-06 — High — cancel before the first scheduling turn
`concurrency/n6b_cancel_before_first_turn.py` re-run, `deterministic: true`,
`result: FAIL`. With one `await asyncio.sleep(0)` before the cancel, 3/3 publish
correctly (`status=error`, `RuntimeError(... cancelled while running ...)`, receipt
`InterpreterStoppedError`). Without it, the handler body inside `_run_event_loop`
(`interpreter.py:1446-1462`) never executes because the coroutine never began, so
`_die()` never runs. This is precisely the window an `asyncio.timeout()` / `TaskGroup`
abort around startup occupies.

### R5-07 — High — inline plain-`def` service stalls the loop
`triage-r5/t2_engine.py::J3` → `J3_blocked_s: 0.601`, `J3_ticks: 0`; the original
`probes/main-3ed3099/p2_gate_and_inline.py` agrees (`j5_start_blocked_s: 0.803`,
`j5_loop_ticks_during_start: 0`). `await interpreter.start()` blocks for the service's
full duration and a concurrent 10 ms ticker gets **zero** iterations. Correct fix shape
is `run_in_executor` with the completion delivered through the priority lane, which
preserves #116's ordering guarantee without occupying the loop.

### R5-08 — High — `send_threadsafe` bypasses the self-send gate
`p2_gate_and_inline.py` re-run: `create_task` route 21 (budgeted), nested 21
(budgeted), **`send_threadsafe` from a thread 60, `j4c_threadsafe_budgeted: false`** —
ran to the probe's own ceiling with `maxIterations: 20` never engaging.
`_issued_from_own_action()` reads a `ContextVar`; threads get a fresh empty context.
This is the *documented* hand-off-to-a-worker path, not an exotic one.

### R5-09 — High — settle budget is per drain
`p2_gate_and_inline.py` re-run: a single 40-hop `always` chain under `maxIterations:50`
completes (`j6_after_start: "s40"`, `j6_after_go: "t40"`, `j6_start_ok/go_ok: true`),
but two independent events in one batch give `j6b_value: "u9"`, `j6b_ok: false`,
`j6b_err: "RunawayChainError"`. The second event inherits the first's spend. The
effective budget is `maxIterations / len(batch)` — a silent, load-dependent cliff for
anyone batching a replay. (My own re-implementation in `t3_receipts.py::J5` did *not*
reproduce it; the original probe's chain shape is the faithful one and is what I count.)

### R5-10 — High — guard raise on an engine-driven transition
`triage-r5/t4_final.py::LD01`: guard on an `invoke.onDone` under
`guardErrorPolicy:"raise"` → `ids=['ld.v']` (stranded), `status="running"`,
`interpreter.error=None`; only `last_transition_ok=False` / `last_error` are set, and
the sole hook is `on_guard_error`. A further `send("ANY", wait=True)` returns
`changed=False, error=None` and the configuration is unchanged. `guardErrorPolicy:"raise"`
is surfaced only through the `Receipt` of a `wait=True` caller — and an `onDone` branch
has no caller. **LD-02 folded in:** `pending_invocations()` reports
`[PendingInvocation('ld.v','ver','svc')]` for this *dead* strand (the service did
finish), while a genuinely running service reports `[]` — so the list is non-empty for
"crashed" and empty for "working", carries no timestamp, and cannot serve as the health
signal R5-10 leaves missing.

### R5-11 — High — the receipt cannot distinguish outcomes
`triage-r5/t3_receipts.py` (async, `wait=True`):
`onUnhandled:"error"` on an unknown event → `changed=False, error=None, deferred=False`
while `status` flips to `"error"` and `interpreter.error` holds the
`UnhandledEventError`; `last_error` stays `None`. A **guard-denied** event under the
same policy → byte-identical receipt, `status="error"`, machine parked. `rerun_prior.py`
confirms the `guardErrorPolicy` half unchanged: `false` → `(changed=False, error=None)`,
`true` → `(changed=True, error=None)` — a guard that *raised* is absorbed into a
legitimate-looking outcome under both. #84's `Receipt.deferred` closes exactly one of
the four indistinguishable cases.

### R5-12 — Blocker — `actionErrorPolicy: "fail"`
`triage-r5/t3_receipts.py::L01` and `t2_engine.py`: with a raise in `b`'s entry list,
`ids_after=['f.a']` — the **source** state, not the target and not a fault state —
`status="error"`, `ran=['ok1']` (the earlier action's outward effect already applied),
a subsequent send returns `changed=False` with `status` stuck at `error`, and
`get_persisted_snapshot()` **succeeds**, returning
`{"status": "error", "state_ids": ["f.a"]}`. #102 covers the no-leaf window; this is a
*legal-but-wrong-leaf* window and is uncovered. For a safety machine this means one
action raise permanently disables it while consumers reading `current_state_ids`/tags
see the pre-transition state.

### R5-13 — High — restore branch never attaches the clock settler
`determinism/n2b_restart_timers.py` re-run: **SYNC** subject
`dormant_after_start=False` ("re-armed") but `attached_settlers=0`, `late=0`, still in
`['tm.armed']` after `clock.increment(200)`; an explicit `tick()` recovers it
(`late_after_tick=1`). **ASYNC** `VERDICT: OK`. `sync_interpreter.py:268-283` takes the
restored branch and `return self` at `:283`, before
`if isinstance(self.clock, SimulatedClock): self.clock._attach(self.tick)` at `:307-308`.
J-6's `p4_clock_attach.py` isolates the same line for `from_snapshot(clock=)`
(`ctor_settlers: 1` vs `restored_settlers_after_start: 0`). Two round-4 features
(#128, #117) that were designed to compose both land on this one early return.

### R5-14 — Medium — `spawn_*` hijacks user action names
`contracts/repro/r2_spawn_prefix_steals_action_name.py` re-run, four-case table under
`MachineLogic(strict=True)`: `place_all_legs` → `user_action_called=['place_all_legs']`,
`ids=['m.b']` (control); `spawn_all_legs`, `spawn_entry_order`, `spawn_blocking_thing`
→ `user_action_called=[]`, `ids=['m.a']`. `base_interpreter.py:2834-2841` routes on the
prefix **before** consulting `machine.logic.actions`, while the comment twelve lines
below states built-ins are resolved "only when the user has NOT supplied an action of
the same name". Under `actionErrorPolicy:"rollback"` the resulting `ActorSpawningError`
is swallowed and the machine sits in its source state forever.

### R5-15 — Medium — `escalate` needs an explicit `invoke.id`
`concurrency/n8b_escalate_needs_invoke_id.py` re-run, `result: FAIL`:
`callable,id=True → true`, `callable,id=False → true`, `escalate,id=True → true`,
**`escalate,id=False → false`** — parent sits in `p.w` with no hook, no receipt error,
no log line. `id` is optional and the engine synthesises one; the callable failure path
handles synthesised ids, the `escalate` built-in's parent lookup does not. The library's
own regression test (`tests/test_round4_findings.py:1134-1157`) declares `"id": "kid"`,
so the id-less shape is uncovered.

### R5-16 — Medium — `send_threadsafe` backpressure
`concurrency/b3_threadsafe_backpressure.py` re-run: under `RAISE` with cap 100, 6 400
calls returned **without raising on the calling thread**; the `QueueOverflowError` lands
on a future the documented usage never reads. `DROP_NEWEST` remains fully hooked
(`on_event_dropped` 6 113). `send_threadsafe` schedules `_enqueue()` onto the loop, so
overflow is evaluated after the caller has returned — unlike `send()`, which evaluates
synchronously. Unchanged by round 4.

### R5-17 — Medium — non-`str` event type via restore
`persistence/n7_restore_event_type.py` re-run: 5/5 hostile types (`42`, `None`,
`['GO']`, `{'x':1}`, `True`) ACCEPTED, each producing `Event(type=<non-str>)` in a live
`status=running` interpreter with `hooks=[]`. `triage-r5/t1_snapshot.py::D` confirms the
asymmetry in one process: `send(42)` → `InvalidEventError`; the same value through
`pending_events` → accepted (and, separately, untyped). `persistence.py:190-196` asserts
only that the `type` key is **present**. Consequence today is mild — the event matches
nothing and is swallowed with no receipt — but this is the path facing untrusted storage,
which is the trust boundary #113 exists to defend.

### R5-18 — Medium — new error classes are invisible to plugins
`determinism/n6_observability.py::O1` plus `triage-r5/t4_final.py`: a spy binding every
`on_*` hook `PluginBase` declares sees **no** error hook for `InvalidEventError`
(`InvalidEventError_hooks: []`), nor for `SnapshotMidStepError` /
`SnapshotSerializationError`. The plumbing itself is sound — `on_plugin_error` fires for
raising and `CancelledError`-raising hooks, and `on_event_dropped` fires with
`reason="unresolved_target"` — so this is a completeness gap in the observability
contract. `SnapshotCorruptError` is correctly excluded: `from_snapshot` is a classmethod
with no interpreter in existence, so no hook can fire by construction.

### R5-19 — Medium — redaction coverage
`security/repro_D_security_1_snapshot_log_leak.py` re-run →
`DEBUG_LOG_LEAKS_SECRET: True`, log excerpt carries `"api_key": "sk-live-SECRET999"` and
`"password"` in clear. `get_snapshot()` logs the JSON snapshot verbatim via
`logger.debug`, independent of `LoggingInspector.redact()`. Compounding it, J-7's probe
shows 13 of 16 realistic sensitive keys pass `DEFAULT_REDACT_KEYS` in clear —
`account_number`, `bearer`, `cookie`, `dob`, `email`, `iban`, `mnemonic`, `pan`, `pin`,
`pwd`, `seed_phrase`, `sessionId`, `signature`. For a financial OMS the misses are the
ones that matter. The `redact()` *mechanism* is well built (pure, recursive,
case-insensitive substring, documented opt-out); the defaults and the second call site
are the problem. Secondary, latent: `plugins.py` applies `_safe()` at only two sites, so
`DoneEvent.data` and `ErrorEvent.error` are unredacted by construction — no live leak
reproduced.

### R5-20 — Medium — dict-shaped event bypasses `InvalidEventError`
`security/attack_invalid_event_hostile.py` re-run: `None`, `123`, `1.5`, `b'GO'`,
`['GO']`, `object()`, `True`, `nan` all raise `InvalidEventError` with the correct
`(InvalidEventError, XStateMachineError, TypeError)` MRO — **`{'type': 'GO'}` → NO ERROR
RAISED**, `BAD_COUNT: 1`. `triage-r5/t2_engine.py` confirms it transitions the machine
(`ACCEPTED`, `ids=['d.b']`). Arguably intended (dict events are a documented input
form); recorded because the hostile-input sweep treats it as the one gap and an adopter
validating at the boundary needs to know the mapping form is unvalidated beyond `type`.

### R5-21 — Low — v1 provenance laundering
`persistence/t4_receipts_provenance.py::P12`: a v1 record `after.hours` →
`Event system=True` (laundered), `xstate.custom` → `system=True`, `done.review`
correctly `system=False`. `events.py` re-derives provenance from the event name for a v1
record, which carries no `kind` discriminator; no other signal exists at that boundary.
Arguably unfixable as stated — the remedy is explicit migration. Exposure requires a
pre-0.8.1 blob containing a user event with an engine-shaped name, and #79 closes the
intake path for new events. Ride-along on #79/#86.

---

## 4. HARNESS-ERROR

| Claim | Disposition |
|---|---|
| `t3_receipts.py::J5` (my own re-implementation of the settle-budget batch case) | **HARNESS-ERROR (mine).** My 40-hop chain settled both batched events correctly (`J5_batch.ids=['ch.u39']`, `ok=true`). The original `p2_gate_and_inline.py::j6b` chain shape *does* reproduce. R5-09 is counted on the original probe, not on mine. |
| `t2_engine.py` first pass — sync `send()` receipt fields all `None` | **HARNESS-ERROR (mine).** `SyncInterpreter.send()` returns `None`; only the async `send(..., wait=True)` returns a `Receipt`. All receipt-shaped claims (R5-11, R5-12) were re-run on the async engine in `t3_receipts.py` before being counted. |
| `t2_engine.py` first pass — guard callable arity | **HARNESS-ERROR (mine).** Guards take `(context, event)`, actions take `(interpreter, context, event, action_def)`. Reusing one `boom` for both raised a spurious `TypeError` at the call site. Fixed; does not affect any finding. |
| `31-r5-gate.md` **LC-12** (`spawn blocking async engine`, PASS→FAIL) | **UNCONFIRMED — flaky check, not counted.** The gate's own annotation records exit code flipping between runs on the same commit, with observed values clustered at a ~250 ms threshold (254/252, 256/251, 258/254 ms). This is a threshold race in the *check*, not a demonstrated library regression. Needs ≥10 repeats before it can be cited; **not** admitted to the register. |
| `31-r5-gate.md` **LC-48** (`no error observability hooks`, PASS→FAIL) | **NOT COUNTED this round — single run, unreplicated.** The specific claim (`on_transition_failed` should precede `on_transition` with failed-action info) is deterministic-looking and plausible, but the standard here is reproduce-before-you-count and it was run once. Adjacent to R5-18; flagged for a dedicated two-run repro. |
| `31-r5-gate.md` `LC-07`, `N-3`, `N-8` (verifyM) | **NOT REGRESSIONS.** Already failing at the `3c527b0` baseline and annotated "keep open"; carried over unchanged. |

---

## 5. DESIGN-CONSTRAINT (real, documented-or-not, but not a defect to file)

| ID | Title | Note |
|---|---|---|
| DC-01 | **No public quiescence API** (was J-2) | `SnapshotMidStepError`'s own message advises snapshotting "once the step settles … or from `on_transition`". The public surface matching settle/quiesce/idle/drain is `["drain_pending", "wait_done"]`; neither answers "is a macrostep in flight?". The only predicate that does is private — and, per R5-01, wrong. Worse, the `on_transition` advice is unsound for any machine with transient states: `p3::j12` snapshots `["w.a"]`, `["w.b"]`, `["w.c"]` and `w.b` is a state the machine is *guaranteed* to leave in the same macrostep. Severity is real (it is why R5-01 has no workaround) but it is a missing feature, not a broken one. |
| DC-02 | **`SimulatedClock.increment()` dispatches on the ambient loop, not the attached engine** (was D5-semantics-2) | `clock.py:312-318` branches on whether *any* loop runs on this thread. A `SyncInterpreter` on a `SimulatedClock` inside a running loop returns `_MustAwait` objects that sync call sites discard; states never advance and the only signal is a `warnings.warn` in `__del__`, invisible under `logging.disable`/`-W ignore`/a pytest filter and arriving after the assertion already passed. **Any pytest-asyncio suite driving a `SyncInterpreter` on a `SimulatedClock` silently tests nothing.** This produced a false FAIL in one track before it was traced. Recorded as a constraint because the behaviour is coherent for the async engine; it needs a gate check, not a fix ticket. |
| DC-03 | **The `onUnhandled` defer buffer is unbounded, including in a terminal region** (was W-02) | 300 `REQUEST` events into a machine whose `auth.revoked` is `type: final`: all accepted, all reported `deferred`, `deferred_count` 300, no cap, no `on_event_dropped`, no back-pressure. `max_queue_size`/`OverflowPolicy` bound the inbox, not the defer buffer. The policy does what it says; nothing will ever drain these. Needs the gateway cap in W-04, not a library change. Result is a lower bound — the probe stopped at 300. |
| DC-04 | **Implementation resolution is lazy, not a build-time gate** (was C-01) | `create_machine(cfg, logic=MachineLogic(strict=True))` with zero actions/guards/services **builds successfully** for all five of B16–B20. The failure appears at first use as a receipt: `changed=False, error=ImplementationMissingError("Guard 'all_evidence_present' not implemented.")`. For a safety machine a missing guard is then indistinguishable from a transition that legitimately did not fire. Closed by wrapper W-01 (walk `entry`/`exit`/`on`/`always`/`after`/`invoke.onDone`/`onError` and assert presence before `create_machine`). |
| DC-05 | **Non-JSON `context` values pass `get_persisted_snapshot()` and fail in the caller's `json.dumps()`** (was A14b) | **NOT-A-DEFECT, recorded for scope.** #131 is explicitly scoped to pending *event* data, and that path correctly raises `SnapshotSerializationError`. `get_persisted_snapshot()` returns a dict, not a string, so it never claims to have produced JSON. Recorded only because the asymmetry is surprising and a team assuming the library validates JSON-ability would be wrong — the guard belongs in the adoption gate. |

---

## 6. OUR-CONTRACT-DEFECT (defects in doc 28 / our statechart JSON, not the library)

| ID | Sev | Title | Reproduced |
|---|---|---|---|
| **OC-01** | **Blocker** | The A3 inline `"*": {"actions":["defer"]}` scaffolding is **live, not "dead but harmless"**: it pre-empts `onUnhandled:"defer"` and silently disables `strict:true` machine-wide | ✅ |
| **OC-02** | Major | B2's `raise_evaluate` is a plain named action and cannot emit `EVALUATE`; an `all_or_none` group with a failed leg never unwinds | ✅ |
| **OC-03** | Major | B4 `completing` has no `LEG_A_FILL`/`LEG_B_FILL` handler, so a correctly-deferred late fill is re-deferred forever | ✅ |
| **OC-04** | Major | B16 elevation survives `LOGOUT`/`IDLE_DEADLINE`/`ABSOLUTE_DEADLINE` and can be re-acquired after revocation (privilege-escalation shape) | ✅ |
| **OC-05** | Major | B19 `stale_lockout` handles only `RECONNECTED`, inverting INV-B19-b and page-storming on flapping connectivity | ✅ |
| **OC-06** | Major | B11 `degraded` has no `STREAM_UNHEALTHY` handler; a concurrent second stream failure is parked and the health map goes stale | ✅ |
| **OC-07** | Major | The `actionErrorPolicy:"fail"` row of the mandatory policy block does not achieve halt-not-continue on this library (consequence of R5-12) | ✅ |
| **OC-08** | Medium | B14's bounded delta buffer (INV-B14-d) is prose-only — no `max`/`bound`/`limit`/`cap` anywhere in the JSON; 1 000 `DELTA`s grew the buffer 1:1 | ✅ |
| **OC-09** | Medium | B8's "no position state reachable without native SL confirmed" is observable in B1 but not enforceable by it — no `stateIn` guard exists in the JSON; the enforceable form is temporal (wrapper) | ✅ |
| **OC-10** | Low | B16 `STEP_UP_OK` while already elevated writes no audit record (the re-entry transition omits `audit_step_up`) | ✅ |

**OC-01 is the single highest-value fix on our side.** Re-run in one process
(`triage-r5/t5_last.py`), on identical machines differing only by the inline wildcard:

```
star=False  -> deferred_count = 1     (runtime defer buffer holds the event)
star=True   -> deferred_count = 0     (wildcard matched; event discarded)
strict_star=False -> UnknownEventError
strict_star=True  -> ACCEPTED
```

Doc 28 §1.3b / E50-T09 asserts "with `onUnhandled: 'defer'` set, the runtime holds the
event before any `'*'` handler is consulted". **That is backwards.** `onUnhandled` is by
definition only reached for an event that matched *nothing*; `"*"` matches everything,
so it always wins, the named `defer` action is a no-op that does nothing with the event,
and the event is discarded with no exception, no `on_event_dropped`, no
`on_unhandled_event`, and a receipt indistinguishable from a correct no-op. Separately,
one bare `"*"` puts `"*"` into `known_events`, so `is_known_event()` short-circuits and
`strict:true` becomes a no-op for the **entire machine**.

By §1.3b's own wording the scaffolding is present in all twenty contracts; it was
confirmed live on B1–B9, B12, B13 and B19. Blast radius includes a B18 kill-switch
`FAULT` delivered via `send_priority` to a machine parked in `submitting` being swallowed
— the priority lane defeated by our own JSON. Stripping only those keys moved one suite
51 PASS/4 FAIL → 54 PASS/1 FAIL with the snapshot sweep still 31/31 MATCH.

**Also lift-worthy:** `AMEND-CV-C06` — the CV-C06 ship-block on order-path statecharts
can be **lifted**. `Receipt.deferred` (#84/#106) now reads `True` for a genuinely held
event and `False` for a real no-op at the caller's await point, and the defer buffer
round-trips a snapshot. Caveat: this only becomes observable **after OC-01 is fixed** —
with the wildcard in place a swallowed event reports `changed=True, deferred=False`,
which is worse than inconclusive.

---

## 7. NEEDS-WRAPPER (carried forward, unchanged)

| ID | Title |
|---|---|
| W-01 | `cv.statechart.watchdog.StallDetector` — external per-interpreter liveness clock with per-invoke budgets. **Closes R5-10 and DC-04.** Buildable entirely from public API: a `PluginBase` recording `(monotonic_ns, frozenset(current_state_ids))` on every `on_transition`, plus an external scheduler tick comparing `now - last_transition_ns` against a per-invoke-id budget. Ship-blocker for B8. Precondition: reconcile the §8.8 vs ADR-0008 `sl_deadline` disagreement (2 s vs 3000 ms). |
| W-02 | `cv.statechart.guards` `@cv_guard` — total guards with explicit deny/allow polarity. **Mitigates R5-10/R5-11.** Deny-polarity mandatory on `tightens_only`, `explicit_audited_override`, `exchange_reports_sl`, `sl_observed`, `attach_attempts_left`, `promotion_gate_satisfied_and_permitted`, `rearm_permitted_and_elevated`. Keep `guardErrorPolicy:"raise"` as a tripwire for an unwrapped guard. |
| W-03 | `cv.statechart.invariants` — runtime assertion of the counting invariants no statechart can express (INV-B6-a, INV-B7-a, INV-B10-a/b). Driven from an `on_transition` hook; reuse the predicates as Hypothesis properties. |
| W-04 | Defer-buffer gateway cap (from DC-03): cap `deferred_count` at 32 and refuse any send to an interpreter whose active configuration is entirely final/terminal. |
| W-05 | Snapshot JSON-ability guard (from DC-05) and a quiescence wrapper (from DC-01): snapshot only from a caller-owned settled point, never from `on_transition` on a machine with transient states. |

---

## 8. Governance / supply chain (unchanged, not code defects)

| ID | Sev | Status |
|---|---|---|
| D-security-2 | Medium | `main` branch protection: 0 required reviewers, no required checks, force-push allowed. Repo governance setting, unchanged since `5e07ba8`. |
| D-security-3 | Low | GitHub Actions pinned to mutable tags, not SHAs. |
| D-security-4 | Low | No SBOM and no artifact signing in the publish pipeline. |
| D-security-5 | Low | Informational: broad `except: pass` in the CLI diagnostic path; an invariant `assert` in `interpreter.py` that `-O` strips. |

`D-security-1` (LoggingInspector logged raw context/payload at INFO) is **CLOSED by
#126** — default redaction via `DEFAULT_REDACT_KEYS`, with `redact_keys=()` remaining an
explicit opt-out. Its residue is tracked as R5-19.

---

## 9. Positive controls (no defect; recorded so the register shows what was cleared)

- **Quiescent snapshots** never raise `SnapshotMidStepError` and always round-trip
  (500-event reduced property run) — confirms #102 is correctly scoped to the mid-macrostep
  window, and that R5-01 is a *predicate* bug rather than an over-broad guard. **False
  positives were not reproduced in any track.**
- **`on_plugin_error` (#127) is well-behaved.** Fires on peers with the correct
  `(plugin, hook, error)` triple, no recursion into the failing plugin, and a watcher whose
  own `on_plugin_error` raises is contained by the `hook == "on_plugin_error"` early return.
  An `async def` hook is caught, its coroutine `close()`d, and reported with an actionable
  `TypeError`. Design note: `last_plugin_error` is last-write-wins across all plugins and
  hooks — a debugging convenience, not a metrics surface.
- **The `InvalidEventError` hierarchy (#113) is correct and complete** for scalar and
  object inputs: all of `None`, `5`, `1.5`, `b"GO"`, `[1,2]`, `object()`, `True`, `nan`,
  `{"payload":1}`, `{"type":7}` raise it on both engines, and every one satisfies both
  `isinstance(exc, XStateMachineError)` and `isinstance(exc, TypeError)`. The two holes are
  the restore path (R5-17) and the mapping form (R5-20).
- **#112 `_repair_configuration`** works: a settle trip is observable
  (`last_transition_ok=False`, `last_error` set) and leaves a legal configuration.
- **#128's dormancy half is sound:** after a plain restore without `restart_timers`,
  `has_dormant_timers` correctly stays `True` and the timer correctly never fires.
- **#133** `on_event_dropped(reason="unresolved_target")` fires; **#129** `stop()`'s
  abandoned events fire `on_event_dropped` (5/5).
- **Test-suite audit (from the diff review, re-affirmed):** no `xfail`, `skip` or `skipIf`
  added anywhere in the 24-file merge; `tests/test_round4_findings.py` is genuine
  per-issue coverage; all four edits to pre-existing tests are **tightenings**.
  `test_wave2_review_findings` is the test that would have caught R5-01 had its config
  been parallel rather than flat.

---

## 10. Counts

| Class | Count |
|---|---|
| LIBRARY-DEFECT (canonical R5-01…R5-21) | **21** (4 Blocker, 8 High, 8 Medium, 1 Low) |
| …merged away as duplicates | 22 submissions collapsed into the above |
| DESIGN-CONSTRAINT | 5 |
| OUR-CONTRACT-DEFECT | 10 |
| HARNESS-ERROR (incl. 3 of my own) | 6 |
| NEEDS-WRAPPER | 5 |
| Governance / supply chain | 4 |
| Positive controls cleared | 8 |

**Gate recommendation: HOLD.** R5-01, R5-02, R5-04 and R5-12 are each independently
sufficient to block an OMS order path. OC-01 must be fixed on our side before any
receipt-based assertion in the catalogue can be trusted, and it is a one-key-per-state
edit.

---

## 11. Time-bound disclosures

Per the standing bound, parameterisations were reduced deliberately and are stated
rather than hidden:

- The R5-04 livelock was re-confirmed under a **40 s** cap rather than the tracks'
  longer soak; a livelock is proven by non-termination plus flat RSS, both observed, so
  the shorter window is sufficient.
- Fuzz corpora were **not** re-run at their original 5 000-case sizes. R5-03 was
  re-confirmed with an **11-mutation deterministic table** (10 untyped), which reproduces
  every distinct frame the four independent 5 000-case runs reported. The large-N counts
  quoted in §3 are the tracks' own and are cited as corroboration, not as my re-runs.
- **LC-12 and LC-48 from `31-r5-gate.md` were not re-run** and are explicitly **not
  counted** (§4). Closing them needs the ≥10-repeat run the gate itself recommends.
- No benchmark, full-suite pytest, coverage or hash-seed pass was attempted; those
  remain open from `31-r5-gate.md` and are unchanged by this triage.
