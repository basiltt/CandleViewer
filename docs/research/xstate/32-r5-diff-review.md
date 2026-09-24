# 32 — R5 diff review: `5e07ba8..3ed3099` (unreleased 0.8.1)

**Scope.** All 24 files of the round-4 merge (`#139`, ~3 000 lines): every
`src/` change read in full, every `tests/` change read, plus targeted probes
for the briefed focus areas. Library source untouched. Probes live in
`docs/research/xstate/probes/main-3ed3099/`:

| Probe | Covers |
|---|---|
| `p1_midstep_snapshot.py` | J-1, J-2, J-3 |
| `p2_gate_and_inline.py` | J-4…J-10 |
| `p3_followups.py` | J-1b, J-7c, J-8b, J-11, J-12 |
| `p4_clock_attach.py` | J-7d root cause |

Run: `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv-main>/Scripts/python <probe>.py`.

**Headline.** The round-4 work is real and largely good: 39 issues, each with
a pinned regression test, no `xfail`/`skip` added anywhere, and the three
weakened-looking test edits (`test_v080_edge_paths`, `test_wave2_edge_paths`,
`test_wave2_review_findings`) are all *tightenings* that correctly encode the
new contracts. But the flagship fix — `SnapshotMidStepError` (#102) — **does
not close the hole it was written to close**, and two new behaviours (#116
inline services, `from_snapshot(clock=)`) introduce fresh defects. Net: the
adoption gate does **not** move.

Findings are ordered by severity.

---

## J-1 — BLOCKER — `SnapshotMidStepError` does not fire on a parallel machine; the exact #102 corruption is still reachable

**Probe:** `p1_midstep_snapshot.py::j1`, `p3_followups.py::j1b_sync_midstep`.

The guard is:

```python
# base_interpreter.py:1156
if self._step_in_flight() and not self._active_leaf_present():
    if _seen is None:
        raise SnapshotMidStepError(self.id)
```

`_active_leaf_present()` (line 1112) returns `True` if **any** active node in
the whole configuration is atomic. In a parallel machine, region `B` always
has a leaf, so the guard is `False` while region `A` is torn open — and the
snapshot is taken anyway.

Observed (async engine, `par` = parallel `A`/`B`, `A.a1 --GO--> A.a2` with a
300 ms action, snapshot taken 100 ms in):

```json
"j1_refused": false,
"j1_state_ids":  ["par.B.b1"],
"j1_config":     ["par", "par.A", "par.B", "par.B.b1"],
"j1_settled":    ["par.A.a2", "par.B.b1"],
"j1_restored_value":  {"A": "A", "B": "b1"},
"j1_restored_status": "running"
```

Region `A` has been erased. The blob passes `persistence.check_shape()`
(status `running`, configuration non-empty), restores without error, and
produces a machine reporting `status="running"` whose region `A` sits on the
**compound node `par.A` with no leaf** — permanently inert, exactly the #102
failure mode, now with a plausible-looking configuration instead of an empty
one. `check_shape` cannot catch it: "at least one state id" is satisfied.

Identical on the sync engine (`j1b_sync_refused: false`,
`j1b_sync_restored_value: {"A": "A", "B": "b1"}`), so this is not an
async-only race.

**A second, engine-independent route** reaches the same place on a *flat*
machine — J-10, `p2::j10_exit_window_content`. A snapshot taken from an
**exit action** of a nested source state is accepted, because the source's
leaf has not been removed yet at exit time:

```json
"j10_exit_snapshot_state_ids": ["ex2.a.a1"],
"j10_restored_value":  {"a": "a1"},
"j10_restored_status": "running"
```

Here the snapshot is *stale* rather than torn — it restores to the **source**
state of a transition that has already been committed. For an OMS that
snapshots defensively from an exit hook (a natural "record what we're leaving"
idiom) this silently rewinds the order state machine one transition. And
`p1::j2b_*` confirms it on both engines: `j2b_sync_exit_action: "ok"`,
`j2b_async_exit_action: "ok"` — never refused.

**Assessment.** #102 is fixed only for the single-region, flat, mid-action
case its own regression test (`TestMidStepSnapshotRefused`) exercises. The
guard's predicate is "the configuration has *a* leaf somewhere", but the
invariant it must enforce is "**every active parallel region** has a leaf, and
no exit set is half-applied". The correct test is per-region completeness
(each active compound node has exactly one active child; each active parallel
node has one active child per region) plus an explicit
`_in_transition`/`_exit_committed` flag rather than inferring the window from
the configuration's shape.

Remediation is not a one-liner: exit-window detection needs an explicit flag,
because the configuration alone cannot distinguish "about to exit `a1`" from
"settled in `a1`".

---

## J-2 — BLOCKER — no public API to wait for quiescence; the exception's own advice is only accidentally correct

**Probe:** `p1::j3`, `p3::j12_midstep_docs_workaround`.

`SnapshotMidStepError`'s message tells the caller to snapshot "once the step
settles (`await send(..., wait=True)`, or from `on_transition`)". That is the
entire quiescence story — there is no `await_settled()`, no `is_settled`
property, no `wait_for_quiescence()`. The public surface matching
settle/quiesce/idle/wait/drain/step is:

```json
"j3_public_quiescence_api": ["drain_pending", "wait_done"]
```

`wait_done` waits for a *final* state; `drain_pending` drains the inbox.
Neither answers "is a macrostep in flight right now?". The one predicate that
does — `_step_in_flight()` — is private and, per J-1, wrong.

**The `on_transition` advice is unsound as written.** `p3::j12` runs
`a --GO--> b`, where `b` has an `entry` action and an `always` to `c`. The
hook fires three times and each snapshot succeeds:

```json
"j12_on_transition_snapshots": [["w.a"], ["w.b"], ["w.c"]],
"j12_final_value": "c"
```

Snapshot #2 (`w.b`) is taken from a **transient** state the machine is
guaranteed to leave in the same macrostep. Persisting it and restoring later
puts the machine on `b` — a state whose `always` will re-fire on the next
drain, so this particular config self-heals. A config whose transient hop is
guarded on context that has since changed will not. The docs sell
`on_transition` as the safe snapshot point; it is the safe point only for a
machine with no transient states, and nothing says so.

Practical consequence for an OMS: there is no supported way for an external
persistence thread to say "take a consistent snapshot now". The only
correct-by-construction pattern left is `await send(..., wait=True)` on the
same task that owns every send — i.e. single-threaded, no external
snapshotter. That is a real capability gap, not a documentation gap.

**Note in the guard's favour:** `j2_on_transition: "ok"` /
`j2_entry_action: "ok"` confirm the recursive-child branch
(`_await_settled_for_snapshot`, 0.5 s bound) does not spuriously refuse a
legitimate snapshot from a plugin hook or entry action. The false-*negative*
direction (J-1) is the problem; false positives were not reproduced.

---

## J-3 — HIGH — #116 regression: a slow plain-`def` service now blocks the async event loop for its full duration

**Probe:** `p2::j5_slow_sync_service`.

`interpreter.py` now routes any `_is_plain_sync_callable(service)` through
`_invoke_plain_service_inline()`, which calls it **on the run loop**. The
changelog and the code comment frame this purely as engine-parity for
ordering. It is also a throughput cliff.

A service doing `time.sleep(0.8)` (stand-in for a blocking DB call, a
`requests.get`, a CPU-bound repricing pass):

```json
"j5_start_blocked_s": 0.801,
"j5_loop_ticks_during_start": 0
```

`await interpreter.start()` blocked for 801 ms and a concurrent
`asyncio.sleep(0.01)` ticker got **zero** iterations. In 0.8.0 the same
service ran via `asyncio.create_task` and the loop stayed live.

This is a silent, breaking change to the async engine's core value
proposition. Any user who wrote `def fetch_quote(i, c, e): return db.query(...)`
— idiomatic, and what every "sync services just work" doc example looks like —
goes from "runs off the critical path" to "stalls every other actor, every
timer and every inbound send on the loop". There is no warning, no opt-out,
and nothing in the changelog's #116 entry ("the async engine now runs a
non-coroutine service inline") that a reader would recognise as "and your
event loop is now hostage to it".

The ordering bug #116 fixed was real. The fix traded a correctness bug for a
liveness bug. The right shape is `run_in_executor` with the completion
delivered through the priority lane — preserving the ordering guarantee
without occupying the loop — or, at minimum, a documented opt-in and a loud
warning when an inline service exceeds a threshold.

---

## J-4 — HIGH — the #105 self-send gate is bypassed by `send_threadsafe` from an action-spawned thread; `maxIterations` becomes unenforceable

**Probe:** `p2::j4*`. Machine: `maxIterations: 20`, action re-sends its own
trigger, capped at 60 for the probe.

| Route | Count | Budgeted? |
|---|---|---|
| `create_task(i.send("T"))` from an async action | 21 | ✅ |
| `call_soon(...)` → `ensure_future(i.send("T"))` | 1 | ✅ (see below) |
| **`Thread(target=lambda: i.send_threadsafe("T"))`** | **60** | ❌ **unbounded** |
| nested: P's action drives Q, Q's action self-sends | 21 | ✅ |

`_issued_from_own_action()` reads a `contextvars.ContextVar`. Threads get a
fresh, empty context, so `_ACTIVE_ACTION_OWNER.get()` is `None` and every
`send_threadsafe` is classified as external traffic. The probe's chain ran to
its own 60-iteration ceiling with the budget never engaging — a genuinely
self-feeding machine that `maxIterations` cannot break.

This is the *documented* escape hatch for actions that need to hand off work
to a worker thread, so it is not an exotic path. The `create_task` result (21)
shows the contextvar *does* propagate to child tasks — `contextvars` copies
the context at `create_task` time — so the gate is coherent for asyncio and
blind to threads. A thread identity fallback (record the owning thread
alongside the contextvar, and treat a `send_threadsafe` from a thread spawned
under an active action as self-generated) would close it; so would simply
counting `send_threadsafe` against the chain when the loop is `_processing`.

**Sub-finding (LOW, J-4b):** the `call_soon` route produced a count of **1** —
the re-send was scheduled but the chain died immediately. The event is
enqueued after the action returns and outside any action context, so it lands
as external traffic, is processed, and the next action's `call_soon` repeats —
yet the count never grew past 1 within the 1 s window. This suggests the
`ensure_future(send(...))` from a bare `call_soon` callback is being dropped
or deferred indefinitely rather than budgeted. Not reproduced to root cause
inside the time bound; flagged for a follow-up probe. It is the *opposite*
failure direction from J-4 (loss, not runaway) and deserves its own look.

---

## J-5 — HIGH — the per-macrostep settle budget is per **drain**, so one event's legitimate settle starves the next event in the same batch

**Probe:** `p2::j6_long_legit_settle`, `p2::j6b_two_sends_same_drain`.

`sync_interpreter.py` moved `iterations` from a local to
`self._settle_iterations`, reset in `_process_event_queue()` — i.e. **once per
drain**, not per macrostep, despite the changelog's "The budget is now per
macrostep."

Single events settle fine: a 40-hop `always` chain under `maxIterations: 50`
completes at `s40` on start and `t40` on `GO`, `last_transition_ok: true`,
no error. Correct.

But two *independent* events in one `send_events` batch, each needing 40 of a
50 budget:

```json
"j6b_value": "u9",
"j6b_ok":    false,
"j6b_err":   "RunawayChainError"
```

The second event inherits the first's spend and is cut after 9 of its 40 hops,
leaving the machine parked on `u9` — a state it should never rest in. The
failure is observable (`last_transition_ok=False`, `last_error` set,
`_repair_configuration()` ran, so the configuration is legal), which is the
#112 improvement working. But the machine is in the wrong state, the
diagnostic blames a "runaway chain" that does not exist, and the fix is
"raise `maxIterations`" — which is exactly the knob a user tunes per-macrostep
and will now have to over-provision by the batch size.

For an OMS batching a day's replay events through `send_events`, the budget
effectively becomes `maxIterations / len(batch)`. That is a silent,
load-dependent correctness cliff.

The counter needs resetting at each macrostep boundary inside the drain loop,
not at the drain's start. The #103 hang it was moved to fix was about the
settle pass *re-entering* `_process_transient_transitions` — that needs a
re-entrancy guard, not a drain-scoped counter.

---

## J-6 — MEDIUM — `from_snapshot(clock=SimulatedClock())` never attaches the settle hook: restored timers fire only on an explicit `tick()`

**Probes:** `p3::j7c_simclock_detail`, `p4_clock_attach.py` (root cause).

`SyncInterpreter.start()` attaches the clock's settle hook at line 308:

```python
if isinstance(self.clock, SimulatedClock):
    self.clock._attach(self.tick)
```

But that line sits **after** three early returns. A restored interpreter has
`status == "running"`, so `start()` takes the `_restart_timers_on_start`
branch at line 268 and returns at line 283 — never reaching the attach.

`p4` isolates it:

```json
"ctor_settlers": 1,                          ← constructor path: attached
"restored_settlers_before_start": 0,
"restored_settlers_after_start":  0,         ← from_snapshot path: never attached
"restored_clock_pending": 1,                 ← the timer IS armed
"ctor_value_after_increment_only":      "b", ← increment() settles
"restored_value_after_increment_only":  "a", ← increment() does NOT settle
"restored_value_after_explicit_tick":   "b"  ← manual tick() recovers it
```

So `restart_timers=True` does re-arm the deadline correctly (`has_dormant_timers`
goes `True` → `False`, `clock.pending == 1`), and the `clock=` injection works
(`restored_clock_is_c2: true`). The `#49` contract — "`clock.increment(ms)`
leaves the machine settled" — is what breaks, and only on the restore path.
The real-clock equivalent is unaffected (`j7c_realclock_restored_value: "b"`),
because a real clock fires on its own thread.

The damage is confined to deterministic replay under `SimulatedClock` — which
is precisely the use case `from_snapshot(clock=)` (#117) was added to enable.
Two round-4 features that were designed to compose do not. A test asserting
"restore, advance the clock, assert the timer fired" passes only if it happens
to call `tick()`, and the #128/#117 regression tests do exactly that, so the
suite is green.

One-line fix: hoist the `_attach` above the early returns (or attach in
`from_snapshot` when a `SimulatedClock` is injected).

**Sub-note:** `j7b_dormant_after_start: true` — after a plain restore *without*
`restart_timers`, `has_dormant_timers` correctly stays `True` and the timer
correctly never fires. That half of #128 is sound and the health-check signal
works as documented.

---

## J-7 — MEDIUM — `LoggingInspector` redaction denylist misses most financial and session PII

**Probe:** `p2::j8_redaction`, `p3::j8b_doneevent_leak`.

The mechanism is sound. `redact()` is pure, recurses into nested dicts and
lists, and matches case-insensitive substrings, so `apiKey` / `API_KEY` /
`x-api-key` all redact, and `{"order": {"api_key": "x"}}` →
`{"order": {"api_key": "***"}}` (`j8_nested`). `redact_keys=()` is an explicit,
documented opt-out. Good design.

The **list** is the problem. Of 16 realistic sensitive keys probed, 13 pass
through in clear:

```
account_number, bearer, cookie, dob, email, iban, mnemonic,
pan, pin, pwd, seed_phrase, sessionId, signature
```

`DEFAULT_REDACT_KEYS` covers `password` but not `pwd`; `card` but not `pan`,
`iban` or `account_number`; `token` but not `bearer`, `cookie` or `sessionId`;
`ssn` but not `dob` or `email`. For the briefed domain (financial OMS) the
misses — `iban`, `account_number`, `pan`, `signature` — are the ones that
matter most.

This is a *defaults* finding, not a broken-mechanism finding. But #126's stated
rationale is "a debugging plugin attached 'just for a minute' is exactly how
credentials end up in a log aggregator" — and with these defaults it still is.
Anyone adopting must pass an explicit `redact_keys=` superset; that obligation
is nowhere in the docs.

**Coverage gap (secondary).** `_safe()` is applied at exactly two sites:
`on_event_received` for `isinstance(event, Event)` payloads, and `_log_ctx`.
The `ErrorEvent` branch logs `event.error` raw, and the `else` branch logs
`getattr(event, "data", None)` raw — so a `DoneEvent` carrying a service result
is unredacted by construction. In practice this did **not** leak in the probe
(`j8b_done_data_leaked: false`, `j8_secret_in_logs: false`): the `DoneEvent`
path's `on_event_received` did not emit for the invoke completion in the sync
drain. So the gap is latent rather than active, and I could not construct a
live leak inside the time bound. Worth closing anyway — the asymmetry is
accidental, not designed, and an exception's `repr` routinely carries the
payload that caused it.

---

## J-8 — LOW (positive) — `on_plugin_error` is well-behaved

**Probe:** `p2::j9_plugin_error`. Verified, no defect.

- A raising `on_transition` is contained; the machine stays `running`.
- `on_plugin_error` fires on peers with the correct `(plugin, hook, error)`
  triple, twice for two transitions — no recursion into the failing plugin.
- A watcher whose **own** `on_plugin_error` raises is contained too, and the
  `hook == "on_plugin_error"` early-return prevents the infinite regress:
  `last_plugin_error` ends as `('BadWatcher', 'on_plugin_error', RuntimeError(...))`.
- An `async def` hook is caught, its coroutine `close()`d, and reported with a
  genuinely actionable `TypeError` message. This is the standout fix in the
  round: a failure mode that previously produced only a `RuntimeWarning` on
  stderr now has a typed, programmatic surface.

One design note worth recording: `last_plugin_error` is **last-write-wins**
across all plugins and hooks. A metrics exporter polling it will miss failures
under any concurrency. `on_plugin_error` is the correct surface; the attribute
is a debugging convenience and the docstring should say so.

---

## J-9 — LOW (positive) — `InvalidEventError` hierarchy is correct and complete

**Probe:** `p3::j11_invalid_event`. Verified, no defect.

All seven malformed inputs — `None`, `5`, `{"payload": 1}`, a bare `object()`,
`[1, 2]`, `b"GO"`, `{"type": 7}` — raise `InvalidEventError` on the sync
engine, and `None`/`5`/`object()` do the same on the async engine. Every one
satisfies both `isinstance(exc, XStateMachineError)` and
`isinstance(exc, TypeError)`, so the dual-inheritance back-compat promise in
the docstring holds: existing `except TypeError` keeps working,
`except XStateMachineError` now catches it too. `issubclass(InvalidEventError,
TypeError)` is `True`. Nothing escapes the hierarchy.

---

## J-10 — LOW — `from_snapshot` raises untyped errors for non-`str` and malformed-JSON payloads

**Probe:** `p1::j1c_*`.

`check_shape()` (#110) is a genuine improvement and is correctly ordered —
after `check_version`/`check_identity`, before any field read — and its rules
(status in the known five, `context` a mapping, `configuration`/`state_ids`
lists of strings, `pending_events`/`deferred` lists of dicts with a `type`)
are sensible. The tightened `test_v080_edge_paths` assertion is right: a
non-dict `context` should be refused, not restored into a machine every
`assign` would crash on.

But it only runs *after* `json.loads`. Two pre-parse paths still escape:

```json
"j1c_none_payload": "TypeError",         ← bare TypeError from json.loads
"j1c_bad_json":     "InvalidConfigError" ← wrong type; not a config problem
```

`SnapshotCorruptError` exists precisely for "the blob is for the right machine
but its shape is wrong". A `None` payload and `"{not json"` are the most
likely shapes of real-world corruption (truncated write, `None` from a cache
miss) and neither produces it. A caller writing
`except SnapshotCorruptError:` — the documented contract — will not catch its
two most common causes. Both should be normalised to `SnapshotCorruptError`
before parsing.

---

## Test-suite audit

Checked explicitly per the brief; nothing adverse found.

- **No `xfail`, no `skip`, no `skipIf`** added anywhere in the diff.
- `tests/test_round4_findings.py` (+1 409 lines) is one class per issue,
  each encoding the reporter's acceptance criterion. Genuine coverage, not
  padding.
- The three edits to pre-existing tests are all **tightenings**:
  - `test_v080_edge_paths::TestSnapshotNonDictContext` — was "a non-dict
    context is assigned wholesale", now asserts `SnapshotCorruptError`.
    Correct.
  - `test_wave2_edge_paths::TestTeardownWithoutLoop` — was
    `assertEqual(i.status, "done")` on a machine whose loop had died, now
    asserts `"error"` + a `RuntimeError` cause. Correct, and the original
    finding (no crash on the deferred-teardown path) is still asserted.
  - `test_wave2_review_findings` — was "a mid-transition snapshot must not
    raise", now asserts it *is* refused (`0 < refused < 30`). Correct in
    direction. **Note:** this is the test that would have caught J-1, had it
    used a parallel machine; its config is flat.
  - `test_interpreter_send_receipt` — filters `dropped` to `"queue_full"`
    because `stop()` now also reports `"stopped"`. A legitimate accommodation
    of #129; the original assertion's substance is preserved.
- `test_factory` — `assertIs(machine.logic, obj)` → `assertIsNot(...)` +
  `assertIsInstance(...)`. This *strengthens* the #92/#121 no-caller-mutation
  contract.

---

## Verdict

**The adoption gate does not move.** Two blockers stand:

- **J-1** — the headline #102 fix is incomplete. Every parallel machine, and
  every exit-action snapshot on any machine, can still persist a
  configuration that restores permanently inert while reporting `running`.
  The new exception makes the hole *less visible*, not smaller: a caller who
  writes `except SnapshotMidStepError` now reasonably believes they are
  protected.
- **J-2** — there is still no supported way to snapshot a running machine
  from outside its own task. The documented workaround (`on_transition`) is
  unsound for any machine with transient states.

Two further findings are adoption-relevant in their own right: **J-3** turns
every plain-`def` service into an event-loop stall on the async engine, and
**J-5** makes `maxIterations` scale inversely with batch size.

**Credit where due.** The round is not a wash. `on_plugin_error` / the
`async def` hook diagnostic (J-8), the `InvalidEventError` hierarchy (J-9),
`check_shape`'s core rules, `_repair_configuration` (#112), the `_EngineMark`
pickle/deepcopy fix (#138), the `#136` recursion guard and the `#132`
ambiguous-`stateIn` rejection are all correct, well-reasoned, and properly
tested. The engineering quality is visibly high; the problem is that the two
hardest issues in the round got fixes that address their reproducers rather
than their invariants.

**Recommended re-review trigger:** a parallel-machine and exit-window case in
`TestMidStepSnapshotRefused`, a public quiescence predicate, an executor for
inline services, and a per-macrostep reset of `_settle_iterations`.

### Follow-ups not closed inside the time bound

- **J-4b** (`call_soon` → `ensure_future(send)` produced a chain count of 1,
  not 21): loss-direction anomaly, root cause unidentified. Needs its own
  probe.
- **J-7 secondary** (`DoneEvent.data` / `ErrorEvent.error` unredacted by
  construction): confirmed by reading `plugins.py`, but no live leak
  reproduced — the emitting path did not fire in the sync drain. Latent.
- Parameterisations were kept small deliberately (chains of 40 hops, 60-event
  ceilings, 1 s observation windows) to stay inside the 25-minute budget.
  Every finding above was reproduced at least once; none is inferred from
  reading alone except where explicitly labelled.
