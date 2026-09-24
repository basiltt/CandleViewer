# 25 — Diff review `5327ba6..3c527b0` (PR #83 / commit `2459c82`)

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit `3c527b0`. CHANGELOG `[Unreleased] — targeting 0.8.1`; **`__version__`
still reports `0.8.0`**, so this build is identified **by commit**.

**Date:** 2026-09-18. **Python:** CPython 3.13.7. **OS:** Windows 11 Pro 10.0.26200.
**Interpreter:** `_ref/xstate-statemachine/.venv-main/Scripts/python`, env
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

**Diff reviewed:** 18 files, +1023/−357. One functional commit, `2459c82`:
**`ErrorEvent` (#80)**, **provenance-based system events (#79)**, **one task
per invoked child (#43)**. Source: `events.py` (+92), `base_interpreter.py`,
`interpreter.py`, `models.py`, `sync_interpreter.py`, `plugins.py`,
`validation.py` (−50), `__init__.py`; tests: `test_actor_perf.py` (+460,
new), `test_events.py` (−34 net). Full `src/` and `tests/` diffs read.

**Probes:** `docs/research/xstate/probes/main-3c527b0/` (`g1`–`g20`).
**Baseline comparisons** were run against a throwaway `git worktree` at
`5327ba6`, since removed; the clone is back to a clean `3c527b0`.

No library source was modified. No `git` command was run in the CandleViewer
repository. GitHub was not written to.

---

## 0. Bottom line

The three headline changes are **real and they work**. #43 in particular is
a genuinely good piece of engineering: the `children + 1` task budget is
independently confirmed (G-20), 1 000 spawn/complete cycles leak nothing
(G-5), teardown is correct on parent `stop()` and on rollback of the
entering transition (G-10), and the exit-vs-completion race is handled —
scanned across the window in 1 ms steps, no stale `onDone`/`onError` ever
lands in a state the parent already left (G-6, G-19). The full suite is
**3242 passed, 13 skipped** in 496 s.

**But the provenance mechanism (#79) has a soft centre, and `ErrorEvent`
(#80) landed on a persistence path that was never taught about it.** Three
High findings:

- **G-1 — `Event.system` is a public, user-settable constructor argument.**
  `send(Event("ANYTHING", system=True))` bypasses strict mode, `onUnhandled`
  and the `"*"` matcher, on **both** engines and through
  `send_threadsafe`. The name-based rule #79 removed was at least *hard to
  hit by accident*; this replaces it with an explicit, documented-by-dataclass
  opt-out that any caller can set. The fix for #79 restored the exemption
  hole it was closing, through a different door.
- **G-2 — provenance does not survive a snapshot.** `from_snapshot`
  re-materialises every persisted event as a plain `Event` with
  `system=False`. An `escalate` event that was exempt before the snapshot
  comes back as user traffic: it now trips `onUnhandled: "error"` and is
  swallowed by `"*"`. This is a **regression against `5327ba6`**, where the
  name rule gave the same answer before and after a restore.
- **G-3 — a pending `ErrorEvent` is silently dropped by
  `get_persisted_snapshot()`.** The inbox is filtered with
  `isinstance(e, Event)`; `ErrorEvent`/`DoneEvent` are `NamedTuple`s. #47
  added `pending_events` to the snapshot specifically so a crash between
  accept and process could not lose an event — #80 routed *every* service
  and child failure through a class that falls through that filter.

Ranked for our adoption: **G-2 and G-3 are the ones that matter to us**,
because our order path snapshots and restores. G-1 matters to the library's
security story more than to ours.

---

## 1. Findings

| ID | Sev | Area | One-line |
|---|---|---|---|
| **G-1** | **High** | #79 | `Event(system=True)` is user-settable; bypasses strict / `onUnhandled` / `"*"` on both engines and via `send_threadsafe`. |
| **G-2** | **High** | #79 + #47 | Provenance is not persisted; restored engine events become user traffic. Regression vs `5327ba6`. |
| **G-3** | **High** | #80 + #47 | Pending `ErrorEvent`/`DoneEvent` silently dropped by the snapshot; the failure vanishes with no record. |
| **G-4** | Medium | #80 | `ErrorEvent.data`'s `DeprecationWarning` fires from the library's *own* code (`plugins.py:435`, `base_interpreter.py:1781`) — unfixable by the user. |
| **G-5** | Medium | #80 | `_resolve_event_spec` turns an `ErrorEvent` into `Event(payload=<exception>)` — `payload` is not a dict, so `event.payload.get(...)` raises. |
| **G-6** | Medium | #80 | `escalate` is the one failure path **not** converted; still a plain `Event` with the error under `payload["error"]`. |
| **G-7** | Medium | #79 | Strict mode still exempts by **name** via `ENGINE_EVENT_SHAPES`: `done.invoke.NEVER_INVOKED`, `after.party`, `xstate.whatever`, `___xstate_forged` all pass undeclared. |
| **G-8** | Medium | parity (pre-existing) | Sync engine never converts an invoked **child-machine** failure to `onError`; async does. Not introduced here, but in scope for #80. |
| **G-9** | Low | #43 | Completion-delivery task is created via `_loop_create_task` and registered with neither the `TaskManager` nor a strong reference. |
| **G-10** | Low | #79 | Dead constant `_SYSTEM_EVENT_PREFIXES` (`base_interpreter.py:275`) with a comment that now describes behaviour that no longer exists. |
| **G-11** | Low | tests | The forged-`system` bypass (G-1) and the restore-provenance gap (G-2) have no test. Three tests were deleted for a withdrawn feature without replacement coverage of the new attack surface. |
| **G-12** | Low | docs | The provenance API (`is_system_event`, `system_event`, `Event.system`) is undocumented and unexported, while `ENGINE_EVENT_SHAPES` is announced in the CHANGELOG but not re-exported from the package root. |

---

### G-1 — `Event.system` is user-settable and is a complete guardrail bypass  ·  **High**

**Evidence.** `events.py:117`

```python
system: bool = field(default=False, compare=False, repr=False)
```

It is an ordinary dataclass field on the **public** `Event` class, so
`Event("X", system=True)` is valid, supported, type-checked user code. The
three consumers all trust it unconditionally:

- `base_interpreter.py:1539` — `if not isinstance(event, Event) or event.system: return` (skips **strict** *and* `event_schemas`)
- `base_interpreter.py:3258` — `if is_system_event(event) or not isinstance(event, Event):` (skips `onUnhandled`)
- `base_interpreter.py:3648` — `system=is_system_event(event)` → `_matching_descriptors` returns exact matches only (skips `"*"` and `"prefix.*"`)

**Repro.** `probes/main-3c527b0/g1_forge_system.py`, `g9_sync_parity.py`,
`g18_threadsafe_and_detach.py`

```
is_system_event(Event('X'))              = False
is_system_event(Event('X', system=True)) = True

A) plain  Event('ANYTHING')  -> state {'s.b'}     # "*" fires
B) forged Event(system=True) -> state {'s.a'}     # "*" bypassed

C) strict plain : UnknownEventError
C) strict forged: ACCEPTED

D) onUnhandled=error plain : status=error, err=UnhandledEventError(...)
D) onUnhandled=error forged: status=running, err=None
```

Identical on the sync engine (`g9`: B/C/D) and through `send_threadsafe`
(`g18`: `a) send_threadsafe strict forged: ACCEPTED`) — so the #78 fix that
brought `send_threadsafe` under the strict guard is bypassable the same way.

**Why this matters.** #79's own framing is *"a user event is user traffic
whatever it is called."* That is now true of the **name** and false of the
**object**. The 0.8.0 hole needed a user to name an event `done.review`;
this one needs a `system=True` kwarg — narrower in practice, but it is a
silent, total bypass of three independent guardrails rather than one
matcher quirk, and `strict` mode is a *safety* feature whose whole value is
that it cannot be accidentally opted out of. Note also that `system` is
`compare=False, repr=False`: a forged event is **invisible in a `repr()`**
and compares equal to its honest twin, so this does not show up in logs or
in a test assertion on event equality.

**Suggested shape of a fix.** Keep the flag private to the engine: name it
`_system`, or (better) carry provenance out-of-band — the engine already
controls every mint site through `system_event()`, so an `Event` subclass
(`_SystemEvent`) added to `ENGINE_EVENT_TYPES` gets the same result with no
public surface and no way to forge it from application code.

---

### G-2 — provenance does not survive a snapshot  ·  **High**  ·  *regression vs `5327ba6`*

**Evidence.** `base_interpreter.py:999-1010` persists only `type` and
`payload`; `:1229` and `:1235` rebuild every deferred and pending event as

```python
Event(type=record["type"], payload=record.get("payload") or {})
```

— i.e. `system=False`, unconditionally. `Event.system` is `compare=False,
repr=False` and is not in the serialised shape, so the flag is created by
the engine and then thrown away at the first persistence boundary.

**Repro.** `probes/main-3c527b0/g3_restore_regression.py`

```
onUnhandled=error, escalate event
  live (system=True) : ('running', 'None', {'u.a'})            # exempt, correct
  after restore      : ('error',   'UnhandledEventError(...)', {'u.a'})   # FAILS THE MACHINE
'*' matcher, escalate event
  live (system=True) : ('running', 'None', {'s.a'})            # exempt, correct
  after restore      : ('running', 'None', {'s.b'})            # swallowed by "*"
```

Confirmed by `g2_snapshot_provenance.py`:
`restored: [('Event', 'xstate.error.actor.child', False), ('Event', 'USER_EVT', False)]`
— the escalate event and the user event are indistinguishable after a
round-trip.

**Why this is a regression.** On `5327ba6` the exemption was a pure function
of `event.type`, so it gave the **same answer before and after** a restore.
`3c527b0` makes it a function of in-memory state that the snapshot does not
carry. A machine that restores with an escalate event in its inbox and
`onUnhandled: "error"` now goes to `status="error"` where it previously did
not. This is the interaction of two features shipping in the same release
(#79 provenance, #47 pending-event persistence) and the CHANGELOG does not
mention it.

**Direct relevance to us.** Our order path is snapshot/restore-based. This
is the finding in the diff most likely to bite us.

---

### G-3 — a pending `ErrorEvent` is silently dropped by the snapshot  ·  **High**

**Evidence.** `base_interpreter.py:1007-1010`

```python
"pending_events": [
    {"type": e.type, "payload": copy.deepcopy(e.payload)}
    for e in self.pending_events
    if isinstance(e, Event)          # <-- ErrorEvent/DoneEvent are NamedTuples
],
```

`ErrorEvent` and `DoneEvent` are `NamedTuple`s (`events.py:133`, `:176`),
not `Event`s, so they fail the filter and are dropped with **no warning and
no record**. The restore side (`:1233-1236`) could not round-trip them
anyway: it rebuilds everything as a plain `Event`, which has no `error`
field and the wrong class for `isinstance(event, ErrorEvent)`.

**Repro.** `probes/main-3c527b0/g17_snapshot_drops_errorevent.py` — two
demonstrations, one natural and one deterministic:

```
A) real inbox held      : ['ErrorEvent:error.platform.svc']
A) snapshot persisted   : []
A) failure survived     : False   <-- the failure is GONE from the snapshot

B) parked in inbox      : ['ErrorEvent:error.platform.svc', 'DoneEvent:done.invoke.svc', 'Event:USER_EVT']
B) snapshot persisted   : ['USER_EVT']   <-- both engine events dropped
```

(A) is a real failing `invoke` on a real interpreter; the probe snapshots
inside the window between the engine enqueuing the `ErrorEvent` and the run
loop draining it. The window is short on a toy machine but is exactly as
long as the current macrostep on a real one.

**Why this matters.** #47's stated purpose is *"a crash between accept and
process lost them with no trace; with it a restored machine resumes with
its mailbox intact."* That guarantee now has a hole precisely at the events
you least want to lose. Pre-`3c527b0` a failure was a `DoneEvent` and was
dropped the same way — but #80 makes **every** service and child-actor
failure take this shape, so the blast radius went from "invoke completions"
to "all invoke completions *and* all failures." A machine restores believing
the invoke never failed, sits in the invoking state, and no `onError` ever
fires.

**Note:** the filter is silent. Even a `logger.warning` on a dropped
non-`Event` would have surfaced this.

---

### G-4 — the library trips its own deprecation warning  ·  Medium

`ErrorEvent.data` warns (`events.py`, `stacklevel=2`), but two engine-internal
call sites read `.data` on an event that may be an `ErrorEvent`:

- `plugins.py:435` — `data_to_log = getattr(event, "data", None)` in the
  shipped `LoggingInspector`
- `base_interpreter.py:1781` — `payload=getattr(resolved, "data", {}) or {}`
  in `_resolve_event_spec`

**Repro.** `g4_plugin_deprecation.py`, with only `LoggingInspector()`
attached and no user code touching `.data`:

```
DeprecationWarnings raised: 1
   plugins.py:435 | ErrorEvent.data is deprecated and will be removed in 0.9; read ErrorEvent.error instead.
```

Baseline comparison (`/tmp/base_cmp2.py` vs the `5327ba6` worktree) confirms
this is new: `DEPRECATIONS: []` on `5327ba6`, `['base_interpreter.py:1781']`
on `3c527b0`.

A user who runs `-W error::DeprecationWarning` in CI — the recommended way
to be ready for 0.9 — now fails on library code they cannot change. Both
sites should read `getattr(event, "error", None) or getattr(event, "data", None)`,
or branch on `isinstance(event, ErrorEvent)`.

---

### G-5 — `_resolve_event_spec` builds an `Event` whose `payload` is an exception  ·  Medium

`base_interpreter.py:1779-1782` normalises a non-`Event` by reading `.data`:

```python
return Event(type=resolved.type, payload=getattr(resolved, "data", {}) or {})
```

For a `DoneEvent` that is a dict and correct. For an `ErrorEvent`, `.data`
is the deprecated property returning the **exception**, so the resulting
`Event.payload` is a `ValueError`, not a mapping.

**Repro.** `g13_resolve_event_spec_errorevent.py` (unit) and
`g13b_reachable.py` (end-to-end, `sendParent` forwarding the triggering
`ErrorEvent` upward — a standard supervision idiom):

```
DoneEvent  -> Event(type='done.invoke.svc', payload={'k': 1})       payload type: dict
ErrorEvent -> Event(type='error.platform.svc', payload=ValueError('boom'))
  isinstance(payload, dict): False
  event.payload.get(...) would now raise: AttributeError: 'ValueError' object has no attribute 'get'

# end-to-end:
forwarded event seen by parent: {'type': 'error.platform.svc', 'payload': "ValueError('boom')", 'is_dict': False}
```

Baseline shows the same malformed payload on `5327ba6` (it read
`DoneEvent.data`, which held the exception), so the **shape** bug is
pre-existing — but `Event.payload` is typed `Dict[str, Any]`, every other
path maintains that invariant, and #80 was the natural moment to fix it.
What *is* new is that this path now also emits G-4's `DeprecationWarning`
from inside the engine.

---

### G-6 — `escalate` is the one failure path not converted to `ErrorEvent`  ·  Medium

The diff converted every `DoneEvent`-carrying-an-exception site — verified
exhaustively by grep: the five surviving `DoneEvent(` constructions
(`base_interpreter.py:3150`, `interpreter.py:1784`, `:2039`,
`sync_interpreter.py:1062`, `:1257`) are all success paths. Good.

`escalate` is not among them. `base_interpreter.py:2665-2668`:

```python
escalate_event = system_event(f"xstate.error.actor.{self.id}", error=error_payload)
```

**Repro.** `g15_escalate_shape.py`

```
escalated event as seen by the handler: {'cls': 'Event', 'type': 'xstate.error.actor.p:kid',
                                         'has_error_attr': False, 'payload': "{'error': 'child exploded'}"}
isinstance(ErrorEvent)? False
```

So the contract the CHANGELOG and `docs/api/index.md` advertise — *"branch
on `isinstance(event, ErrorEvent)` or read `event.error`"* — does not hold
for escalated failures, which are the actor-supervision failure path and
the one closest to XState v5's `xstate.error.actor.*` naming that the docs
explicitly invoke. A handler written to the documented pattern gets
`AttributeError: 'Event' object has no attribute 'error'`.

Either convert it, or scope the docs to "invoke failures".

**Aside (not a finding, but noted while probing):** the escalate event is
only reachable by an exact `on` key — `xstate.error.actor.p:kid`, including
the parent-namespaced actor id. `"xstate.error.actor.*"` and `"xstate.*"`
both fail to match it (correctly, per the new provenance rule), which makes
escalate handlers depend on an internal id-minting convention.

---

### G-7 — strict mode still exempts by name  ·  Medium

`models.py:1552-1560` (`is_known_event`) is still a **name** test, now
against the narrower `ENGINE_EVENT_SHAPES`:

```python
if event_type.startswith(ENGINE_EVENT_SHAPES):
    return True
```

The in-code comment acknowledges the tension (*"the one place a name is all
we have"*), and narrowing `done.` → `done.invoke.` genuinely closes the
reported `done.typo` case. But the residual is still a name-shaped hole.

**Repro.** `g14_strict_shape_residual.py`

```
  done.typo                        UnknownEventError     # fixed
  done.review                      UnknownEventError     # fixed
  error.validation                 UnknownEventError     # fixed
  done.invoke.NEVER_INVOKED        ACCEPTED   <-- undeclared, strict did not fire
  done.state.NO_SUCH_STATE         ACCEPTED
  error.platform.NOT_A_SERVICE     ACCEPTED
  after.party                      ACCEPTED
  after.9999999                    ACCEPTED
  xstate.whatever                  ACCEPTED
  xstate.done.actor.ghost          ACCEPTED
  ___xstate_forged                 ACCEPTED
```

`after.party` is the nicest of these: it is not even a well-formed `after.`
shape (no numeric delay), and strict mode waves it through. Since `send()`
already has the event **object** at `_check_strict`, the provenance flag is
available there — the name test is only needed for build-time `on`-key
validation, not for the runtime `send()` check.

---

### G-8 — sync engine does not deliver `onError` for a failed invoked child machine  ·  Medium  ·  *pre-existing*

**Repro.** `g16_sync_child_failure.py` — a `SyncInterpreter` invoking a child
**machine** whose own inner service raises:

```
parent state: {'p.w'}
parent status: running error: None
onError event seen: []
```

The parent never leaves the invoking state and never learns the child
failed. The async engine handles this correctly
(`interpreter.py:2028`, `_deliver_invoked_completion` with `status == "error"`),
and `g8_unhandled_child_failure.py` case C confirms `p.bad` on async.

Baseline check confirms this is **not** introduced by the diff — the sync
`_invoke_service` changes in `2459c82` are pure `DoneEvent`→`ErrorEvent`
renames. But #80's stated scope is *"service and child-actor failures"*, the
new `test_actor_perf.py::TestErrorEvent::test_child_machine_failure_delivers_error_event`
covers only the async engine, and the release notes claim engine parity
elsewhere. Worth listing so it is a known gap rather than an assumed one.

Related, also pre-existing and confirmed identical on both commits
(`/tmp/base_cmp.py`): an invoked **child machine** that fails with **no**
`onError` handler leaves the parent `status='running', error=None`, whereas
a failing **callable** service correctly calls `_fail()` →
`status='error'`. The `_has_error_handler` / `_fail` escalation that
`interpreter.py:1824` applies to callable services has no counterpart in
`_deliver_invoked_completion`. See `g8_unhandled_child_failure.py` cases
A vs B.

---

### G-9 — the completion-delivery task is untracked  ·  Low

`interpreter.py:1958-1963` schedules delivery via `_loop_create_task`
(`:2069`), which does `loop.create_task(coro)` and returns — the result is
assigned to nothing. Unlike every other task in the file it is **not**
`task_manager.add(owner_id, task)`'d, so it is not owned by the invoking
state, not cancelled on exit, and not awaited by `stop()`. CPython's
`asyncio` holds only a *weak* reference to a running task; the stdlib docs
explicitly say to keep a strong reference.

**Probed, and I could not make it bite.** `g12_delivery_task_gc.py` runs 300
invoke/complete cycles calling `gc.collect()` on every loop iteration while
the delivery task is in flight: `lost completions: 0 /300`.
`g11_delivery_task_untracked.py` shows a `stop()` racing a completion leaves
`tasks left = 0` and simply drops the `onDone` (defensible — the machine is
stopping).

So: latent, not currently reproducible. Worth a one-line fix (hold the
reference, or register it with the `TaskManager`) rather than a behaviour
change.

---

### G-10 — dead constant with a now-false comment  ·  Low

`base_interpreter.py:275`:

```python
_SYSTEM_EVENT_PREFIXES: Tuple[str, ...] = SYSTEM_EVENT_PREFIXES
```

Both former readers (`_handle_unhandled_event`, `_matching_descriptors`)
were converted to provenance in this diff; grep confirms **zero** remaining
uses. The comment above it (`:270-274`) still says it is *"Shared by the
wildcard matcher, the unhandled-event policy and strict mode so the three
can never disagree about what counts as a system event"* — a description of
the architecture this commit deleted. This is the single most misleading
line left in the file for the next reader.

The `#79` changes to `models.py` and `validation.py` are otherwise
consistent; `SYSTEM_EVENT_PREFIXES` is correctly retained in `events.py` for
back-compat and is still re-exported.

---

### G-11 — deleted tests were not replaced with coverage of the new surface  ·  Low

`tests/test_events.py` removes `TestBuildTimeWarning` (3 tests) — correct,
the feature was withdrawn — and flips
`test_wildcard_does_not_match_reserved_namespace_user_event` into
`test_user_event_in_reserved_namespace_matches_wildcard`, plus two new
acceptance tests. That is a fair and honest swap for the *intended*
behaviour change, and I found no weakened or silently deleted assertions
elsewhere in the diff. No TODOs or `skip`s were introduced;
`test_actor_perf.py` is 9/9 green and its three perf assertions
(`children+1`, no wake-ups, sub-2 ms `onDone`) are pinned as claimed.

What is missing is a test for the *new* attack surface the refactor created:

- nothing asserts that `Event("X", system=True)` from user code is **not**
  trusted (G-1)
- nothing asserts that provenance survives a snapshot round-trip (G-2)
- nothing asserts that a pending `ErrorEvent` is persisted (G-3)

All three are one-assertion tests. Their absence is why G-1–G-3 shipped.

---

### G-12 — the provenance API is undocumented; `ENGINE_EVENT_SHAPES` is not re-exported  ·  Low

```
ENGINE_EVENT_SHAPES in pkg: False      # reachable only as `events.ENGINE_EVENT_SHAPES`
is_system_event in pkg:     False
ErrorEvent in pkg:          True
__version__:                0.8.0
```

`ErrorEvent` is correctly added to `__init__.py` and `__all__`, and
`docs/api/index.md` documents it well. But:

- The CHANGELOG announces `events.ENGINE_EVENT_SHAPES` "for build-time
  checks and documentation" — technically accurate via the submodule, but
  it is the only newly-public name in this release not re-exported from the
  package root, and it appears nowhere in `docs/api/index.md`.
- `Event.system` appears in **no** user-facing doc (one passing mention in
  `changelog.md:56`). Given G-1, that is arguably for the best — but a
  public dataclass field with load-bearing security semantics and zero
  documentation is the worst of both worlds.
- `is_system_event` / `system_event` — the actual provenance API — are
  unexported and undocumented, so a plugin author writing an
  `on_event_received` hook has no supported way to ask "did the engine mint
  this?" and will reach for the name prefixes the release just deprecated
  in spirit.

---

## 2. What I checked and found clean

Recording the negatives, since the brief asked for specific areas:

- **Every failure path converted?** Yes, except `escalate` (G-6). All five
  surviving `DoneEvent(` constructions are success paths (verified by grep +
  read). Callable-service failure, child-actor bring-up failure (bad `input`
  resolver, `start()` raising), and child-machine `error` status all deliver
  `ErrorEvent`. Sync engine converts its two sites correctly (`g9` case A:
  `('ErrorEvent', 'error.platform.svc', ValueError('sync boom'))`).
- **#43 teardown.** Parent `stop()` with a live child → child `stopped`,
  tasks back to baseline (`g10` a). Rollback of the entering transition →
  no orphan actor, `_actors=0`, `_invoked_children={}`, tasks at baseline
  (`g10` b). Child failing during parent exit → no stale `onError`, scanned
  ±2 ms across the window with a passing control (`g19`). Child completing
  as the parent exits → no stale `onDone`, six timing points (`g6`).
- **Leaks.** 1 000 spawn/complete cycles: `tasks=2, _actors=0,
  _invoked_children=0` throughout, 1000/1000 completions delivered (`g5`).
- **Task budget.** `children + 1` confirmed at 1, 10 and 50 idle children —
  delta over baseline is exactly `n` (`g20`). The
  `production-characteristics.md` rewrite is accurate.
- **The listener-detach-by-`__name__`** in `_cancel_state_tasks`
  (`interpreter.py:1604-1608`) looked fragile — two different closures in
  the file share the name `_on_child_terminal` (spawn path `:1548`, invoke
  path `:1966`). It is **safe in practice**: spawned children are never
  registered in `_invoked_children`, so the detach loop never sees them.
  Confirmed empirically (`g18` b, `/tmp/t9.py`). Fragile by construction,
  not broken — I did not raise it as a finding, but a sentinel attribute
  would be cheaper than the invariant.
- **Full suite:** `3242 passed, 13 skipped, 11 warnings in 495.98s`. The 11
  warnings are all pre-existing (`resolver.py` sibling-fallback, CLI
  `--style`).

---

## 3. Release-readiness note

Nothing here blocks the library from shipping 0.8.1 *as an improvement over
`5327ba6`* — the diff is net-positive and #43 is excellent. But **G-2 is a
behavioural regression introduced by this commit** and G-3 is a data-loss
bug on the persistence path, both created by two features in the same
release meeting each other. If 0.8.1 ships as-is, both become documented
0.8.1 behaviour that the adopting project has to work around rather than
`main`-only findings we can still get fixed upstream. For our purposes the
ordering is: **G-2, G-3, then G-1**.

`__version__` still reports `0.8.0` on a tree whose CHANGELOG describes
0.8.1 — unchanged from the `5327ba6` review and still worth fixing before
any release.

---

## 4. Artefacts

Probes (all runnable standalone; each prints its own verdict):

| Probe | Finding |
|---|---|
| `g1_forge_system.py` | G-1 (async: `"*"`, strict, `onUnhandled`) |
| `g2_snapshot_provenance.py` | G-2 (round-trip shows flag loss) |
| `g3_restore_regression.py` | G-2 (live vs restored, both policies) |
| `g4_plugin_deprecation.py` | G-4 |
| `g5_child_leak_cycles.py` | clean — 1 000 cycles |
| `g6_exit_race.py` | clean — completion/exit race |
| `g7_ondone_happy.py` | control for `g6` |
| `g8_unhandled_child_failure.py` | G-8 (unhandled-failure asymmetry) |
| `g9_sync_parity.py` | G-1 on sync; `ErrorEvent` sync parity clean |
| `g10_stop_rollback_teardown.py` | clean — stop() + rollback teardown |
| `g11_delivery_task_untracked.py` | G-9 |
| `g12_delivery_task_gc.py` | G-9 (negative: 0/300 lost) |
| `g13_resolve_event_spec_errorevent.py` | G-5 (unit) |
| `g13b_reachable.py` | G-5 (end-to-end) |
| `g14_strict_shape_residual.py` | G-7 |
| `g15_escalate_shape.py` | G-6 |
| `g16_sync_child_failure.py` | G-8 |
| `g17_snapshot_drops_errorevent.py` | G-3 |
| `g18_threadsafe_and_detach.py` | G-1 (`send_threadsafe`); detach invariant |
| `g19_child_fails_during_exit.py` | clean — failure/exit race, with control |
| `g20_task_budget.py` | clean — `children + 1` confirmed |
