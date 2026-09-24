# Round-9 diff review — `6db65d8..f28719c` (unreleased 0.8.1)

**Scope.** 14 files, ~2.2k lines. All `src/` and `tests/` changes read in full.
Library at `C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine`
@ `f28719c` (`__version__` still `0.8.0`; key on the commit).
`tests/test_round8_findings.py` (29) + `tests/test_round7_findings.py` (37) — **66 passed** locally.

**Probes.** All standalone (stdlib + `xstate_statemachine` only), under
`docs/research/xstate/probes/main-f28719c/`. Every service/action check runs
BOTH `def` and `async def` where the distinction can matter. Where a probe also
runs against `6db65d8` (via `PYTHONPATH` to a `git archive` of the old tree) the
result is given for both, so a finding is labelled *new* or *pre-existing*.

| # | Severity | Finding | Probe | New in this diff? |
|---|---|---|---|---|
| N-1 | **High** | `#195` does not cover `done.state.*`: a hand-built `DoneEvent` drives a parallel/compound `onDone` on both engines | `p1`, `p15` | incomplete fix (new gate missed this path) |
| N-2 | **High** | `#195` does not cover `after.*`: a hand-built `AfterEvent` fires a 60 s timer transition instantly on both engines | `p2`, `p15` | incomplete fix |
| N-3 | **High** | The live-invocation gate is *only* a provenance test; a genuine completion replayed from a snapshot drives a freshly-armed invocation's `onDone` with stale data | `p5` | new (gate introduced here) |
| N-4 | **High** | `_replace` on a genuine completion preserves the private subclass, so any action/plugin can mint a trusted completion for *another* invocation; `engine_done` is also importable | `p7` | new |
| N-5 | **High** | A delayed self-`send` cycle is charged to nothing and, under `#192`, is now explicitly tagged *external* so the shed can never cut it — unbounded spin with `maxIterations` inert | `p3` | pre-existing; `#192` cements it |
| N-6 | Medium | The `#192` provenance tag and the priority lane itself are lost across a snapshot round-trip: every lane item restores into the inbox as external traffic | `p12` | new (tag), pre-existing (lane) |
| N-7 | Low | `#198` narrows v1 compatibility: a `version: 1` running blob without `configuration` used to restore and is now refused. The changelog names only the v0 shape | `p6` | new |

Verified-clean (probes exit 0, kept as regression pins):
`p8` (`children_timeout` per child), `p9` (`#193` ordering / roll-forward, both kinds),
`p10` (`_seed_pending` not spent by unrelated traffic), `p11` (`#192`/`#201` lap parity,
both kinds, both engines), `p13` (`#196` sync child reaping: leak, double-stop,
stop-during-bring-up — **fails on `6db65d8`, passes here**), `p14` (`always` still
selected in the settle pass after a named event), `p16` (start-hook exception does not
wedge the in-flight flag on either engine).

---

## N-1 — `#195` leaves `done.state.*` forgeable (High)

`_completion_is_for_live_invocation` is consulted from exactly one branch of
`_select_transitions` (`base_interpreter.py:4532`, the `invoke` `onDone`/`onError`
branch). The branch immediately above it —

```python
# 🏁 `onDone` transitions for compound/parallel states.
if current.on_done and current.on_done.event == event.type:
    if _passes(current.on_done):
        eligible.append(current.on_done)
```

— matches on `event.type` alone, with no provenance test and no type test. A
parallel state's `onDone` is therefore driven by a hand-built
`DoneEvent("done.state.m.work", ...)` while both regions are still in their
non-final states.

```
async: states=['m.finished'] forged_onDone_taken=True
sync:  states=['m.finished'] forged_onDone_taken=True
```

This is exactly the shape `#195` set out to close — the changelog says a
hand-built `DoneEvent` "bypassed `strict` and `onUnhandled` and drove a real
`onDone`" — and `done.state` is a name `ENGINE_EVENT_SHAPES` already lists. Under
`strict=True` the new `UnknownEventError` path does refuse it (`p15`), but strict
is opt-in and the default-mode machine transitions.

Repro: `probes/main-f28719c/p1_forged_done_state.py` (exit 1); table in
`p15_strict_refusal_coverage.py`.

**Suggested fix.** Gate the `on_done` branch on `is_system_event(event)` the same
way the invoke branch is now gated.

---

## N-2 — `#195` leaves `after.*` forgeable (High)

Same omission, `base_interpreter.py:4523`:

```python
if isinstance(event, AfterEvent):
    for transitions in current.after.values():
        for t in transitions:
            if t.event == event.type and _passes(t):
```

`isinstance` matches the public NamedTuple — precisely the test `#195` replaced
everywhere else. A caller who knows the state id can fire a 60-second timer
instantly on both engines:

```
async: states=['m.expired'] forged_timer_fired=True
sync:  states=['m.expired'] forged_timer_fired=True
```

The published docs assert the opposite. `docs/api/index.md` now says a hand-built
`AfterEvent` "does not drive … `after`", and the `#195` changelog entry says
`is_system_event` "requires them". Both are false for the default (non-strict)
interpreter.

Of the two forgery gaps this is the more dangerous: `after` is the documented
spelling for time-in-force / session-timeout scaffolding, and the forgery needs
only the delay and the state id, both of which are in the chart.

Repro: `p2_forged_after.py` (exit 1).

---

## N-3 — the live-invocation gate does not test liveness (High)

```python
def _completion_is_for_live_invocation(self, state, invocation, event) -> bool:
    return is_system_event(event)
```

The name, the docstring and the changelog all promise SCXML §6.4.2 ("only for an
invocation that is OUTSTANDING"); the body tests provenance only. The docstring's
justification — *"a completion that reaches this point for a state that was exited
is impossible because exiting cancels the work"* — stops being true once
`restore_event` can mint engine-provenance completions, which is also new in this
diff.

`p5_stale_completion_roundtrip.py` persists a running machine whose
`pending_events` carries a genuine `done.invoke.fetch`
(`{"kind":"done",…,"engine":true}`), restores it, and the restored machine takes
`onDone` with the **stale** payload before the freshly-armed 1 s service has been
invoked at all:

```
states=['m.ready'] context.result={'value': 'STALE'} fetch_invocations=0
```

The two halves of `#195` interact badly: persisting provenance (so a genuine
round-trip keeps working) is what makes the liveness argument unsound, and the
gate added to enforce liveness does not enforce it.

**Suggested fix.** Either test actual outstandingness (an invocation-instance id
carried on the completion, matched against the live invocation), or refuse to
restore engine completions into a configuration that re-arms the same invoke id.

---

## N-4 — the private engine classes are reachable from user code (High)

`#195` states the subclasses "are not exported and have no public name; construct
through the `engine_*` helpers only". Three routes exist anyway:

1. `from xstate_statemachine.events import engine_done` — the minting helpers are
   module-level, un-underscored functions. `tests/test_round8_findings.py` itself
   imports `engine_done` this way.
2. **`_replace` preserves the subclass.** The docs advertise this as a feature
   ("`_replace` … behave the same and preserve the subclass"). Any action or plugin
   that receives a genuine completion can therefore re-address it:

   ```
   type(genuine) = _EngineDone
   is_system_event(forged via _replace) = True
   deepcopy keeps class: _EngineDone
   pickle keeps class: _EngineDone
   states=['m.done'] trace=['forge', 'mark:B-FORGED'] real_b_invocations=0
   ```

   Invocation `b`'s `onDone` ran with a forged payload while `b`'s real service had
   not been started once.
3. `pickle` / `deepcopy` round-trips preserve it (shown above), so a completion that
   crosses a process boundary carries mintable provenance with it.

Repro: `p7_engine_class_reachable.py` (exit 1).

The trust boundary `#195` draws is "user code cannot author a completion". That
boundary does not exist as drawn. What the change *does* achieve is real and worth
keeping — a naive `DoneEvent("done.invoke.fill", …)` no longer works — but the
documentation should claim defence-in-depth against accidental laundering, not a
security property. (The `restore_event` docstring already makes this concession for
snapshots; the API doc and changelog do not.)

---

## N-5 — a delayed self-send is charged to nothing, and `#192` guarantees it can never be shed (High)

`Interpreter._deliver` (`interpreter.py:2173`) fires a delayed self-directed send
with a bare `self._deliver_priority(target_event)` — default
`engine_completion=False`. Under `#192` that default is now stored on the item as
`self_generated=False`, and the run loop's cut is

```python
over = self._raise_depth > limit and self_generated
```

So a delayed self-send is (a) never counted into `_raise_depth`, and (b) after this
change *explicitly exempt* from the shed even if the budget had tripped. A
two-state cycle whose entry actions each schedule a 1 ms self-send spins forever
with `maxIterations: 20`:

```
laps(exits)=658   after 10s: raise_depth=0 chain_tripped=False states=['m.a']
```

Same result at `6db65d8` (642 laps), so the runaway is **pre-existing** — but `#192`
is the commit that made the exemption explicit and documented ("a caller's priority
send … is not the chain and is processed"), and a delayed self-send is not a
caller's send. Before the change the item's fate depended on position; now it is
guaranteed to survive. Any chart using `raise`-with-`delay` as a heartbeat has no
backstop.

Repro: `p3_delayed_selfsend_unbounded.py` (12 s watchdog; exit 1 on both commits).

**Suggested fix.** `_deliver` should pass
`engine_completion=self._issued_from_own_action()` when `actor is self`, exactly as
`send(priority=True)` now does.

---

## N-6 — the `#192` tag, and the priority lane, do not survive a snapshot (Medium)

`_persisted_pending` flattens the lane (`[ev for ev, _ in self._priority_queue]`)
and `_enqueue_restored` puts every restored record into the **inbox**. After a
round-trip:

```
lane before:         [('LANE', True)]
persisted pending:   ['LANE', 'INBOX']
lane after restore:  []
inbox after restore: ['LANE', 'INBOX']
```

Consequences: a self-generated lane item restores as external traffic (uncharged by
`maxIterations`, immune to the shed, and it resets the settle budget under the
`is_system_event`-keyed rule in the run loop); and a due `after` event that was in
the lane now queues *behind* any restored external backlog, losing the head-of-lane
guarantee `#48` exists to provide.

Losing the lane is pre-existing; losing the *provenance tag* is new with `#192`, and
the tag is the one thing the change exists to preserve. If the tag is deliberately
not persisted (defensible — a restored machine's chain is new), the changelog should
say so, because "provenance travels WITH the event" reads as a durability claim.

Repro: `p12_priority_provenance_roundtrip.py` (exit 1).

---

## N-7 — `#198` narrows v1 restore compatibility beyond what the changelog states (Low)

The changelog says "v0 payloads keep the `state_ids`-only shape", implying v1
payloads always carried both fields. 0.8.0 shipped `SNAPSHOT_VERSION = 1` and its
writer *did* record `configuration`, so blobs produced by 0.8.0 restore fine. But a
v1 blob whose `configuration` was dropped downstream (a storage layer projecting a
subset of keys, a hand-rolled writer, a schema migration) restored at `6db65d8` and
is now refused:

```
6db65d8: A: v1 + both fields -> restored   B: v1 + state_ids only -> restored
f28719c: A: v1 + both fields -> restored   B: v1 + state_ids only -> REFUSED
```

The security argument is sound (emptying a field must be refused exactly like
contradicting it). The gap is documentation: this is a restore-compatibility
narrowing for a shape the library accepted one commit ago, and it belongs in a
migration note, not only in the security rationale. A machine that cannot restore is
an outage.

Repro: `p6_v1_blob_from_0_8_0.py` (exit 0 at `6db65d8`, exit 1 here — by design).

---

## Checklist answers (the ten brief questions)

**(1) Per-item provenance on the priority lane.** The tag lives on the deque item
(`Tuple[AnyEvent, bool]`), set in `_deliver_priority` from `engine_completion` and
read in the run loop. Where it can be lost:

- *Defer replay*: `_deliver_priority(ev)` with no kwarg → `False`. Correct and
  commented ("a replayed event keeps its original external standing"), though a
  deferred **self-raised** event also comes back as external. Low impact: the
  deferral policy only holds events that had no handler.
- *Snapshot round-trip*: lost entirely — **N-6**.
- *`send_threadsafe`*: decides `self_issued` on the calling thread and routes
  self-issued sends to the internal queue (always `self_generated=True` via
  `_next_event`). Correct.
- *`sendTo` between actors*: goes through `_send_to_actor` → the target's own
  `send()`, so the recipient classifies it by *its* own `_issued_from_own_action`,
  which is `False`. Correct — cross-actor traffic is external to the recipient.
- *Action-issued priority send charged like `raise`?* Yes on the async engine, and
  `p11` confirms identical trip laps for `raise` vs `send(priority=True)` at
  `maxIterations=10` for both `def` and `async def` (12 laps each) and for the sync
  engine's `def` lane (12). The sync engine ignores `priority` by design and refuses
  `async def` actions with `NotSupportedError`, so that cell is N/A rather than a
  parity gap.
- **Gap**: the *delayed* self-send path bypasses the whole scheme — **N-5**.

**(2) `def`-service handoff moved into the engine-held task.** `#116` ordering
holds: `p9` shows `order=['done', 'ping']` for `def` (the completion precedes an
event sent immediately after `start()`) and `['ping', 'done']` for `async def`,
which is the documented difference, not a regression. Roll-forward cancels before
submission: `rollforward_submissions=0` for both kinds. The "result arriving for an
exited state is ignored" path returns early *before* `_finish_plain_service`, so no
completion is published — and because the debt ledger is now keyed to the task
(`#200`) and settled by the task's own done-callback, the debt is released on that
path too; a receipt attached to such an event never existed (no event is created).
The Production-Characteristics § 2 paragraph is accurate for both engines.

**(3) `children_timeout` per child.** `_await_actor_bringups` now passes `timeout`
to each `asyncio.wait` *wave* rather than a shrinking global deadline. N concurrent
children settle in ~D: `p8` measures `start()` at 0.404 s for N=3, D=0.6 s,
`children_timeout=0.4 s`. The worst case is not `N·D` but `W·timeout` where `W` is
the number of bring-up waves — a child whose own bring-up arms a further child adds
a wave. Worth a doc sentence; not filed as a finding since the nesting is unusual
and the behaviour is strictly better than before. The WARNING path is correct and
fires on the non-yielding-`def` case (`p8` output), matching the new docs.

**(4) Private engine subclasses.** Reachable — **N-4**. `pickle`/`deepcopy` preserve
the class (verified). A forged snapshot record *can* set `"engine": true`; the
`restore_event` docstring concedes this explicitly and the reasoning (a writer of
arbitrary records already controls `state_ids`) is sound. Remaining `isinstance`
checks on the public NamedTuples: `base_interpreter.py:970` (`_coerce_event` — fine,
it is a coercion), `2448`, `4523` (**N-2**), `4532`+`4554` (gated by the new hook for
`invoke`; the `xstate.error.actor.` sub-branch at 4554 sits *inside* the gate, so it
is covered), `events.py:307-311` (`event_kind` — fine), `plugins.py:620` (display).

**(5) Eventless-only `always`.** The settle pass still runs after a named event, so
an `always` whose guard is flipped by that event's actions still fires — `p14`,
green on both engines and both action kinds. One behaviour change is *not* called
out in the changelog: an event that previously "matched" only because an `always`
was an eligible candidate is now genuinely unhandled, so `onUnhandled: "error"` and
`strict` fire where they did not. `p4` demonstrates it — but the same probe exits 1
on `6db65d8` too, so on the shapes tested this is pre-existing rather than
introduced; recorded as an observation, not a finding.

**(6) Sync engine reaping invoked children.** `p13` covers the leak (15 laps, thread
delta 0, `_actors` empty — **delta 15 and a leaked actor on `6db65d8`**), double
`stop()`, and `stop()` while a child is live. All clean. The `if self._actors.get(aid)
is child` identity guards are the right fix for the re-entry id-collision case.

**(7) `version >= 1` both fields non-empty.** 0.8.0-written blobs restore — **N-7**
for the narrowed edge.

**(8) `#200` / `#201`.** `_chain_owed` becomes a read-only property over
`_chain_owed_tasks`; the debt is settled by `task.add_done_callback(set.discard)`,
which fires for every terminal outcome including non-`Exception` `BaseException`.
This is a genuine leak fix. `_seed_pending` is armed only when the initial descent
left work in flight and is cleared by the first system event; `p10` confirms it is
not spent by unrelated traffic in a way that extends a runaway (laps identical with
and without a slow initial service).

**(9) "chain-end test counts arming, not a ledger delta" (`b79413a`).** The chain-end
test compared `self._chain_owed == owed_before`. Because the step that *consumes*
completion N also lets N's done-callback discard it from the set while *arming* N+1,
the set size is unchanged (1 → 1) and the delta test wrongly declared the chain
over — and the exact moment the callback runs differs across Python ≤ 3.11. The fix
counts arming events in the step (`_armed_this_step`), which is the right invariant:
"did this step start work whose completion is the next link?" is a question about
arming, not about ledger size. Correct, and the reason is worth keeping in the
changelog.

**(10) Undocumented changes / weakened tests / xfail.** No `xfail` and no skips in
the round-8 file. Two round-7 assertions were changed rather than deleted, both with
a stated reason: `seen == [2]` → `[1]` (the `#201` seed rule) and
`test_agreeing_fields_and_absent_configuration_restore` →
`test_agreeing_fields_restore_and_v0_may_omit_configuration`, which now asserts the
refusal *and* keeps a v0 positive case. Neither is a weakening — the second is
strictly stronger. Undocumented behaviour changes found: the priority-lane tag not
surviving a snapshot (**N-6**) and the v1 restore narrowing (**N-7**).

---

## Bottom line

The six fixes I could verify positively — `#193` ordering and roll-forward
cancellation, `#194` per-child timeout and its WARNING, `#196` sync child reaping,
`#200` task-keyed ledger, `#201` lap parity, `b79413a`'s arming count — all do what
they say, and `#196`'s child-reaping fix closes a real thread leak that reproduces on
`6db65d8`.

`#195` is the weak one. It genuinely closes the naive forgery it was reported for,
but it gates only the `invoke` `onDone`/`onError` branch while leaving `done.state.*`
(**N-1**) and `after.*` (**N-2**) forgeable in default mode, ships a liveness gate
that tests provenance instead of liveness (**N-3**), and rests on a private-class
boundary that `_replace`, `pickle` and a module-level import all cross (**N-4**). The
published docs state the stronger property as fact. For adoption purposes I would
treat `is_system_event` as a hygiene mechanism, not a trust boundary, and keep
`strict=True` on for any machine whose chart declares `after` or `onDone`.
