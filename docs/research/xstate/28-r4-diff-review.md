# 28 — Round-4 diff review: `3c527b0..5e07ba8`

**Scope.** Source and test diff between `3c527b0d04c0d2d0ebb565af7e9e905f7178f620`
(the build under verdict in `26-verify-3c527b0-verdict.md`) and
`5e07ba8842345a73ef8f830f0281de16370a7c74` (`main`, unreleased 0.8.1;
`__version__` still reports `0.8.0` — this build is identified **by commit**).

22 files, +1 661 / −135. Two functional commits: `4d27e7a` (PR #100,
round-3 findings #84–#99 plus reopened #31/#77/#79) and `4db48b1` (PR #101,
two ride-alongs). Every `src/` hunk and every `tests/` hunk was read.

**Date:** 2026-09-18. **Python:** CPython 3.13.7. **OS:** Windows 11 Pro 10.0.26200.
**Interpreter:** `_ref/xstate-statemachine/.venv-main/Scripts/python`,
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

**Library suite on this commit:** `3276 passed, 13 skipped, 0 failed` in 498 s.
(`3242 passed / 13 skipped` at `3c527b0` → +34 tests, all in the new
`tests/test_round3_findings.py`; 33 `test_` methods plus reworked cases in
`test_clock.py` / `test_factory.py` / `test_persistence.py`.)

**No library source was modified.** No `git` command was run in the CandleViewer
repository. GitHub was read-only.

Repros: `docs/research/xstate/probes/main-5e07ba8/r*.py`. Each is standalone,
pins `sys.path` at the library `src/`, and prints a VERDICT line. Where a
finding is a *regression*, the probe runs the same scenario against a
`git archive 3c527b0` extraction (`/tmp/lib3c/src`) in the same process run, so
the before/after is one command.

---

## 0. Bottom line

**This is the strongest of the four diffs reviewed. Every one of the three
`3c527b0` High defects is genuinely closed, the round-3 list is real work, and
the new test file pins each item against a pre-fix reproduction.** G-1
(forgeable `Event.system`), G-2 (provenance lost across a snapshot) and G-3
(pending `ErrorEvent` silently dropped) all verify fixed end-to-end
(`r2`, `r18`, `r19`, `r44`). Snapshot layout v2 is well-designed: a per-record
`kind` discriminator, a real codec pair, a clean forward-compat refusal
(`SnapshotVersionError`, `r16`), and v1 records restore unchanged.

**But the same two-features-meet-at-a-boundary failure mode that produced G-2
has produced two more instances, and one of them is a fresh data-loss
regression introduced by this diff.**

- **H-1 (High, regression).** `#90`'s self-send reroute gates on
  `self._processing` — an interpreter-wide flag, not "the caller is an action
  of this interpreter". Any coroutine that calls `send()` while the run loop is
  mid-macrostep is reclassified as self-generated: it is charged to the chain
  budget and can be **discarded**. A/B: 50/50 delivered at `3c527b0`, 49/50 at
  `5e07ba8` (`r25`). Reproduces at the **default** `maxIterations: 1000`
  (`r27`). This is silent external-event loss on the async engine — the exact
  class of defect #77 existed to remove from the sync engine.
- **H-2 (High).** `#75`'s `_detach()` calls `dataclasses.replace()`, which
  drops `_provenance` because the field is `init=False`. So
  `send(engine_event, wait=True)` demotes an engine event to user traffic and
  fails an `onUnhandled: "error"` machine, while the identical `wait=False`
  call does not (`r44`: `wait=False → running`, `wait=True → status=error,
  UnhandledEventError`). #85/#86 hardened provenance against the constructor
  and against the snapshot; the receipt path was not audited.
- **H-3 (High).** `restore_event()` re-derives provenance **by name** for v1
  records. `#98` was added in this same diff to stop `after.party` /
  `done.invoke.NEVER` passing `strict` — and a v1 snapshot record restores
  exactly those names with engine provenance (`r46`, `r47`). A restore
  launders the events `#98` rejects. The docstring calls this "the one place a
  name is all we have"; that is true, and it is still an attacker- and
  bug-reachable exemption on a path that reads persisted bytes.
- **H-4 (High).** `Receipt.deferred` is keyed on `id(event)` in a
  `Set[int]` that is only ever discarded on a **receipt** path
  (`interpreter.py:1278`, `sync_interpreter.py:512`). A fire-and-forget defer
  leaks an entry permanently: 50 000 fire-and-forget defers leave 50 000 stale
  ids / 2.1 MB on the async engine (`r35`) — and a later **handled** event
  whose object reuses a stale id reports `deferred=True` (`r6b`,
  1/20 000). #75 fixed precisely this `id()`-reuse class for receipts and the
  same mistake was repeated for `deferred`.

Plus three Medium and four Low findings below, including a genuine
**public-API break** (`Receipt` grew a 4th field; 3-tuple unpacking raises,
`r41`) that is announced nowhere as breaking.

**Counts on this diff: 4 High · 3 Medium · 4 Low.** Net against the
`26-` verdict: 3 High closed, 4 High opened. The gate's High count does not
improve.

---

## 1. Findings

### H-1 — `#90`'s reroute gate is interpreter-wide, so it discards *external* events (High, **regression introduced by this diff**)

**File:** `src/xstate_statemachine/interpreter.py:633-637`
**Repro:** `probes/main-5e07ba8/r12_external_misroute.py`,
`r13_external_loss.py`, `r14_which_lost.py`, `r25_ab_external_loss.py` (A/B),
`r27_default_limit_loss.py`

`#90` routes an action-issued `send()` to the internal queue so it counts
against the chain budget. The gate it uses is:

```python
if self._processing and not self._refuse_if_not_running(event_obj):
    self._raise_depth += 1
    self._internal_queue.append(event_obj)
```

`self._processing` is set for the whole duration of
`_process_event_and_transient_transitions` (`interpreter.py:1240/1270`). It
says *the run loop is busy*, not *the caller is an action of this
interpreter*. Any other coroutine on the same loop — an HTTP handler, a
market-data feed, a timer coroutine — that calls `send()` during a macrostep
takes this branch. Its event is charged to `_raise_depth`, and once
`_raise_depth > maxIterations` the run loop **drops** the event at the head of
the queue (`interpreter.py:1173-1196`).

This is not theoretical and does not need a pathological config. One handler
doing `await` (any I/O) plus a producer burst is enough:

```
default maxIterations=1000, external burst during one 0.5s macrostep:
  burst=  500 delivered=  500 LOST=   0
  burst= 1000 delivered= 1000 LOST=   0
  burst= 1500 delivered= 1499 LOST=   1   <- lost n=0
  burst= 3000 delivered= 2999 LOST=   1   <- lost n=0
```

A/B across the diff, `maxIterations=5`, 50 independent external `W` sends
during one 0.4 s macrostep (`r25`):

```
--- 3c527b0 (baseline) --- lib3c: delivered 50/50  LOST=0
--- 5e07ba8 (HEAD)     --- xstate-statemachine: delivered 49/50  LOST=1
```

**Failure scenario.** An order-management service runs one `Interpreter`. A
fill handler awaits a database write (0.5 s). During that window the market
feed pushes 1 500 `TICK`/`FILL` events via `send()` from its own coroutine.
One of them is discarded. Its `send(wait=True)` receipt carries
`InterpreterStoppedError("dropped: 'W' exceeded the 5-event self-raised chain
budget on 'm'")` (`r14`) — a message that names neither the real cause nor a
`RunawayChainError`, and which a fire-and-forget caller never sees at all.
`interp.last_error` reads `None` in the `r12` run because a later clean step
resets it.

**Why this is worse than the bug it replaced.** The whole point of #77 was
"never events the caller was told were accepted". The sync engine was fixed to
honour that (`external_budget`, `sync_interpreter.py:620`). The async engine
now violates it, via the fix for a *different* issue, with no equivalent
`external_budget` concept.

**Severity High.** Silent loss of accepted external events, at the default
configuration, on the recommended engine, in the money path. Note the loss is
one event per trip rather than the whole tail, which makes it *harder* to
notice, not less serious.

**Suggested shape of a fix.** The gate needs to distinguish "this coroutine is
executing inside my own action" from "my run loop happens to be busy" — e.g. a
`contextvars.ContextVar` set around `_run_user_action`, which is correct under
`await` and across concurrent tasks, where a plain instance flag is not. A
weaker but still correct fallback is to give the async engine the same
`external_budget` the sync engine has, so only genuinely internally-queued
events are droppable.

---

### H-2 — `_detach()` strips engine provenance, so `wait=True` demotes an engine event to user traffic (High)

**File:** `src/xstate_statemachine/interpreter.py:713`
(`dataclasses.replace(event_obj)`), reached from `interpreter.py:602-603`
**Repro:** `probes/main-5e07ba8/r43_detach_strips_provenance.py`,
`r44_detach_ab.py`

`Event._provenance` is declared `init=False` (`events.py:126-128`) so it cannot
be supplied to the constructor. `dataclasses.replace()` constructs a new
instance **through `__init__`**, and therefore cannot carry an `init=False`
field — the copy comes back with `_provenance=None`:

```
minted system?             True
dataclasses.replace(ev)    False   <- the _detach() path
```

`#75`'s `_detach()` runs whenever `wait=True` and the caller passed its own
event object (`interpreter.py:601-603`). End-to-end against an
`onUnhandled: "error"` machine (`r44`):

```
engine-minted event sent to an onUnhandled:'error' machine:
  wait=False -> status=running  error=None
  wait=True  -> status=error    error=UnhandledEventError
```

**Failure scenario.** Any code holding an engine-minted event and re-sending it
with a receipt — a supervisor that forwards an `escalate` to a parent and wants
to confirm it landed, a test harness replaying a captured `xstate.error.actor.*`
— silently converts it to user traffic. On an `onUnhandled: "error"` machine
that **terminates the interpreter**. The same call with `wait=False` is fine,
so the failure is triggered by asking for a receipt.

This is the same class as G-2 in the `26-` verdict — provenance is not audited
across an internal copy boundary — and it was introduced by #85 giving
`_provenance` `init=False` without checking the one place in the codebase that
reconstructs an `Event` through `__init__`. `_detach`'s NamedTuple branch
(`_replace()`) and its `copy.copy` fallback both preserve provenance correctly;
only the dataclass branch loses it. `copy.copy` preserves it, `copy.deepcopy`
does not (`r1`) — see L-3.

**Severity High.** Unhandled-event termination of a running machine, gated on a
parameter (`wait`) that should not change semantics.

---

### H-3 — `restore_event()` reintroduces the name-based provenance rule that `#98` removed (High)

**File:** `src/xstate_statemachine/events.py:314-317`
**Repro:** `probes/main-5e07ba8/r46_v1_promotion.py`,
`r47_restore_launders_strict.py`, `r3_snapshot_v2.py`

```python
if kind is None:  # v1 record
    kind = "system" if etype.startswith(ENGINE_EVENT_SHAPES) else "event"
```

`ENGINE_EVENT_SHAPES` is `('done.invoke.', 'done.state.', 'error.platform.',
'after.', 'xstate.', '___xstate')`. Every name `#98` was added in this same
commit to *reject* is promoted to engine provenance by this line (`r46`):

```
  v1 user event xstate.mine            -> system=True
  v1 user event after.party            -> system=True
  v1 user event done.invoke.NEVER      -> system=True
  v1 user event error.platform.fake    -> system=True
```

`r47` closes the loop against a live `strict` machine:

```
live send 'after.party'  -> UnknownEventError (correct, #98)
restored from v1 record  -> system provenance: True
VERDICT: the same name rejected live is engine-exempt after a restore.
```

A **v2** record is worse in one respect: `kind` is taken from the record with
no validation at all, so a snapshot that says `{"kind":"system","type":"PAYOUT"}`
restores as an engine-provenance `PAYOUT` that bypasses `strict`,
`onUnhandled` and `"*"` (`r3`, final block). Snapshots are persisted bytes — a
database row, a Redis value, an S3 object. Treating a field in that payload as
proof of engine origin is a trust boundary the rest of `#85` was built to
avoid.

**Failure scenario.** An operator restores a machine from a snapshot written by
an older build (or a corrupted/edited one). An event named `after.<anything>`
in `pending_events` is delivered with engine standing: it is invisible to `"*"`,
does not trip `onUnhandled: "error"`, and passes `strict` undeclared. The
`#98` guarantee — "a user event is user traffic whatever it is called" — holds
live and not after a restore.

**Severity High.** A provenance-based security/correctness decision is made
from untrusted persisted data, and it is the same decision three separate
issues in this release were filed to make name-independent.

**Note on the fix's own reasoning.** The docstring argues this is "the one
place a name is all we have". That is accurate but resolves the ambiguity in
the unsafe direction. A v1 record genuinely cannot distinguish the two cases —
which argues for treating v1 pending records as **user** traffic (the safe
default, matching #79's own thesis) and documenting the one-time behaviour
change, not for restoring the pre-#79 rule.

---

### H-4 — `Receipt.deferred` reuses the `id()`-keying defect `#75` fixed: unbounded growth and false positives (High)

**Files:** `src/xstate_statemachine/base_interpreter.py:465, 3335`;
`src/xstate_statemachine/interpreter.py:1278-1279`;
`src/xstate_statemachine/sync_interpreter.py:512-513`
**Repro:** `probes/main-5e07ba8/r35_deferred_growth.py`,
`r36_sync_deferred_growth.py`, `r6b.py`, `r5_deferred_idleak.py`

`_deferred_this_step: Set[int]` is populated with `id(event)` for every
deferred event (`base_interpreter.py:3335`) but discarded **only** on a
receipt-resolution path. An event deferred by a fire-and-forget `send()` has
no receipt, so its id is never removed.

Two consequences.

**(a) Unbounded growth.** 50 000 fire-and-forget defers on the async engine
(`r35`), with `deferLimit: 1` so at most one event is actually held:

```
deferred_events held :  1000
_deferred_this_step  : 50000   <- grows without bound
approx bytes         : 2097368
```

The set is per-interpreter and never trimmed; the machine's own defer buffer is
capped (`DEFER_MAX`) but this bookkeeping set is not. This is the identical
shape as the `_SIBLING_FALLBACKS_WARNED` leak that *this same diff* bounded to
1 024 entries (`resolver.py:90-104`) — the ride-along fix was applied to one
unbounded id set and not to the one introduced two commits earlier.

**(b) False `deferred=True` on a correctly handled event.** `id()` is reused
after an object is freed. A stale entry for a dead deferred event collides with
a live, handled one (`r6b`):

```
stale ids retained: 1026
HANDLED 'GO' reported deferred=True: 1/20000
VERDICT: DEFECT REPRODUCED
```

`r5` reproduces the same at 1/2 000 on the sync engine under lighter load.

**Failure scenario.** The whole point of `#84` is that a caller must be able to
tell "held, will run later" from "processed, no-op". A false `deferred=True`
tells an order service that a `CANCEL` it *did* execute is still pending; the
documented guidance in `testing-and-pure-api.md` is "do not read `changed` as a
no-op" when `deferred` is set, so the caller will retry or wait. Rate is low
but non-zero and load-dependent, which is the worst profile for a money path.

**Severity High.** `#75` established that `id()` is not a safe key for
per-event bookkeeping in this codebase and fixed it by giving the queued
envelope its own identity held alive by the receipt map. `_deferred_this_step`
has no such liveness anchor. Holding the event object (a `set` of `id()` plus a
strong ref, or keying on the envelope the receipt map already pins) would fix
both halves.

---

### M-1 — `Receipt` grew a fourth field: an undeclared public-API break (Medium)

**File:** `src/xstate_statemachine/events.py:352-356`
**Repro:** `probes/main-5e07ba8/r41_receipt_arity.py`

`Receipt` is an exported `NamedTuple` (`Receipt` is in `__all__`). Adding
`deferred` changes its arity:

```
3-tuple unpack BREAKS: too many values to unpack (expected 3)
len(Receipt): 4 | ==-compat with 3-tuple: False
```

`ids, changed, err = receipt` — the natural spelling for a 3-field NamedTuple,
and one the 0.8.0 docs' own examples invite — raises `ValueError` after
upgrading. Equality against a 3-tuple also flips to `False`.

The CHANGELOG lists `Receipt.deferred` under **Fixed**, not under a breaking-
change heading, and neither `docs/_guide/changelog.md` nor
`testing-and-pure-api.md` mentions that existing unpacking breaks. For a
pre-1.0 library this is a legitimate change to *make*; it is not legitimate to
make it silently. **Medium**, not High: it fails loudly and at the first call.

---

### M-2 — `#94`'s "completions are never discarded" holds on the sync engine only (Medium)

**Files:** `src/xstate_statemachine/sync_interpreter.py:656-740` (implemented)
vs `src/xstate_statemachine/interpreter.py:1173-1196` (not implemented)
**Repro:** `probes/main-5e07ba8/r31_async_completion_drop.py`

The CHANGELOG says completions are never discarded "on **both** engines", and
`json-config.md` repeats "Engine completions (`done.invoke`, `error.platform`)
are never discarded" without qualification. The sparing logic
(`spare = is_completion and not tripped`, the `keep`/`victims` partition) exists
only in `SyncInterpreter._process_event_queue`. The async trip handler drops
whatever event is at the head of the queue with no `is_system_event` check.

`r31` does **not** reproduce a stranded machine — the async engine's
`_raise_depth` accounting happens to spare the completion in the case tested
(`done.invoke DELIVERED`). So this is a **documentation-overreach / latent
divergence** finding, not a confirmed data-loss one: the guarantee is written
as unconditional and is enforced by construction on one engine and by
circumstance on the other. Given H-1 shows the async trip handler *does* drop
events that reach its head, the circumstance is not one to rely on.

**Medium.** Two engines, one documented guarantee, one implementation.

---

### M-3 — `create_machine()` still mutates a duck-typed logic object (Medium)

**File:** `src/xstate_statemachine/factory.py:212-219, 276-279`
**Repro:** `probes/main-5e07ba8/r22_ducktyped_mutation.py`

`#92`'s copy is conditional on `isinstance(final_logic, MachineLogic)`; the
duck-typed branch is explicitly left as-is. But `_alias_logic_names` then runs
`setattr(logic, attr, owned)` unconditionally, so for a duck-typed logic object
— a shape the code comments call "duck-typed **by contract**" — the caller's
attributes are still replaced and the alias keys still appear:

```
duck-typed caller's .actions object REPLACED: True
duck-typed caller's keys mutated: True -> ['storeUser', 'store_user']

MachineLogic caller keys after 1st machine: ['store_user'] (unchanged: True)
```

The `MachineLogic` path is genuinely fixed. The issue's stated invariant —
"`create_machine` is a pure function of its inputs again" — holds for one of
the two supported input shapes.

**Ride-along (Low, same fix).** `copy.copy(final_logic)` is shallow, so a
`MachineLogic` **subclass** shares all its other instance state across every
machine built from it, and auto-registered bound methods still close over the
*original* instance (`r23`): `m1.logic.counter is l.counter → True`,
`actions["bump"].__self__ is l → True`. That is arguably the right behaviour
(the user's object is what should run), but it means the "machine-owned logic"
framing is true only of the three registry dicts. Worth a docstring sentence.

**Memory answer for the review question.** Measured at 1 000 machines from one
`MachineLogic` with 200 actions + 200 guards (`r11`): **17.18 MiB total,
17.6 KiB per machine**, callable identity preserved, caller untouched. The
per-machine cost is the three copied dicts, not the callables. At our expected
scale this is a non-issue; recording it so the number exists.

---

### L-1 — `AfterEvent` telemetry is silently dropped by the v2 codec (Low)

**File:** `src/xstate_statemachine/events.py:292-302`
**Repro:** `probes/main-5e07ba8/r37_after_lateness_loss.py`

`persist_event` writes only `{"kind": "after", "type": ...}`. `AfterEvent`
carries `scheduled_for` and `fired_at` (the `#48` lateness telemetry), and
`restore_event` reconstructs it with both at `0.0`:

```
original  : AfterEvent(type='after.5000.m.pending', scheduled_for=1000.0, fired_at=1007.5) lateness_ms= 7500.0
restored  : AfterEvent(type='after.5000.m.pending', scheduled_for=0.0, fired_at=0.0)       lateness_ms= 0.0
```

A restored due-timer event reports `lateness_ms = 0.0` — not "unknown",
**zero**, which is an affirmative claim that the timer was on time. Any
lateness alerting reads a restored event as healthy. The v2 layout was designed
precisely so "every event class round-trips"; this one round-trips its type and
loses its data.

---

### L-2 — `DoneEvent.data` is stringified into the snapshot by `default=str` (Low)

**File:** `src/xstate_statemachine/events.py:296-298` +
`base_interpreter.py:946`
**Repro:** `probes/main-5e07ba8/r40_done_data_coercion.py`,
`r38_done_data_nonjson.py`, `r39_snapshot_json_ab.py`

`persist_event` deep-copies `DoneEvent.data` verbatim; `get_snapshot()` then
runs `json.dumps(..., default=str)`. A service returning a `Decimal`,
`datetime` or `set` is silently coerced to its `str`:

```
persisted     : [{'kind':'done','type':'done.invoke.svc','data':{'amount':'10.50'},'src':'svc'}]
onDone received: {'amount': '10.50'} types: {'amount': 'str'}
VERDICT: Decimal -> str, silently: True
```

`get_snapshot()` does not fail (`r39` A/B: both commits OK), so this is not a
regression — but before this diff the record was *dropped* (bug #87) and now it
is *silently mistyped*. An `onDone` handler that did `data["amount"] * qty`
worked before the restore and raises `TypeError` after it. **Low** only because
it requires a restore of a pending completion with non-JSON data; the money
relevance (`Decimal`) is why it is listed at all. Worth a `TypeError` at
persist time rather than a lossy coercion.

---

### L-3 — provenance does not survive `deepcopy` or `pickle` (Low)

**File:** `src/xstate_statemachine/events.py:240, 253`
**Repro:** `probes/main-5e07ba8/r1_provenance_copy.py`

```
original      : True
copy.copy     : True
copy.deepcopy : False
pickle roundtr: False
```

An identity sentinel cannot survive process boundaries by construction — this
is inherent to the chosen mechanism, not a coding slip, and the snapshot codec
(`kind`) is the intended cross-process path. Recording it because:

- `deepcopy` losing it is surprising while `copy` keeps it, and the codebase
  deep-copies event payloads in several places;
- `multiprocessing` / `concurrent.futures` hand-off of an engine event is
  therefore a silent demotion to user traffic (same consequence as H-2);
- it is undocumented.

Also in scope of the review question "how private is it really": **it is not
private against in-process code.** `events._ENGINE_MARK` is a module attribute,
and a public mint (`system_event`) hands out an object carrying it (`r2`):

```
forged via module attr : True
forged via public mint : True
```

Both forgeries need `object.__setattr__` on a frozen dataclass plus a private
name or a donor object — i.e. deliberate, not type-checked, not reachable from
the documented API. That is a genuine and adequate improvement over a public
`system: bool` field, and the pinned test
(`test_mutating_private_slot_with_a_bool_does_not_forge`) correctly covers the
naive attempt. The claim to make in the issue comment is "not forgeable from
the public API", not "not forgeable".

---

### L-4 — new mechanisms are documented only in the changelog; two are unexported (Low)

**Repro:** `probes/main-5e07ba8/r24_docs_undocumented.py`

| Symbol | Guide coverage |
|---|---|
| `Receipt.deferred` | `changelog.md` + a good new table in `testing-and-pure-api.md` ✅ |
| `RunawayChainError` | `changelog.md`, `json-config.md`, `testing-and-pure-api.md` ✅ |
| `last_error` | `changelog.md`, `json-config.md`, `testing-and-pure-api.md` ✅ |
| `persist_event` / `restore_event` | **`changelog.md` only** |
| `system_event` | **`changelog.md` only**, and not in `__all__` |
| `is_system_event` | **no guide page at all**, and not in `__all__` |

`is_system_event` is now the single predicate behind `strict`, `onUnhandled`
and `"*"` — the semantics three issues in this release turn on — and it is
neither exported nor documented outside the changelog. `system_event` is named
in the changelog as "the ONLY way to produce" an engine event but is not
importable from the package root. This is G-12 from the `26-` verdict,
unchanged. The `snapshots.md` v2 paragraph and the `json-config.md`
`maxIterations` paragraph are both good additions; the gap is the events module.

---

## 2. What verifies clean

Recorded so the next pass does not re-litigate settled items.

| Item | Evidence |
|---|---|
| **#84 `Receipt.deferred`** — deferred vs handled vs no-op, both engines | `r4`: `deferred=True` on hold, `False` on handled, on async and sync. (Correctness of the *flag*; H-4 is the bookkeeping.) |
| **#85 provenance not forgeable from the public API** | `r2`: `Event("X", system=True)` is a `TypeError`; `system` is a read-only property; setting `_provenance = True` does not forge. |
| **#86/#87 snapshot v2** | `r3`: all five kinds round-trip with a correct `kind`. `r18`: a pending `ErrorEvent` is persisted **and delivered** after restore (`m.failed`), matching the user-event baseline. `r19`: identical under every `onUnhandled` setting. |
| **v2 forward-compat** | `r16`: 0.8.0-era code reading a v2 payload gets `SnapshotVersionError: Snapshot version 2 is newer than the supported version 1. Upgrade xstate-statemachine to restore it.` — clean, actionable, names the remedy. |
| **`machine_hash` scope** | `r10`: action **params** are still excluded (`assign amount=1` and `amount=1000000` hash equal). Unchanged by this diff and documented as deliberate in `_node_shape`; re-pinned because the review asked. |
| **#77 criterion 6 observable** | `r9`: sync receipt carries `RunawayChainError`, `last_transition_ok=False`, `last_error` set. Async: `last_error` is `RunawayChainError`. |
| **#88 `tripped` is per chain** | `r9`: `send_events(["SPIN"] + ["WORK"]*5)` → 5 of 5 `WORK` handled on both engines (was 0 of 5). |
| **#89 `**kwargs` is not consent** | `test_clock.py` diff inverts the assertion correctly; `r24`-adjacent reading confirms `_accepts_kwarg` now requires an explicitly named non-`VAR_KEYWORD` parameter and defaults un-introspectable callables to the legacy shape (the safe direction). |
| **#91 shadowed near-duplicates warn** | `r34`: `UserWarning` names both spellings; the exact key still wins. |
| **#92 `MachineLogic` not mutated** | `r22`, `r11`: caller's registry untouched, callables shared by identity, 17.6 KiB/machine. (M-3 is the duck-typed gap.) |
| **#95 no self-inflicted `DeprecationWarning`** | `plugins.py` now branches on `ErrorEvent` before the `.data` fallback. |
| **#96 `_resolve_event_spec` dict payload** | Code review: `ErrorEvent` → `{"error":…, "src":…}`, non-mapping `data` → `{"data":…, "src":…}`. |
| **#97 `escalate` mints an `ErrorEvent`** | `base_interpreter.py:2689-2700`, non-exception payloads wrapped in `RuntimeError`. |
| **#98 strict exempts by provenance** | `r47` first line: live `after.party` → `UnknownEventError`. (H-3 is the restore hole.) |
| **#99 sync child-machine `onError`** | `r20`: with a handler → `p.failed` + `ErrorEvent` carrying the child's error; without → parent `status=error`. Parity with the async engine. Note the completion is observed on the next `tick()`, not at `start()` — correct for the non-blocking runner, worth knowing when writing tests. |
| **#31 `_SIBLING_FALLBACKS_WARNED` bounded** | `resolver.py:90-104`, cap 1 024, cleared on overflow; pinned by `test_set_never_exceeds_cap`. |
| **No deadlock from the #90 reroute** | `r8`: a rerouted `send(..., wait=True)` **does** resolve its receipt (the run loop resolves it after the macrostep); no orphaned futures. |
| **No FIFO regression from the #90 reroute** | `r28`, `r29`, `r30` A/B: ordering vs an idle-queued event, vs an external backlog, and vs `send_threadsafe` is **identical** at `3c527b0` and `5e07ba8`. (The `send_threadsafe` reorder shown in `r29` is pre-existing at both commits, not introduced here.) |

**Test-quality check.** No `xfail`, no `skip`, no `TODO`/`FIXME` in
`tests/test_round3_findings.py`. The three modified existing tests
(`test_clock.py`, `test_factory.py`, `test_persistence.py`) are **not**
weakened: the clock test inverts an assertion that encoded the #89 bug; the
factory tests replace an `assertIs(machine.logic, caller_logic)` identity
assertion with an explicit callable-identity check that preserves the contract
the test existed for and adds the non-mutation contract; the persistence tests
absorb the new `kind` key. `_snake_to_camel` and its docstring examples were
deleted along with the aliasing it fed — correct, and the ambiguity rule that
replaces it is stricter.

---

## 3. Disposition for the adoption gate

- H-1 is a **regression** and should block the 0.8.1 tag on its own: it is
  silent loss of accepted external events at default settings on the async
  engine.
- H-2 and H-3 are both "the new provenance rule was not audited across a
  boundary" — the same root cause as the `26-` verdict's G-2. A third instance
  in two releases suggests the fix should be a systematic audit of every place
  an `Event` is reconstructed (`_detach`, `restore_event`, `deepcopy` sites),
  not three more point fixes.
- H-4 is the `#75` lesson not carried across to the `#84` bookkeeping.
- M-1 should be reclassified in the CHANGELOG as a breaking change before the
  tag.

Constraint impact on our side: **CV-C06** (the `onUnhandled: "defer"`
discriminator) now has a real mechanism — `Receipt.deferred` answers the
question the `deferred_count` probe could not (`26-` verdict §0). It is usable
**subject to H-4**: the flag is correct in the common case and wrong at a low,
load-dependent rate, so CV-C06 should treat `deferred=True` as advisory and not
as the sole gate on a retry decision until H-4 lands. Our in-house shim
(ADR-0016 Part 2) remains the execution path and is unaffected by all four
High findings.

---

## 4. Artefact index

All under `docs/research/xstate/probes/main-5e07ba8/`.

| Probe | Finding |
|---|---|
| `r1_provenance_copy.py` | L-3 |
| `r2_forge.py` | L-3, L-4 |
| `r3_snapshot_v2.py` | H-3, §2 |
| `r4_deferred_receipt.py` | §2 (#84) |
| `r5_deferred_idleak.py`, `r6_deferred_false_positive.py`, `r6b.py` | H-4 |
| `r7_async_send_reroute.py`, `r8_selfsend_receipt_orphan.py` | §2 (no deadlock) |
| `r9_runaway.py`, `r32_async_receipt_type.py` | §2 (#77, #88) |
| `r10_hash_params.py` | §2 (machine_hash) |
| `r11_registry_mem.py` | M-3 (memory) |
| `r12`–`r14`, `r25`, `r27` | **H-1** |
| `r16_fwdcompat.py` | §2 (forward compat) |
| `r17`–`r19` | §2 (#86/#87) |
| `r20_sync_child_error.py`, `r21_child_status.py` | §2 (#99) |
| `r22_ducktyped_mutation.py`, `r23_machinelogic_subclass.py` | M-3 |
| `r24_docs_undocumented.py` | L-4 |
| `r28`, `r29`, `r30` | §2 (no FIFO regression) |
| `r31_async_completion_drop.py` | M-2 |
| `r34_shadow_warn.py` | §2 (#91) |
| `r35`, `r36` | H-4 (growth) |
| `r37_after_lateness_loss.py` | L-1 |
| `r38`, `r39`, `r40` | L-2 |
| `r41_receipt_arity.py` | **M-1** |
| `r43`, `r44` | **H-2** |
| `r46`, `r47` | **H-3** |
