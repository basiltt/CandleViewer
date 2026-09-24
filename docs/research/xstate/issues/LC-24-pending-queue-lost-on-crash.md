---
lc: LC-24
title: "Feature: pending events in the interpreter queue are lost on stop and invisible in the snapshot"
labels: [enhancement, severity/high, area/persistence, candleviewer]
severity: High
blocks_adoption: false
repro_script: repro/LC-24_pending_queue_lost_on_crash.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

`Interpreter.send()` puts the event on an in-memory `asyncio.Queue` (`interpreter.py:375`) and returns. `get_persisted_snapshot()` records `status`, `context`, `state_ids`, `configuration`, `output`, `error`, `history`, `actors` and `system` — but not that queue. `stop()` cancels the run-loop task (`interpreter.py:313-315`) and whatever is still queued is discarded. There is also no public accessor or drain API, so a shutdown path cannot flush the queue to durable storage even if it wants to.

Fifty events sent and then stopped leave zero trace: the snapshot shows `n=0`, the post-stop context shows `n=0`, and nothing in the snapshot records that fifty events ever existed. Because `send()` costs ~2.3 µs while a transition costs ~33 µs, the queue is *where events normally live* under any burst — it is the busiest and most volatile structure in the interpreter, and it is the only one that is not persisted.

## Environment

- Library: xstate-statemachine 0.7.0, commit `42612cf` (local clone, `pip install -e .`)
- Python: 3.13.7
- OS: Windows-11-10.0.26200-SP0
- Install method: editable install into a dedicated venv

## Current workaround and why it is insufficient

The application must own a durable inbox in front of the interpreter and only acknowledge the upstream message after the transition has been *observed*:

```python
class DurableInbox:
    """Every event is journalled before it reaches the interpreter."""

    def __init__(self, interp, journal):
        self._interp, self._journal = interp, journal

    async def deliver(self, event: dict) -> None:
        seq = await self._journal.append(event)        # fsync
        await self._interp.send(event)
        # We cannot await the transition: send() is fire-and-forget (LC-42).
        # So we poll a context watermark the machine itself must maintain.
        while self._interp.context.get("last_seq", -1) < seq:
            await asyncio.sleep(0.001)
        await self._journal.commit(seq)

    async def recover(self) -> None:
        for event in await self._journal.uncommitted():
            await self._interp.send(event)
```

Why this is not enough:

1. **It requires the machine to cooperate.** `last_seq` must be assigned by an action on *every* transition of *every* machine, including transitions that exist only to be ignored. Miss one handler and the inbox blocks forever on an event the machine legitimately dropped — and because unhandled events are discarded with no signal at all (reported separately as LC-03), "the machine ignored it" and "the machine has not got to it yet" are indistinguishable from outside.
2. **It serialises the machine.** Awaiting the watermark before delivering the next event reduces the interpreter to one in-flight event, discarding the queue's entire purpose and with it the 2.3 µs `send()` — throughput collapses to the 33 µs transition cost plus a polling interval.
3. **The poll loop is a busy-wait on an unbounded deadline.** There is no completion signal to await (`send()` returns once the event is queued and cannot report that it was applied — reported separately as LC-42), so the only options are polling latency or a condition variable the machine must also be modified to set.
4. **Recovery double-delivers.** Uncommitted journal entries are replayed on boot, but the library gives no way to know which of them the dead process had already applied — the snapshot's context reflects some prefix of them and nothing says which. Every handler must therefore be made idempotent by hand, keyed on an id the application invents.
5. **It does not compose with child actors.** Each spawned actor has its own queue with the same hazard, and the application has no handle on those queues at all.

An application-level journal is the right architecture for *durability of intent*; it is not a substitute for the interpreter being able to say what it has accepted but not yet processed.

## Reproduction of the current behaviour

```python
"""LC-24 repro: queued events are lost on stop and invisible in the snapshot.

`Interpreter.send()` puts the event on an in-memory `asyncio.Queue`
(`interpreter.py:375`). `get_persisted_snapshot()` records status, context,
configuration, history, output and actors — but NOT that queue. `stop()`
cancels the run loop and discards whatever is still queued. There is also no
public API to drain it, so no shutdown path can flush events durably.

Exit code 1 on failure.
"""

from __future__ import annotations

import asyncio
import json
import logging

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

N = 50

CFG = {
    "id": "counter",
    "initial": "up",
    "context": {"n": 0},
    "states": {"up": {"on": {"TICK": {"actions": ["bump"]}}}},
}


def bump(i, c, e, a):  # noqa: ANN001
    c["n"] += 1


async def main() -> int:
    ok = True
    machine = create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))
    i = await Interpreter(machine).start()

    # Enqueue a burst without yielding to the run loop, then crash/stop.
    for _ in range(N):
        await i.send("TICK")

    snap = json.loads(i.get_snapshot())
    print(f"OBSERVED snapshot keys        = {sorted(snap)}")
    print("EXPECTED snapshot keys        = include a pending-event field")
    queue_fields = [k for k in snap if "queue" in k or "pending_event" in k]
    if not queue_fields:
        ok = False

    print(f"OBSERVED snapshot context.n   = {snap['context']['n']}")
    print(f"EXPECTED snapshot context.n   = {N} (or n pending events recorded)")

    has_drain = any(
        hasattr(i, name) for name in ("drain_pending", "pending_events")
    )
    print(f"OBSERVED drain/pending API    = {has_drain}")
    print("EXPECTED drain/pending API    = True")
    if not has_drain:
        ok = False

    await i.stop()
    processed = i.context["n"]
    lost = N - processed
    print(f"OBSERVED processed after stop = {processed}")
    print(f"OBSERVED events lost          = {lost}")
    print("EXPECTED events lost          = 0 (drained, or recoverable from snapshot)")
    if lost:
        ok = False

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED snapshot keys        = ['actors', 'configuration', 'context', 'error', 'history', 'output', 'state_ids', 'status', 'system']
EXPECTED snapshot keys        = include a pending-event field
OBSERVED snapshot context.n   = 0
EXPECTED snapshot context.n   = 50 (or n pending events recorded)
OBSERVED drain/pending API    = False
EXPECTED drain/pending API    = True
OBSERVED processed after stop = 0
OBSERVED events lost          = 50
EXPECTED events lost          = 0 (drained, or recoverable from snapshot)
RESULT: FAIL
```

Exit code `1`. Fifty accepted events, zero processed, zero recorded, zero recoverable.

## Expected behaviour

This is filed as an enhancement, not a conformance bug, and it is worth being precise about why.

XState's persistence contract is stated as: "[Actors](https://stately.ai/docs/actors) can persist their internal state and restore it later. **Persistence** refers to storing the state of an actor in persistent storage... **Restoration** refers to restoring the state of an actor from persistent storage" (<https://stately.ai/docs/persistence>), and persistence is deep — "all invoked & spawned actors will be persisted and restored recursively." XState does **not** persist its in-memory mailbox either, so this library is not diverging from XState here. What XState *does* persist that is analogous is its scheduler: pending delayed sends live in `system._snapshot._scheduledEvents` (`packages/core/src/system.ts`), i.e. accepted-but-not-yet-delivered work is explicitly part of the persisted system snapshot. And XState offers event sourcing via the inspection API as the documented alternative for exactly this durability problem — "An alternative to persisting state is **event sourcing**, which is a way of restoring the state of an actor by replaying the events that led to that state" — which is only implementable because XState gives you a hook that sees every event entering the actor. This library offers neither: no scheduled/pending events in the snapshot, and no inspection hook to build event sourcing on.

The SCXML model the library follows treats the external event queue as a first-class part of the interpreter's runtime state, not an implementation detail: the `interpret` algorithm in <https://www.w3.org/TR/scxml/> creates `externalQueue = new BlockingQueue()` alongside `configuration` and `historyValue`, and the Informal Semantics appendix defines an external event as "An SCXML event appearing in the external event queue." A snapshot describing `configuration` and the datamodel but not the queue is describing part of the interpreter state.

At minimum, two things are reasonable to expect and neither exists today:

1. a way to *see* what is pending (so a shutdown path can persist it), and
2. a graceful stop that processes or hands back what was accepted, rather than discarding it silently.

Point 1 is the one that matters most. Persisting the queue is arguably the embedder's job — but today the embedder *cannot do it either*, because the queue is private with no accessor and `stop()` discards it without a word.

## Root cause analysis

`src/xstate_statemachine/interpreter.py`:

- `:129` — `self._event_queue: asyncio.Queue[...]` is created per interpreter, private, with no accessor.
- `:375` — `await self._event_queue.put(event_obj)` is the entirety of `send()`. The event is accepted; the caller's `await` returns; nothing durable has happened. (`:400`, `send_events`, is the batch equivalent.)
- `:427` — `event = await self._event_queue.get()` in `_run_event_loop` is the only consumer.
- `:313-315` — `stop()` does `self._event_loop_task.cancel()`. Cancellation interrupts the `await ... get()` (or the in-flight transition), and the queue object is then dropped with the interpreter. Nothing inspects `qsize()`, nothing drains, nothing warns.

`src/xstate_statemachine/base_interpreter.py`:

- `:690-745` — `get_persisted_snapshot()` returns a dict literal of exactly nine keys. The queue is not among them, and the docstring's claim that recording actors recursively "makes a snapshot a faithful representation of the machine" is exactly the standard this omission fails.

`SyncInterpreter` has the analogous `Deque` at `sync_interpreter.py:132`; it drains synchronously inside `send()` so the window is much smaller, but `:361` `self._event_queue.clear()` discards outright on the error path.

## Impact

**General users.** Every user of this library who persists snapshots believes, reasonably, that a snapshot plus the machine definition reconstitutes the actor. It does not: it reconstitutes the actor minus its inbox, with no indication that an inbox existed. The window is not exotic — it is every burst. At 2.3 µs to enqueue and 33 µs to process, a producer that is faster than the machine builds a queue by construction, and that queue is the largest during exactly the traffic spikes most likely to precede an OOM kill, a deploy, or a supervisor restart. Graceful shutdown makes it *worse*, not better: an orderly `stop()` discards the queue just as thoroughly as a `SIGKILL`, so the careful operator and the careless one lose the same events.

**CandleViewer (trading OMS).** CandleViewer is a trading order-management system we are evaluating this library for. Its order machine receives `FILLED`, `PARTIAL_FILL` and `CANCELED` from the exchange WebSocket feed. These arrive in bursts — a 10-lot order sweeping five price levels produces five `PARTIAL_FILL` events within a millisecond — and the WS reader calls `send()` for each, which is why the reader can keep up. Our latency budget for the order path is 165 ms p95; that 165 ms is 165 ms of fills sitting in exactly this volatile queue. If the process is killed in that window — a deploy, an OOM, a k8s eviction — the fills are gone: the position exists on the exchange, the restored machine believes the order is still `submitting`, and the reconciliation sweep reports a phantom position with no event trail explaining it. Worse, the WS client has already acknowledged those frames to the exchange (there is nothing to wait for — `send()` returns immediately and cannot report completion, see LC-42), so they will never be redelivered. This is the direct motivation for our standing rule *never acknowledge a bus message before the transition is observed* — a rule that exists solely to work around this gap, and which costs us the throughput described above.

## Proposed API

Two additions, independently useful, neither breaking:

**1. `pending_events` / `drain_pending()` on the interpreter.**

```python
@property
def pending_events(self) -> tuple[Event, ...]:
    """Events accepted by `send()` but not yet processed, in order."""

async def drain_pending(self) -> list[Event]:
    """Removes and returns all pending events without processing them.

    Intended for shutdown paths that must persist accepted-but-unprocessed
    work durably before the process exits.
    """
```

**2. A `pending_events` field in the persisted snapshot**, restored by `from_snapshot`.

```python
# get_persisted_snapshot()
"pending_events": [
    {"type": e.type, "payload": getattr(e, "payload", None)}
    for e in self._snapshot_pending_events()
],
```

`from_snapshot` re-enqueues them, so a restored interpreter resumes with its inbox intact.

**3. `stop(drain: bool = False)`** — when `True`, process the remaining queue before tearing down, bounded by an optional timeout.

### Usage example

```python
import asyncio, json
from xstate_statemachine import Interpreter, create_machine

interp = await Interpreter(order_machine).start()

# --- WS reader: unchanged, still fire-and-forget and still fast ---
await interp.send("PARTIAL_FILL", qty=2, px=101.5)

# --- shutdown handler: nothing accepted is lost ---
async def on_sigterm() -> None:
    # Option A: finish the work we accepted.
    await interp.stop(drain=True)

    # Option B: hand it back and persist it with the snapshot.
    snapshot = interp.get_snapshot()          # now includes pending_events
    await storage.put("order:A-1", snapshot)
    await interp.stop()

# --- boot: the inbox comes back with the machine ---
restored = Interpreter.from_snapshot(await storage.get("order:A-1"), order_machine)
assert [e.type for e in restored.pending_events] == ["PARTIAL_FILL"]
await restored.start()   # the queued fill is processed normally
```

**Backwards compatibility.** `pending_events` in the snapshot is additive; `from_snapshot` reads it with `snapshot.get("pending_events") or []`, matching how `output`, `history`, `actors` and `system` already tolerate absence, so old snapshots restore exactly as today. `stop()` keeps its current semantics by default (`drain=False`). The new accessors are pure additions. Serialisation of event payloads follows the existing `json.dumps(..., default=str)` convention, and payloads that cannot round-trip degrade to a string exactly as context values already do — documented, not silent.

**Design note.** If persisting the queue is judged out of scope (a defensible position — a mailbox is arguably the embedder's problem), then `pending_events` and `drain_pending()` alone would close the gap, because they let the application own durability *correctly* instead of guessing. What is not defensible is the current state: the queue is unobservable, so no correct shutdown path can be written at any level of the stack. At the very least, `stop()` should log a warning when it discards a non-empty queue.

## Acceptance criteria

- [ ] `pending_events` property returns accepted-but-unprocessed events in FIFO order, for both `Interpreter` and `SyncInterpreter`.
- [ ] `drain_pending()` removes and returns them; a subsequent `pending_events` is empty; drained events are not processed.
- [ ] `get_persisted_snapshot()` includes a `pending_events` list; `from_snapshot` re-enqueues it; snapshots without the field restore unchanged.
- [ ] `stop(drain=True)` processes the queue to empty before teardown; `stop()` unchanged by default but logs a warning when discarding a non-empty queue.
- [ ] Child actors' pending events are captured recursively, consistent with `_persist_actors`.
- [ ] `repro/LC-24_pending_queue_lost_on_crash.py` exits `0`.
- [ ] Tests added under `tests/`:
  - `tests/test_pending_queue.py::test_pending_events_reports_unprocessed_in_order`
  - `tests/test_pending_queue.py::test_drain_pending_returns_and_empties_queue`
  - `tests/test_pending_queue.py::test_snapshot_round_trip_preserves_pending_events`
  - `tests/test_pending_queue.py::test_stop_with_drain_processes_remaining_events`
  - `tests/test_pending_queue.py::test_stop_without_drain_warns_when_queue_non_empty`
  - `tests/test_pending_queue.py::test_old_snapshot_without_pending_events_restores`
  - `tests/test_pending_queue.py::test_child_actor_pending_events_round_trip`
- [ ] Docs: the persistence page states explicitly whether the mailbox is part of a snapshot, and shows the shutdown pattern above.

## Related

These are sibling reports from the same evaluation; each is self-contained and can be read independently.

- **LC-42** — `send()` cannot answer synchronously; together with this issue there is no way to know an event was applied.
- **LC-41** — the same queue, unbounded and unobservable; `pending_events` would also give backpressure something to measure.
- **LC-43** — a third failure mode of the same structure (cross-thread `send()` silently lost).
- **LC-21**, **LC-22**, **LC-19**, **LC-20** — the other respects in which a snapshot is not a faithful resume.

## Verification

- Verified: 2026-09-15
- Python: 3.13.7, Windows-11-10.0.26200-SP0
- Library commit: `42612cf`, version 0.7.0 (editable install)
- Command: `python repro/LC-24_pending_queue_lost_on_crash.py`
- Exit code: `1` (fails against the library as shipped); Observed block matches real output (one `EXPECTED snapshot keys` line was missing from the transcript and has been restored).
- Root-cause lines re-checked against source: `interpreter.py:129` (`self._event_queue: asyncio.Queue[...]`), `:375` (`await self._event_queue.put(event_obj)` in `send`), `:400` (same in `send_events`), `:406`/`:427` (`_run_event_loop`, `await self._event_queue.get()`), `:314` (`self._event_loop_task.cancel()` in `stop`), `base_interpreter.py:690-745` (`get_persisted_snapshot`, nine-key dict literal), `sync_interpreter.py:132` (`Deque`) and `:361` (`self._event_queue.clear()`). All confirmed. Note `stop()`'s cancel is at `:314` (the draft's `:313-315` range is fine); there is a second `_event_loop_task.cancel()` at `:270`.
- Expected-behaviour section **rewritten**. The draft quoted a sentence ("Persisted state is a snapshot of the actor's state that can be used to restore the actor's state later") that does not appear on the persistence page, and cited "SCXML §3.13" for the external-queue definition, which is the wrong section. More importantly the draft implied XState persists its mailbox; it does not. The section now states plainly that this is an enhancement rather than an XState-conformance gap, and grounds the argument in XState's `_scheduledEvents` persistence and inspection-API event sourcing, plus the actual SCXML `interpret` algorithm and Informal Semantics definitions. Labels/severity unchanged — the issue is already filed as `enhancement`.
- Duplicate check: `gh issue list --state all` on the upstream repo returns one issue (#17, camelCase action auto-discovery, closed). Not a duplicate.
