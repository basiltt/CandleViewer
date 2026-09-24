# 42 — Round-7 diff review: `cec108b..221ce7c`

Scope: PRs #165 / #176 (hot-path perf) and #177 / #178 (round-6 fixes
#166–#175, #157, #122-as-designed). ~1.7k lines across `src/` and `tests/`.
Read in full: `base_interpreter.py`, `interpreter.py`, `sync_interpreter.py`,
`clock.py`, `models.py`, `factory.py`, `resolver.py`, `logic_loader.py`,
`machine_logic.py`, and the three touched test files.

Library test suite at `221ce7c`: **3419 passed, 13 skipped** (470 s). No
deleted tests, no new `xfail`/`skip`. The only test edit is
`test_round4_findings.py::TestPriorityLanePersisted`, which stopped forcing
`_processing = True` as a freeze because #169 now refuses a root snapshot on
"in flight" alone — a legitimate fixture repair, not a weakening; the
assertion it guards is unchanged.

Probes: `docs/research/xstate/probes/main-221ce7c/p1..p10`.

---

## Verdict summary

| ID | Area | Severity | Status |
|----|------|----------|--------|
| L-1 | `_deliver_priority` charges **external** `send(priority=True)` to the chain budget | **Blocker** | Reproduced (`p1`) |
| L-2 | `await start()` hangs unboundedly on a slow invoked child (#171) | **Blocker** | Reproduced (`p2`) |
| L-3 | #166/#167/#168 bound only the **plain-`def`** service path; the coroutine invoke cycle is still unbounded | **Blocker** | Reproduced (`p3`) |
| L-4 | External traffic renews the per-macrostep settle budget mid-chain | High | Reproduced (`p4`) |
| L-5 | `_await_settled_for_snapshot` spins `time.sleep` on the loop thread | High | Reproduced (`p10b`) |
| L-6 | Sync `_deferred_this_step` never cleared on `wait=False` — unbounded growth | Medium | Reproduced (`p7`) |
| L-7 | `_threadsafe_self_sends_in_flight` balance (#172) | — | **Negative** — holds (`p5`) |
| L-8 | `__slots__` compatibility | — | **Negative** — clean (`p6`) |
| L-9 | `_guard_denied_this_step` stickiness on `wait=False` | — | **Negative** (`p8`) |
| L-10 | `after`-timer charging in practice; `service_pool_size`; sentinels; lazy lock; single-pass parser | — | **Negative** — see notes |

Three blockers. All three are in the machinery this round added, and all
three are in the direction the round-6 notes say the design exists to avoid.

---

## L-1 — `_deliver_priority` charges *external* `send(priority=True)` to the chain budget — **Blocker**

`interpreter.py:2288`

```python
def _deliver_priority(self, event: AnyEvent) -> None:
    if self._processing:
        self._raise_depth += 1
    self._priority_queue.append(event)
```

The test is **when** the event lands, not **who** issued it. But
`send(..., priority=True)` is public external API and routes straight here
(`interpreter.py:811`). Any outside producer that enqueues while a macrostep
is open — i.e. any producer faster than the loop, which is the only regime
where this matters — has its events counted as self-generated and dropped at
`max_iterations`.

This is precisely the failure the run-loop's own architecture note says the
design exists to prevent:

> An earlier version incremented whenever the queue was non-empty after
> processing, which cannot tell a runaway `raise` from a merely busy
> producer — 5,000 legitimate concurrent `send()` calls lost 3,999 of them.

`p1` reproduces it against `main`. 3,000 external `send("PING", priority=True)`
from a plain producer coroutine, no `raise` anywhere:

```
sent=3000 processed=1162
dropped=1838 reasons={'chain_budget'}
```

**61% of legitimate external sends silently discarded**, reported as a runaway
chain. Drip-feeding one per loop turn still loses 2. The machine has no `raise`,
no self-`send`, no cycle — it is a single state with one counting action.

Also note the recovery clause hides it: the drop path resets
`_raise_depth = 0` when the lanes happen to empty, so `_raise_depth` and
`_chain_tripped` both read clean afterwards (`p1` ends at `0` / `False`) and
`last_error` is `None`. The loss is observable only through
`on_event_dropped`. A caller polling `last_error` for chain trouble sees
nothing.

Fix direction: decide provenance the way `send()` already does —
`_issued_from_own_action()` (or an explicit `internal=` carried by the
caller) — not by `_processing`. A priority delivery from
`_after_timer._fire`, `_finish_plain_service` and `_deliver` is engine work;
`send(priority=True)` from user code is not.

---

## L-2 — `await start()` hangs unboundedly on a slow invoked child (#171) — **Blocker**

`interpreter.py:561`, `2586`

#171 makes `start()` await invoked-child bring-up:

```python
await self._await_actor_bringups()
...
async def _await_actor_bringups(self) -> None:
    while self._actor_bringups:
        pending, self._actor_bringups = self._actor_bringups, []
        await asyncio.gather(*pending, return_exceptions=True)
```

`gather` with **no timeout**. The bring-up coroutine `_start_invoked_actor`
awaits `child.start()`, which runs the child's entry actions. The changelog
calls bring-up "transient (microseconds)" — true of the engine's own work,
not of the user entry action the child's initial state declares. Before #171
`start()` returned regardless; now an awaiting entry action on a child is a
startup hang on the parent.

`p2`: parent invokes a child whose initial state has an entry action that
awaits (stands in for a lock, a socket, a connection pool):

```
start() still not returned after 8s (child entry sleeps 30s)
status=running
VERDICT: START() HANGS ON A SLOW INVOKED CHILD (no timeout)
```

`status` reads `"running"` throughout, so a health check sees a live machine
while `start()` has not returned and no event has ever been read. The
`except Exception` recovery in `start()` never runs — nothing raised.

The `while` loop compounds it: a bring-up that itself enters another invoking
state appends more tasks, so the wait spans a transitive closure of children,
not one level.

Fix direction: bound the wait (`asyncio.wait_for` on a documented startup
timeout) and surface the timeout, or await only registration in `_actors`
rather than the child's full `start()`.

---

## L-3 — the invoke-cycle bound covers only plain-`def` services; the coroutine path is still unbounded — **Blocker**

This is the #168 fix landing on one of two delivery paths.

A **plain-`def`** service completes through `_finish_plain_service`, which
calls `_deliver_priority(done_event)` — the priority lane, charged, and
dequeued with `from_inbox=False`.

A **coroutine** service completes through `_invoke_service_task`:

```python
await self.send(done_event)      # interpreter.py:2413
```

which is the ordinary inbox. Two consequences, both fatal to the round-6 fix:

1. `_deliver_priority` never runs, so `_raise_depth` is never incremented —
   the chain budget cannot accumulate. (`send()` from the service task is not
   `_issued_from_own_action()`; the task is not inside a user action of this
   interpreter.)
2. The event is dequeued with `from_inbox=True`, so the run loop's reset
   clause fires on **every lap**:

   ```python
   if not is_system_event(event) or from_inbox:
       self._settle_iterations = 0
       self._settle_tripped = False
   ```

   A `DoneEvent` *is* a system event, but `from_inbox` is True, so the
   per-macrostep settle budget — the whole of #166 — is handed back each time
   round.

`p3` runs the #168 `ver -> arm -> ver` ping-pong twice, identical config
(`maxIterations: 50`), changing only `def` to `async def`:

```
[plain-def] laps=25   settle_tripped=True  last_error=RunawayChainError  -> BOUNDED
[coroutine] laps=5324 settle_tripped=False last_error=NoneType           -> UNBOUNDED
```

5,324 laps against a declared limit of 50, still climbing when the probe's own
watchdog cut it. The changelog's claim — "The invoke cycle now trips at the
same lap count on both engines" — holds only for plain services, which are the
*documented minority* path (the same docs tell users to make a service a
coroutine so it does not block timers, #174). The recommended shape is the
unbounded one.

Fix direction: the reset must not treat arrival via the inbox as proof of
externality for engine-minted completions, and `_invoke_service_task`'s
completion should travel the same charged lane the plain path uses.

---

## L-4 — external traffic renews the per-macrostep settle budget mid-chain — High

Same reset clause. `_settle_iterations` is reset whenever an external event
begins a step, by design ("the sync engine's #103/#151 rule"). But on the
async engine the chain and external traffic interleave freely: a chain made of
`always` hops plus completions yields to the loop between macrosteps, so any
external event in between hands the chain a fresh allowance.

`p4` — the same `ver`/`arm` cycle at `maxIterations: 20`, with and without a
steady drip of an external `NOISE` event the machine handles as a self-loop:

```
[noise=False] laps=10   settle_tripped=True -> BOUNDED at ~20
[noise=True]  laps=1010 settle_tripped=True -> BUDGET RENEWED BY EXTERNAL TRAFFIC
```

The trip flag is set — and immediately cleared again by the next `NOISE`.
A 100× overshoot from ordinary traffic; the ceiling is
`laps ≈ limit × external event count`, i.e. unbounded in wall-clock terms on a
live machine. For a venue-facing machine (market-data ticks are exactly this
drip) the settle budget is not a bound at all.

The sync engine does not have this shape because a drain is not interleaved
with external arrivals.

---

## L-5 — `_await_settled_for_snapshot` spins `time.sleep` on the event-loop thread — High

`base_interpreter.py:1274`

```python
while (self._step_in_flight() and not self._configuration_is_legal()
       and time.monotonic() < deadline):
    time.sleep(0.0005)
```

The docstring justifies the blocking spin by assuming the child runs on its own
thread: *"a sync child's step runs on its actor thread and completes in
microseconds"*. For an **async** child invoked by an async parent, both run on
the same event loop. `time.sleep` on that loop is exactly what prevents the
child from making progress, so the condition can never clear: the wait always
burns the full 500 ms deadline, then snapshots the torn configuration anyway.

#169 widened the reach of this path — legality is now the test for the child
branch specifically, so it is hit more often.

`p10b`, parent snapshot taken over a child that is mid-step for 500 ms:

```
(b) parent snapshot over a mid-step ASYNC child: snapshot returned after 503 ms
    of loop-blocking spin
```

503 ms with the entire event loop frozen — every timer, every actor, every
inbound send on that loop. The timer-lateness bound the priority lane exists to
provide (#48) is void for that window. And the result is the torn snapshot the
wait was supposed to avoid.

`p10a` confirms the #169 root refusal itself is correct and parity-clean on both
engines (entry-action snapshot → `SnapshotMidStepError` on sync and async alike).

Fix direction: on the async engine the settle wait must be an `await`
(`asyncio.sleep`) reached through an async snapshot entry point, or the child
branch must refuse rather than spin.

---

## L-6 — sync `_deferred_this_step` never cleared on `wait=False` — Medium

`sync_interpreter.py:565-571`. The perf change moved the per-step resets under
`if wait:`:

```python
if wait:
    config_before = frozenset(...)
    if not self.machine.context_is_immutable:
        context_before = copy.deepcopy(self.context)
    self._deferred_this_step.clear()     # #106: per-step scope
    self._guard_denied_this_step = False # #153: per-step scope
```

`_deferred_this_step` is appended to unconditionally by
`_handle_unhandled_event` (`base_interpreter.py:3978`), regardless of `wait`.
On the documented fire-and-forget shape the list is therefore never cleared and
grows for the life of the interpreter.

`p7`, 5,000 `send()` calls under `onUnhandled: "defer"`:

```
sends=5000
_deferred_this_step (per-STEP scope) = 5000
_deferred_events    (the real buffer) = 1000
after one wait=True send: _deferred_this_step = 1
```

The real defer buffer is correctly capped at 1,000; the per-step list is not
capped at all. Two costs: unbounded memory on a long-lived machine that defers,
and the `any(ev is event for ev in self._deferred_this_step)` scan each
`wait=True` receipt performs becomes O(sends-since-last-wait).

Not a correctness bug for the receipt itself — the first `wait=True` send clears
the list before the step, so `deferred` is still computed against a clean list
(the count drops to 1 above). Bounded-growth / performance, hence Medium.

---

## Negative results (checked, no finding)

**L-9 — `_guard_denied_this_step` staleness.** The sibling of L-6, reset by the
same `if wait:` block. `p8`: a `wait=False` guard-denied send does leave the
flag `True`, but the next `wait=True` send clears it *before* processing, so
`Receipt.denied` stays correct (`denied=False` on an event no guard saw,
matching the clean-interpreter baseline). No leakage into the
`(denied, error is None)` discrimination #170 documents.

**L-7 — threadsafe in-flight counter (#172).** `p5` hammers
`send_threadsafe(internal=True)` from 8 threads × 500 sends. The done-callback
balances exactly: `in_flight_counter=0` at rest, no double-fire, no leak. The
callback fires once per future by `concurrent.futures` contract, including for
a cancelled future, so the "loop stopped before the coroutine ran" case is
covered. Holds.

Incidentally `p5` shows the *intended* behaviour of the chain budget: 4,000
genuinely self-issued sends → `_raise_depth=4000`, `chain_tripped=True`, 989
processed. That is correct load shedding — and the contrast with L-1 is exactly
the provenance test `_deliver_priority` is missing.

**L-8 — `__slots__` (#165).** `p6`: `__dict__` is retained in
`BaseInterpreter.__slots__`, so ad-hoc attributes (plugins, test spies) still
work on both engines; no slot name is duplicated across the MRO (no shadowing,
no wasted descriptor); subclasses declaring their own `__slots__` construct
fine; `copy.copy` works. Clean.

**Shared init/exit sentinels.** `_INIT_EVENT` / `_EXIT_EVENT` are module-level
`Event` NamedTuples, frozen, carrying the engine provenance mark. Searched for
identity-based logic that could now alias across machines: the receipt map is
keyed by `id(event)`, but `_receipts` is only ever populated by
`send(wait=True)` on a user event, never by the init/exit sentinels, and
`send(wait=True)` already calls `_detach()` when the caller hands in its own
object (#75). No aliasing path found.

**Log gating.** The gated calls in `factory.py`, `resolver.py`,
`base_interpreter.py` and `sync_interpreter.py` are all `logger.info` /
`logger.debug` for human tracing. No plugin hook, no `on_*` callback and no
error path is fed by a log call — the observability contract runs through
`self._plugins` and `last_error`, both untouched. The sync `start()` change
additionally skips building `initial_transition` when `_plugins` is empty and
correctly guards the later `on_transition` emission with
`if initial_transition is not None` — consistent, since the only consumer is
the plugin loop that is empty in that branch.

**Lazy deadline-heap lock (`clock.py`).** The benign-race reasoning in the
comment holds: both racing threads produce an unlocked `Lock`, and no pop can
precede the first completed push. The `if not self._heap: return` fast paths in
`due_before` / `__len__` read a list without the lock, which was already the
pre-existing pattern for `next_due`; a missed concurrent push is picked up on
the next pump. No new race.

**Single-pass parser (`a7badc0`, `3ca5d46`).** The two post-parse tree walks
were folded into the parse and `create_machine` no longer builds a throwaway
`MachineNode` for auto-discovery. The order-dependent checks
(`validate_machine`, root-target rejection, `_alias_logic_names`) still run
after the single build; `p1`/`p2`/`p3` exercise both the discovery and
explicit-logic paths without divergence, and the 3,419-test suite covers the
validation matrix. `context_is_flat` (`models.py:1636`) correctly restricts the
`dict()` shortcut to all-immutable-scalar values, so no aliasing.

**`owns_tasks` entry/exit skip.** `_schedule_state_tasks` / `_cancel_state_tasks`
are now skipped for states with no `after` and no `invoke`. Checked the one
case where a non-declaring state could still own a handle: delayed sends
register under `self.id` (the root), and the root is never exited by a
transition — the comment's justification checks out. `_timer_handles` is keyed
by owner id in both engines consistently.

**`service_pool_size` (#173).** Validated at construction (`ValueError` for
`< 1`), ignored when an executor is supplied, `_owns_service_executor` still
drives shutdown. Correct.

**`after` timer charged mid-step.** `p9` tried to provoke L-1's mechanism
through the timer path rather than `send(priority=True)`: a ticking machine
driven by awaiting actions. No `chain_budget` drops in a 400-event window — the
timer lane empties between steps often enough that the reset clause keeps up.
The *mechanism* is the same as L-1 and a slower service would expose it, but I
could not reproduce a loss here, so it is recorded as negative rather than
folded into L-1.

**Receipt.denied for a crashed guard (#170).** The `_pending_guard_error is
None` conjunct in `base_interpreter.py:4399` correctly stops a crashed guard
from setting `_guard_denied_this_step`. Covered by the round-6 tests and
consistent on both engines; no probe needed beyond reading the path.

---

## Test-surface check

No tests deleted, no `xfail` or `skip` added anywhere in the diff.
`tests/test_round6_findings.py` is new (629 lines) and
`tests/test_perf_hot_path.py` is new (53 lines). The single edit to an existing
test, `test_round4_findings.py::TestPriorityLanePersisted`, replaces a
`_processing = True` freeze with cancelling the loop task — necessary because
#169 now refuses a root snapshot whenever a step is in flight. The assertion it
guards (the recorded `pending_events` types) is unchanged, so this is a fixture
repair, not a weakening.

Full suite at `221ce7c`: **3419 passed, 13 skipped**, 470 s. Every finding above
is outside what the suite exercises.

---

## Adoption impact

L-1 and L-3 are both silent-loss / silent-livelock failures on the async engine
— the engine an order-management path would use — and both sit in code this
round added. L-2 turns a slow dependency at startup into an indefinite hang with
`status == "running"`. Under the reproduce-before-you-count standard all three
are reproduced against `main` at `221ce7c` with independent probes, on config
shapes the library's own documentation recommends.

Recommendation: **do not lift the adoption gate on 0.8.1 as it stands.** L-1,
L-2 and L-3 are each a round-7 regression or an incomplete round-6 fix, not a
pre-existing documented limitation, and L-1 in particular re-opens the exact
failure mode (#77) the chain-budget architecture was designed around.

Round-6 fixes that *do* verify clean: #169 (root refusal, both engines), #170,
#172, #173, and the whole of the perf surface (#165/#176) apart from L-6.
