---
r4: R4-11
title: "Bug: the priority (timer) lane is never persisted — an already-fired `after` event is lost across a snapshot"
labels: [bug, severity/high, area/persistence, area/timers]
severity: High
repro_script: repro/R4-11_priority_lane_not_persisted.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

`Interpreter` maintains three delivery lanes: the inbox (`_event_queue`), the
priority lane (`_priority_queue`, where a *fired* `after` timer is delivered so
that a deadline cannot queue behind thousands of routine external events) and
the internal lane (`_internal_queue`, for `raise`). `_snapshot_pending_events()`
reads **only** the inbox, so `get_persisted_snapshot()["pending_events"]` omits
the priority lane entirely. An `after` timer whose deadline has genuinely
elapsed — the engine has already committed to delivering the event — is
silently dropped if the snapshot is taken before the event is dequeued, with no
log line and no hook. Combined with the fact that timers are not re-armed from
a snapshot, there is **no window, before or after firing, in which an
`after`-driven deadline survives a crash**. For a long-running stateful service
this means a persisted machine can sit forever on a deadline that already
expired.

## Environment

- Commit: `5e07ba8` (`main`, unreleased 0.8.1; `__version__` reports `0.8.0`)
- Python: 3.13.7 (CPython, 64-bit)
- OS: Windows 11 Pro (10.0.26200)
- Install: editable (`pip install -e .`) into a project venv
- Found by our adoption audit (#26), round 4.

## Minimal reproduction

```python
# -*- coding: utf-8 -*-
"""R4-11: the priority (timer) lane is never persisted, so an already-FIRED
`after` event is lost by a snapshot taken before it is dequeued.

`_snapshot_pending_events()` reads ONLY the inbox (`_event_queue`), so
`get_persisted_snapshot()["pending_events"]` omits `_priority_queue` -- the
lane a fired `after` timer is delivered on. A deadline that has genuinely
elapsed, but whose `AfterEvent` has not yet been dequeued, is silently dropped
by a snapshot taken in that window. Combined with timers not being re-armed on
restore, no window exists in which an `after` deadline survives a crash.

Exits 1 while the defect is present, 0 once fixed.
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

CONFIG = {
    "id": "lanes",
    "initial": "waiting",
    "context": {"fired": 0},
    "states": {
        "waiting": {"after": {"1000": {"target": "expired", "actions": ["mark"]}}},
        "expired": {"type": "final"},
    },
}


def mark(interp, ctx, event, action_def):  # noqa: ANN001
    ctx["fired"] += 1


def build():
    return create_machine(CONFIG, logic=MachineLogic(actions={"mark": mark}))


async def main() -> int:
    clock = SimulatedClock()
    i = Interpreter(build(), clock=clock)
    await i.start()
    await asyncio.sleep(0.02)

    # 🧊 Freeze the run loop so a fired timer sits in the priority lane
    #    (simulating a crash in exactly that window).
    i._processing = True
    loop_task, i._event_loop_task = i._event_loop_task, None
    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass

    clock._now += 1.5  # the 1 s deadline has genuinely elapsed
    clock.pump()
    await asyncio.sleep(0.02)

    prio = [e.type for e in i._priority_queue]
    pending = [e.type for e in i.pending_events]
    blob = i.get_snapshot()
    d = json.loads(blob)
    snap_pending = [r["type"] for r in d["pending_events"]]
    snap_deferred = [r["type"] for r in d.get("deferred", [])]
    print("OBSERVED: _priority_queue=%r pending_events=%r" % (prio, pending))
    print("OBSERVED: snapshot pending_events=%r deferred=%r"
          % (snap_pending, snap_deferred))
    i.status = "stopped"

    c2 = SimulatedClock()
    c2._now = clock.now()
    i2 = Interpreter.from_snapshot(blob, build())
    i2.clock = c2
    await i2.start()
    await asyncio.sleep(0.03)
    await c2.increment(60000)
    await asyncio.sleep(0.03)
    restored = sorted(i2.current_state_ids)
    fired = i2.context["fired"]
    print("OBSERVED: restored after +60 s virtual time: states=%r fired=%d"
          % (restored, fired))
    await i2.stop()

    print("EXPECTED: the fired AfterEvent appears in the snapshot, and the "
          "restored machine reaches ['lanes.expired'] with fired=1 (the "
          "uninterrupted reference run's outcome).")
    ok = bool(prio) and prio[0] in snap_pending and fired == 1
    print("RESULT:", "PASS" if ok else
          "FAIL (fired AfterEvent lost across the snapshot)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED: _priority_queue=['after.1000.lanes.waiting'] pending_events=[]
OBSERVED: snapshot pending_events=[] deferred=[]
OBSERVED: restored after +60 s virtual time: states=['lanes.waiting'] fired=0
EXPECTED: the fired AfterEvent appears in the snapshot, and the restored machine reaches ['lanes.expired'] with fired=1 (the uninterrupted reference run's outcome).
RESULT: FAIL (fired AfterEvent lost across the snapshot)
```

The fired `AfterEvent` is demonstrably in `_priority_queue`, yet it is in
neither `pending_events` nor `deferred` in the snapshot, and neither in the
live `pending_events` property. The restored machine stays in `lanes.waiting`
with `fired=0` even after a further 60 s of virtual time — the 1 s deadline
never fires again. An uninterrupted reference run reaches `['lanes.expired']`
with `fired=1`.

## Expected behaviour

The library's documented persistence contract is that an **accepted** event
survives a snapshot/restore round trip. `drain_pending()` states it removes and
returns "every accepted-but-unprocessed event […] Intended for shutdown paths
that must persist accepted work durably before the process exits"
(`interpreter.py:1045-1050`) — a fired `AfterEvent` sitting in the priority
lane is exactly accepted-but-unprocessed work, and it is not returned there
either.

The exclusion of the *internal* lane is deliberate and documented in the code —
`self._internal_queue.clear()  # mid-macrostep state; never persisted`
(`interpreter.py:995`) — which is defensible, since internal events only exist
within a macrostep. The priority lane carries a fully external, already-elapsed
deadline across macrostep boundaries, has no such rationale, and has no
documentation of the omission anywhere.

SCXML §3.12.1/§4 treats a `<send>` whose delay has elapsed as delivered to the
external event queue; XState v5's persisted snapshot (`actor.getPersistedSnapshot()`,
https://stately.ai/docs/persistence) captures the actor's queued events so that
restoring resumes from an equivalent point. Either the event is persisted and
replayed, or the timer is re-armed on restore; silently dropping it is not a
valid third option.

## Root cause analysis

`src/xstate_statemachine/interpreter.py:1017-1026`:

```python
def _snapshot_pending_events(self) -> List[AnyEvent]:
    q = self._event_queue
    if isinstance(q, _PreStartQueue):
        return q.peek()
    return list(getattr(q, "_queue", ()))
```

It reads only `self._event_queue`. `self._priority_queue` is declared at
`interpreter.py:219` (`deque[AnyEvent]`), written by `_deliver_priority`
(`interpreter.py:1703`, `self._priority_queue.append(event)`) and drained ahead
of the inbox in `_next_event` (`interpreter.py:1677-1678`,
`return self._priority_queue.popleft(), False`). A fired `after` timer is
delivered through that path, by design, so the deadline does not queue behind
routine traffic (the #48 priority-lane work).

There is no read of `_priority_queue` anywhere in the persistence path —
`get_persisted_snapshot()` / `get_snapshot()` build `pending_events` solely from
`_snapshot_pending_events()`, and `deferred` from the deferred buffer. On the
restore side `_enqueue_restored()` (`interpreter.py:1029`) only ever writes to
the inbox, so nothing could round-trip even if it were captured. `stop()` calls
`self._priority_queue.clear()` (`interpreter.py:994`) immediately before the
internal lane's documented clear — dropping the lane on a clean shutdown too.

The omission dates from the introduction of the priority lane (#48/#39): the
lane was added to `_next_event` and `stop()` but never to the snapshot
functions, which predate it and were written when the inbox was the only
external lane.

## Impact

**General users.** Every `after`-driven timeout in a persisted machine is
crash-unsafe. There are two loss windows and the library covers neither:
before firing the timer is not re-armed on restore, and after firing the event
is not in the snapshot. The failure is completely silent — no hook, no log, no
count. `queue_depth` and `pending_events` both report the event does not exist,
so an operator validating "did my snapshot capture everything in flight?"
against the public API gets a confident wrong answer. Restored machines park
forever on elapsed deadlines while reporting `status="running"`, which health
checks read as healthy.

**Concrete order-management scenario.** An order machine arms
`after: {30000: "expire"}` as a good-till-time / no-fill cancel deadline. The
30 s elapses, the `AfterEvent` lands in the priority lane, and the process is
restarted (deploy, OOM, failover) in the millisecond window before the run loop
dequeues it. The order is rehydrated from its snapshot into `waiting` with the
deadline gone. It never expires and is never cancelled: a live, unhedged order
sits at the venue indefinitely, and the service's own view says the timer is
still pending. The operator's only recourse is an out-of-band reaper, which is
exactly the responsibility they delegated to the state machine.

## Proposed fix

**Design.** Persist the priority lane alongside the inbox and the deferred
buffer, and restore it into the same lane.

1. In `_snapshot_pending_events()` (or a new `_snapshot_priority_events()`),
   capture `list(self._priority_queue)`.
2. Write it to a **new**, separately-keyed snapshot field, e.g.
   `"priority_events": [...]`, using the existing `persist_event` encoding.
   Keeping it separate from `pending_events` preserves lane ordering on
   restore: priority events must go back to the head, ahead of inbox events,
   not be merged into the inbox.
3. On restore (`from_snapshot` / `_restore_state`), rebuild `_priority_queue`
   from `priority_events` via `restore_event`, before the inbox is repopulated
   by `_enqueue_restored`.
4. Treat a missing `"priority_events"` key as `[]` so v1/v2 snapshots upcast
   unchanged.
5. Include the lane in `drain_pending()` (it is "accepted-but-unprocessed" by
   that method's own definition) and stop clearing it in `stop()` before any
   final snapshot is taken.

This sits in `src/xstate_statemachine/interpreter.py` next to
`_snapshot_pending_events` (≈ line 1017) and in the snapshot assembly /
`base_interpreter.py` restore path.

**Compatibility.** Additive: an old snapshot restores as today (empty priority
lane); a new snapshot read by an older version ignores the unknown key. No
public API change. The only behaviour change is that a previously-lost event is
now delivered — which can only move a restored machine toward the outcome of
the uninterrupted reference run.

**Note on interaction with lateness telemetry.** A restored `AfterEvent`
currently loses its `scheduled_for` / `fired_at` / `lateness_ms` (they are
reconstructed as `0.0`, `events.py:292-302` — filed separately as `R4-23`).
That bug is presently *masked* by this one: fixing R4-11 alone turns a silently
dropped event into a delivered event that affirmatively claims it was on time.
The two should land together, with unknown timings restored as `None` rather
than `0.0`.

**Alternatives considered.**
1. *Re-arm timers on restore instead of persisting the fired event.* Needed
   anyway for the not-yet-fired window, but it does not fix this one: on
   restore the deadline is already in the past, and re-arming would either fire
   immediately (losing the original `scheduled_for`) or not at all. Persisting
   the fired event is the faithful option; both fixes are wanted.
2. *Merge priority events into `pending_events`.* Simplest, but loses lane
   priority on restore — the deadline would queue behind restored routine
   traffic, defeating the reason the lane exists (#48).
3. *Documentation only.* If persisting is rejected, at minimum document the
   omission in `_snapshot_pending_events` and in the persistence guide, exactly
   as the internal lane's omission is documented at `interpreter.py:995`, and
   have `pending_events` / `drain_pending()` say they exclude it. This leaves
   a real data-loss hole and is a strictly worse outcome.

## Acceptance criteria

- [ ] `_priority_queue` is captured in the snapshot and restored into the
      priority lane, ahead of restored inbox events.
- [ ] `repro/R4-11_priority_lane_not_persisted.py` exits `0`.
- [ ] `tests/test_persistence_lanes.py::test_fired_after_event_survives_snapshot`
      — freeze the run loop, fire an `after` on a `SimulatedClock`, snapshot,
      restore: the restored machine reaches the target state with the action
      having run exactly once.
- [ ] `tests/test_persistence_lanes.py::test_priority_lane_restored_ahead_of_inbox`
      — a snapshot holding both a priority event and two inbox events restores
      with the priority event processed first.
- [ ] `tests/test_persistence_lanes.py::test_v1_v2_snapshot_without_priority_events_upcasts`
      — a snapshot lacking the new key restores with an empty priority lane and
      no error.
- [ ] `tests/test_persistence_lanes.py::test_drain_pending_includes_priority_lane`
- [ ] `tests/test_persistence_lanes.py::test_after_event_not_delivered_twice_after_restore`
      — no duplicate delivery when the timer is also re-armed.
- [ ] The persistence documentation states which lanes are persisted and which
      are not, and why.

## Related

- Register row `R4-11` (filed High, **CONFIRMED** at filed severity). Source id
  `D-persistence-6`; unmerged 1:1.
- Evidence: `battle-5e07ba8/persistence/d6_priority_lane.py`,
  `battle-5e07ba8/persistence.md` / `.triage.md`; final-verification runs
  `probes/main-5e07ba8-final` (`fv3_r406_r407_r411.py`, pre-`start()` variant:
  a `priority=True` send is absent from the snapshot, from `pending_events` and
  from `drain_pending()` while `queue_depth` counts only the non-priority
  events).
- **`R4-23`** — `AfterEvent` lateness telemetry (`scheduled_for`/`fired_at`/
  `lateness_ms`) resets to `0.0` across a snapshot round trip
  (`events.py:292-302`). Currently masked by this issue; should be fixed
  together.
- **`R4-10`** — timers are not re-armed on restore (the *not-yet-fired*
  window). Together with this issue, no window exists in which an `after`
  deadline survives a crash.
- Prior issues: **#48** (priority lane for fired timers), **#39**
  (`priority=` sends), **#47** (the inbox).
- Meta: our adoption audit **#26**.

## Verification

- Date: 2026-09-18
- Python: 3.13.7 (`.venv-main`)
- Commit: `5e07ba8`
- `repro/R4-11_priority_lane_not_persisted.py` re-run in a fresh process: exit
  code `1`, output matches the Observed section verbatim (`_priority_queue`
  holds the fired `after.1000.lanes.waiting` event; snapshot `pending_events`
  and `deferred` are both empty; the restored machine stays in
  `lanes.waiting` with `fired=0` even after +60 s of virtual time).
- Root cause confirmed by direct inspection of
  `src/xstate_statemachine/interpreter.py`: `_snapshot_pending_events`
  (≈ line 1017) reads only `self._event_queue`; `self._priority_queue` is
  declared at line 219, appended to by `_deliver_priority` (≈ line 1703,
  matches cited region) and drained ahead of the inbox in `_next_event`
  (≈ lines 1677-1678, matches). No read of `_priority_queue` exists anywhere
  in the snapshot-building path, and `stop()` clears it (line 994) before any
  final snapshot could capture it. Line numbers match the citations closely.
- XState v5 claim checked via `https://stately.ai/docs/persistence`
  (event-sourcing / inspection API section): a persisted/replayed actor is
  expected to preserve queued-but-undelivered events; the SCXML analogy in
  the issue (elapsed `<send>` delay ⇒ event delivered to the external queue)
  is standard SCXML semantics (§3.12.1/§4) and is not contradicted by
  anything in the fetched docs.
- No self-containedness issues; no project name/label leak found.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --search "priority queue persist"` surfaces only issue **#26** (the meta
  tracking issue) and **#48** (priority lane for fired timers, a prerequisite
  this issue builds on, not a duplicate) and **#47** (persisting the inbox,
  which this issue explicitly says omits the priority lane). No duplicate
  found.
