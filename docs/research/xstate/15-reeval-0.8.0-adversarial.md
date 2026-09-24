# 15 — Adversarial re-evaluation of xstate-statemachine 0.8.0

**Target:** `_ref/xstate-statemachine` @ v0.8.0 (commit `9bf6065`), installed
editable into `.venv-gate`.
**Method:** 11 purpose-built adversarial probes under
`docs/research/xstate/probes/v080/`, attacking the wave-3 features the way an
OMS would: partially-applied order state, fills racing invokes, backpressure,
crash/restore, virtual time, and cross-thread producers.
**Raw output:** `probes/v080/ALL_RESULTS.txt`.

Framing note, per the 0.8.0 release notes: most fixes are **per-machine
policies or additive APIs whose default preserves 0.7.x semantics**. A probe
that "fails" against a default is therefore classified below as either a
genuine defect, or a *documented opt-in* that becomes a CandleViewer
configuration constraint. Every finding here was separately controlled — a
"side effect not rolled back" claim is only listed after a control run proved
the side effect happens at all.

| Probe | File | Score |
|---|---|---|
| A — rollback / fail | `a_rollback.py` | 15/17 |
| A follow-up controls | `a_rollback_followup.py` | 3/5 |
| A12 redo (live child) | `a12_sendto_redo.py` | 1/2 |
| B — onUnhandled defer | `b_defer.py` | **9/9** |
| C — inbox + receipts | `c_inbox_receipts.py` | **13/13** |
| D — restore + invokes | `d_restore_invokes.py` | 8/9 |
| E — clock + timer lane | `e_clock_timers.py` | 8/9 |
| E7 — sync timers in a loop | `e7_sync_timer_in_loop.py` | 3/4 |
| F/G — strict + threads | `f_strict_and_threads.py` | 14/15 |
| H — engine parity | `h_engine_parity.py` | 6/8 |
| I — deprecations | `i_deprecations.py` | 7/10 |

---

## 1. Confirmed new defects

### D-1 (High, for us) — `SyncInterpreter` timers are lost when the interpreter is created inside a running asyncio loop

**Probe:** `e7_sync_timer_in_loop.py` E7b (and E7 in `e_clock_timers.py`).

`RealClock.set_timeout` branches on the *caller's* context, not on which
engine owns the clock:

```python
try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    loop = None
if loop is not None:
    return loop.call_later(max(0.0, delay_sec), fn)   # asyncio lane
return self._heap.push(self.now() + max(0.0, delay_sec), fn, owner)
```

A `SyncInterpreter` constructed **from inside a running loop** therefore parks
its `after` deadlines on `loop.call_later`, leaving `clock._heap` empty.
`SyncInterpreter.tick()` and the pump at the top of `send()` both call
`clock.pump()`, which drains only the heap — so they find nothing and the
timer never fires through the sync engine's own API.

Measured (probe E7a vs E7b, same machine, `after: {40: "b"}`):

| context | `clock.pending` | state after `tick()` |
|---|---|---|
| off-loop thread (control) | 1 | `{'sy.b'}` ✅ |
| inside a running loop | **0** | `{'sy.a'}` ❌ |

This is exactly the shape #50 was meant to fix, just displaced: the sync
engine no longer spawns a thread per timer (E6 confirms 25 machines → **+0
threads**), but in a loop context it now schedules onto machinery its own pump
cannot reach. It bites any async app that keeps one sync machine for a hot
path, and any async test that constructs a sync machine.

Partial mitigation observed: E7c/E7d pass because the asyncio `call_later`
callback still enqueues the event, so a *later* `tick()` after enough loop
turns picks it up. The failure is that `tick()` is not authoritative — it
cannot deliver a deadline that is genuinely due.

### D-2 (Medium) — rollback restores state, but does not retract already-emitted effects

**Probes:** `a_rollback.py` A11, `a_rollback_followup.py` A11s/A16,
`a12_sendto_redo.py` A12r.

`actionErrorPolicy: "rollback"` is a **context + configuration** transaction.
It is not an effect transaction. When an earlier action in the same list has
already emitted something outward, that emission survives the rollback:

* **`raise`** — a `raise`d event queued before the failing action is still
  delivered. A11: `seen=['PING']` while the configuration correctly rolls back
  to `rs.a`. Control A11c proves the raise is a real delivery; A11s shows the
  sync engine behaves identically; A16 shows it escapes under `"fail"` too
  (machine goes to `status=error` *and* the event was delivered).
* **`sendTo`** — A12r, with the child invoked on a *surviving* parent state so
  it is alive across the transition: `hits=1` after a full rollback to
  `st2.up.a`. Control A12c2 confirms one hit is the normal delivery count.

Note the first A12 attempt (`a_rollback.py` A12) "passed" vacuously — the
invoke sat on the source state, so exiting it killed the child before delivery
and the control showed zero hits too. That is why A12 was redone; the redo is
the finding.

Why this matters for an OMS: the whole point of rollback is that a
half-applied order transition cannot be observed. If the failing entry action
runs *after* a `sendTo` that told the risk actor "order is live", the machine
rolls back to `idle` while the risk actor believes an order exists. The
library's guarantee is narrower than the word "rollback" implies.

Correctly rolled back, for contrast — all verified green:
context (A1, A14), configuration (A1–A5), timers armed by the partially
entered target (A6), invokes armed by it (A7), timers of the state we exited
are **re-armed** (A8), and spawned actors are stopped and unregistered.

### D-3 (Low) — async engine emits no `on_transition` for the initial entry; the sync engine does

**Probe:** `h_engine_parity.py` H1 / H7.

Driving one machine (nested + parallel + guards + `always` + entry/exit +
internal `raise`) through both engines with an identical 11-event sequence:

* trace lengths differ by exactly one — async 36, sync 37;
* the extra sync entry is
  `('T', 'par', '___xstate_statemachine_init___', ('par', 'par.boot'))`;
* **filtering that single synthetic init transition makes the two traces
  byte-identical** (H1b: 36 entries, `identical`).

So the single-core refactor is real and the divergence is one hook call, not a
semantic difference. But a plugin that counts transitions, or persists one row
per transition, gets a different count per engine for the same machine.

Everything else in H is clean: per-event context parity (H2), final
configuration parity (H3), async self-determinism across repeat runs (H4), and
parity is preserved under `onUnhandled: defer` (H5) and under
`actionErrorPolicy: rollback` with a raising action (H6).

### D-4 (Low) — the `actionErrorPolicy` DeprecationWarning cannot be relied on to warn before the 1.0 flip

**Probe:** `i_deprecations.py` I4, I8, I10.

The warning is emitted from `_apply_action_error_policy`, i.e. **only when an
action actually raises**. Three consequences:

* **I4** — a machine whose actions never raise in testing gets **0 warnings**,
  yet its behaviour still changes in 1.0 (committed → rolled back) the first
  time an action raises in production. The warning fires exactly when you are
  least able to act on it.
* **I10** — the one-shot flag (`action_error_policy_is_default`) lives on the
  **machine object**, not the interpreter. A second interpreter built over the
  same machine gets **0 warnings** (first: 1, second: 0). Any process that
  builds one machine and many interpreters — the normal actor-per-order shape
  — sees the warning once, ever, possibly in an unrelated request.
* **I8** — `stacklevel=3` lands the warning on `base_interpreter.py`, not on
  user code, so `-W error::DeprecationWarning` plus a traceback does not point
  at the machine that needs pinning.

The warning machinery itself is otherwise correct: one-shot per machine (I2),
silenced by an explicit `"continue"` (I3), emitted by both engines (I9).

### D-5 (Informational) — a strict-mode violation inside an internal `raise` is invisible by default

**Probe:** `f_strict_and_threads.py` F7 / F7b.

`_check_strict` does run on an internally `raise`d event, so the typo *is*
detected. But it raises inside an action, which makes it an **action failure**,
which the default `actionErrorPolicy: "continue"` swallows:

| policy | `status` | `error` | `on_transition_failed` |
|---|---|---|---|
| `continue` (default) | `running` | `None` | `[['UnknownEventError']]` |
| `fail` | `error` | `TransitionFailedError` | `[['UnknownEventError']]` |

So strict mode is loud for `send()` from outside (F1, F2 — with a working
difflib suggestion, `Did you mean 'FILL'?`) but silent for the internal case
unless you also set a non-default `actionErrorPolicy` or register a hook.
Two features that each work interact into a blind spot.

### D-6 (Informational) — `from_snapshot` accepts only the JSON *string*, not the dict

**Probe:** `d_restore_invokes.py` D8b.

`get_snapshot()` returns a JSON string; `get_persisted_snapshot()` returns the
dict. Handing the dict back to `from_snapshot` raises
`TypeError: the JSON object must be str, bytes or bytearray, not dict`.
Storing snapshots in JSONB/Mongo and reading them back as dicts — the natural
persistence path — requires a `json.dumps()` round-trip. Cosmetic, but it is a
sharp edge on the documented durability story.

### D-7 (Nit) — `on_transition_failed` fires twice per transition under `"continue"`

**Probe:** `a_rollback.py` A9b.

A machine whose transition action *and* target entry action both raise reports
`[('bo.a', 1), ('bo.a', 1)]` under `"continue"` — two hook calls for one
transition (one per action slot). Under `"rollback"`/`"fail"` it is one, since
the first failure raises out. Defensible, but an alerting hook must dedupe.

---

## 2. Confirmed solid

These were attacked hard and did not break.

**`onUnhandled: "defer"` — 9/9, no findings.** Replay is at the head of the
queue in original order and ahead of live traffic (B1: `A,B,C,LIVE`);
still-unhandled events are re-deferred rather than dropped (B2); `DEFER_MAX`
overflow evicts the **oldest** and reports it against the evicted event
(B3: 1005 sent → 1000 held, 5 `dropped` callbacks, 1000 replayed); the buffer
survives snapshot → `from_snapshot` → replay (B4); no replay spin on a state
change that arms nothing (B6); sync/async replay-order parity (B7); replay also
triggers on an `after`-driven state change (B8); system events are never
deferred (B9).

**LC-03 is genuinely closed end to end (B5).** A `FILL` arriving one microstep
before its handler is armed — while the submit invoke is still running — is
held (`deferred_count=1`) and applied on `onDone`: `log=['FILL']`,
`states={'oms.working'}`. This was the original blocker.

**Bounded inbox + receipts — 13/13, no findings.** `RAISE` fires
`QueueOverflowError` at the call site at exactly the bound (C1); `DROP_NEWEST`
logs and fires `on_event_dropped` and keeps running (C2); `BLOCK` applies real
backpressure with zero loss (C3: 20/20, producer suspended 281 ms); a `BLOCK`
send **issued from inside an action** does not self-deadlock — it is correctly
rerouted to the internal queue (C4: 12/12); `priority=True` is exempt from the
bound (C5) and jumps a 20-deep backlog to index 0 (C10); `queue_depth` never
exceeds `max_queue_size` (C13).

**`send(wait=True)` is a true receipt (C6).** It resolves only after the whole
macrostep including an `await`ing action: context observed at `99`,
`changed=True`, settled `state_ids`. It reports the **settled** state after
`always` transitions (C12: `al.c`, not `al.b`), carries the action error under
both `continue` and `rollback` (C8/C9), reports `changed=False` for an
unhandled event (C7), and on a stopped interpreter resolves with an
`InterpreterStoppedError` in `receipt.error` instead of hanging (C11).

**Clock injection and the timer lane — solid on the async engine.** A 30 s
`after` fires in **0.0002 s** of wall clock (E1); two identical virtual runs
produce identical traces (E2); close-deadline ordering is correct (E3);
children inherit the parent's clock, verified by identity (`child.clock is
clock`) and a 20 s child timer firing in 0.065 s (E8); delayed self-send works
under virtual time (E9). **Starvation is fixed (E4):** under a 2000-event
burst a 40 ms timer fired with `lateness_ms` between **0.05 and 8 ms** across
runs, versus the ~180 ms the changelog cites for 0.7.x. `AfterEvent` carries
real `scheduled_for` / `fired_at` / `lateness_ms` (E5).

**Resumable invocations — 8/9.** `pending_invocations()` reports the stalled
invoke (D1); `restart_services=True` re-runs it exactly once and completes the
machine (D2); the restarted invoke receives the correctly resolved `input`
(D3: `{'oid': 'static-oid'}`); **entry actions do NOT re-run** on restore +
restart (D4 — the critical one: an entry action that emits an order fires
once, not twice); the default restore starts nothing but *reports* the pending
invoke so the caller can decide (D5); nested child-actor invokes restart (D6);
an already-completed service is **not** wrongly re-invoked (D7); context is
deep-copied, not aliased (D8).

**Cross-thread sends — 3/3 plus a good error.** `send()` from a foreign thread
raises `WrongThreadError` at the call site with zero silent loss (G1);
`send_threadsafe()` under a saturated loop delivered **300/300 in order**
(G2); six threads × 100 events delivered **600/600 with per-thread FIFO
preserved** (G3); after the owning loop is closed it raises a `RuntimeError`
that says exactly that (G4).

**Strict mode — 8/9.** Unknown events rejected at the call site with a difflib
suggestion (F1, F2); wildcards `mouse.*` and bare `*` correctly not rejected
(F3); ctor flag beats the config key (F4); `event_schemas` validate payloads
and only for registered types (F5, F6); system events exempt (F9); sync engine
parity (F8). Note F10: strict is **machine-wide**, not per active state — an
event declared on any state in the tree is accepted while that state is
inactive. That is the documented `is_known_event` contract, not a defect, but
it bounds what strict catches.

**Rollback's hard parts.** Timers and invokes armed by a partially entered
target are cancelled (A6, A7); timers of the exited source are re-armed so the
restored state is live rather than inert (A8); `start()`-time entry failures
put the machine in `status=error` with `TransitionFailedError` rather than a
half-built configuration (A4); parallel-region entry failure does not leave
region 1 half-entered (A5); `"fail"` stops the machine correctly (A13);
`last_transition_ok` sequences `True → False → True` (A10) and both engines
agree (A10b) — though note it is **per-event, not sticky** (A17): the next
event, *including an unhandled one*, resets it to `True`.

**Build-time validation (I5, I6).** An unresolvable target is an
`InvalidConfigError` by default with a precise message;
`strict_targets=False` downgrades it to a `DeprecationWarning`. This confirms
doc 14's reading of the A18/C15 "regressions" as correct fail-fast behaviour.

---

## 3. Required CandleViewer constraints

Derived directly from the findings above. These are adoption conditions, not
preferences.

**C-1 — Pin `actionErrorPolicy` explicitly on every machine.** Never rely on
the default. Given D-4, the deprecation warning will not reliably reach us
before the 1.0 flip. Use `"rollback"` for order/position machines;
`"fail"` for machines where a half-applied step must halt the process.
Add a build-time assertion that every machine config carries the key.

**C-2 — Emit outward effects only from entry actions of the committed state,
never from a transition action list that has work after it.** Because of D-2,
a `sendTo` or `raise` that precedes a failing action is not retracted. Rule:
the action that talks to the outside world (order gateway, risk actor, WAL) is
the **last** action in its list, or lives on the entry of a state that is only
reached once the transition has committed. Treat `rollback` as
"context + configuration only" in design reviews.

**C-3 — Do not construct a `SyncInterpreter` inside a running event loop if it
uses `after` timers.** Per D-1 its deadlines become unreachable by `tick()`.
Either keep sync machines entirely off-loop (a dedicated thread, as probe E7a
does) or use the async `Interpreter` inside the loop. If a sync machine must
live in a loop context, inject a `SimulatedClock` or a custom clock that always
uses the heap, and drive it explicitly.

**C-4 — Set `strict: true` *and* a non-default `actionErrorPolicy` together.**
D-5 shows strict alone is silent for internally `raise`d typos under the
default policy. The pair is what closes the typo class. Additionally register
an `on_transition_failed` hook that alerts, since it is the only observation
point under `"continue"`.

**C-5 — Bound every inbox and choose the policy per machine.** The bounded
inbox is solid (13/13), so use it. Market-data ingress: `DROP_NEWEST` with the
`on_event_dropped` hook wired to a counter. Order/execution machines:
`RAISE`, and treat `QueueOverflowError` as a hard incident — never
`DROP_NEWEST` on an order path. `BLOCK` only where the producer can legitimately
be suspended, and note C4 confirms it is safe from inside an action.

**C-6 — Use `send(wait=True)` for any decision the caller gates on, and
`send_priority()` for risk/kill paths.** C6/C10/C12 confirm both work as
advertised. Do not poll `current_state_ids` after a fire-and-forget send.

**C-7 — Restore policy: always call `pending_invocations()` and decide
explicitly; never blanket `restart_services=True`.** D5/D7 show the default is
"stuck but observable" and that completed services are not re-run. For an OMS,
re-invoking a submit is a duplicate-order risk: the recovery path must
reconcile each pending invocation against the venue before restarting it.
D4 (entry actions do not re-run) is what makes this safe to reason about.

**C-8 — Persist snapshots as the JSON string from `get_snapshot()`.** Per D-6,
`from_snapshot` will not take a dict. Store the string, or `json.dumps()` on
the way back in. Wrap this in our own `save_machine`/`load_machine` helpers so
the constraint is enforced in one place.

**C-9 — Any plugin that counts or persists transitions must tolerate the
initial-entry hook asymmetry (D-3), or be pinned to one engine.** If we
persist one row per `on_transition`, filter the synthetic
`___xstate_statemachine_init___` event explicitly rather than assuming engine
agreement. Similarly, dedupe `on_transition_failed` (D-7).

**C-10 — Use `SimulatedClock` for all time-dependent tests.** E1–E3, E8, E9
show it is deterministic, correctly ordered, and inherited by children.
Gotcha to encode in a test helper: `increment()` takes **milliseconds** and,
inside a running loop, returns a `_MustAwait` wrapper that is *neither a
coroutine nor a future* — an `asyncio.iscoroutine()` guard silently skips the
await and no timer fires. Always `await` whatever it returns. Our probes wrap
this as `_advance(clock, seconds)` in `e_clock_timers.py`; ship the same helper.

**C-11 — `last_transition_ok` must be read immediately after the send that it
describes.** A17 confirms it is reset by the very next event, including an
unhandled one. Prefer `send(wait=True)` and read `receipt.error`, which is
bound to a specific event and cannot be clobbered.

---

## 4. Net assessment

0.8.0 is a large, real improvement over 0.7.0 on exactly the axes that blocked
us. The two features we most needed — **defer** (LC-03) and **bounded inbox +
receipts** — are 9/9 and 13/13 under deliberately hostile probing, and the
starvation fix is measurable (timer lateness ~0.05–8 ms under a 2000-event
burst). The single-core refactor is genuine: two engines, one 36-entry trace,
identical.

The findings that remain are narrower than 0.7.0's. One is a real bug we can
hit (D-1, sync timers in a loop). One is a scope mismatch between what
"rollback" promises and what it delivers (D-2) — the library's behaviour is
self-consistent, but the name oversells it and our design must compensate.
The rest are observability seams (D-3 through D-7) that we can close with
configuration and a thin wrapper layer.

None of these is a blocker, provided constraints C-1 through C-11 are adopted
as written.
