---
lc: LC-38
title: "Bug: `SyncInterpreter` is not single-threaded — `after` timers run on background threads and mutate context with no locks"
labels: [bug, severity/high, area/sync-interpreter, candleviewer]
severity: High
blocks_adoption: true
repro_script: repro/LC-38_sync-interpreter-timer-threads.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

`SyncInterpreter` is presented as the synchronous, no-asyncio engine — the natural reading being that everything happens on the caller's thread, inside `send()`. It does not. Every `after` transition starts a **daemon OS thread** (`sync_interpreter.py:1323`), and when the deadline elapses that thread calls `self.send(...)`, running a complete macrostep — exit actions, guards, transition actions, entry actions and `context` mutation — on the timer thread, concurrently with whatever the owning thread is doing. `_deliver` (`:1028`) and `_spawn_actor` (`:1092`) start threads the same way.

There is **no lock of any kind in the codebase**: `grep -rn "asyncio.Lock\|threading.Lock\|threading.RLock" src/` returns nothing. The only concurrency control is `_is_processing`, a plain check-then-set boolean (`sync_interpreter.py:337-340`) — a TOCTOU race, not a mutex, and in any case its effect under contention is to make a timer's `send()` *return silently without processing*, i.e. to drop the timer event rather than to serialise it.

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, installed with `pip install -e .`
- Python: 3.13.7 (also confirmed on 3.12.3)
- OS: Windows 11 (x64)

## Minimal reproduction

```python
"""LC-38 repro: `SyncInterpreter` is not single-threaded.

`sync_interpreter.py` starts one *daemon OS thread per `after` timer*
(`_after_timer` -> `threading.Thread(target=timer_thread, ...)`).
When the deadline elapses that thread calls `self.send(...)`, which appends to
`self._event_queue` and runs the full macrostep -- entry/exit actions, guards
and `context` mutation -- on the timer thread, concurrently with whatever the
owning thread is doing. There is no `threading.Lock` anywhere in the
codebase, and `_is_processing` is a plain check-then-set boolean
(`sync_interpreter.py:337-340`), which is a textbook TOCTOU race, not a
mutex.

This script demonstrates both halves:

  1. The state advances and context is mutated while the main thread merely
     `time.sleep()`s -- no `send()`, no pump -- and the mutating thread is
     NOT `MainThread`.
  2. A main-thread `send()` loop racing the timers loses increments: the
     counter ends below the number of writes actually performed, because
     `context["n"] += 1` from two threads is not atomic across the
     read-modify-write the interpreter performs.

Exit code 1 if either non-single-threaded behaviour is observed.
"""

from __future__ import annotations

import logging
import sys
import threading
import time

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

logging.disable(logging.CRITICAL)

DELAY_MS = 150

CFG = {
    "id": "order",
    "initial": "submitting",
    "context": {"n": 0, "threads": []},
    "states": {
        "submitting": {
            "after": {DELAY_MS: {"target": "timed_out", "actions": ["bump"]}},
            "on": {"TICK": {"actions": ["bump"]}},
        },
        "timed_out": {"type": "final"},
    },
}

writes = 0
writes_lock = threading.Lock()


def bump(interpreter, context, event, action_def):  # noqa: ANN001
    global writes
    name = threading.current_thread().name
    if name not in context["threads"]:
        context["threads"].append(name)
    with writes_lock:
        writes += 1
    # Widen the read-modify-write window the interpreter offers to any
    # concurrent thread. No lock protects `context` in the library.
    n = context["n"]
    time.sleep(0.002)
    context["n"] = n + 1


def build() -> SyncInterpreter:
    m = create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))
    return SyncInterpreter(m).start()


def main() -> int:
    # --- 1. advance with no event pump at all -------------------------------
    sm = build()
    before = sm.current_state_ids.copy()
    main_name = threading.current_thread().name
    time.sleep(DELAY_MS / 1000 + 0.3)
    after = sm.current_state_ids.copy()
    off_main = [t for t in sm.context["threads"] if t != main_name]

    print(f"OBSERVED: state before sleep = {sorted(before)}")
    print(f"OBSERVED: state after pure time.sleep() = {sorted(after)}")
    print(f"OBSERVED: threads that mutated context = {sm.context['threads']}")
    print(f"OBSERVED: non-main mutating threads = {off_main}")
    print(
        "EXPECTED: a synchronous interpreter never advances without a "
        "send(); all context mutation happens on the calling thread."
    )
    advanced_off_thread = bool(off_main)

    # --- 2. lost update race -------------------------------------------------
    global writes
    writes = 0
    sm2 = build()
    deadline = time.perf_counter() + (DELAY_MS / 1000 + 0.3)
    while time.perf_counter() < deadline:
        try:
            sm2.send("TICK")
        except Exception:  # interpreter reached final state
            break
    time.sleep(0.2)
    counted = sm2.context["n"]
    print(f"OBSERVED: bump() executed {writes} times, context['n'] = {counted}")
    print("EXPECTED: context['n'] == number of bump() executions.")
    lost_update = counted != writes

    return 0 if not (advanced_off_thread or lost_update) else 1


if __name__ == "__main__":
    sys.exit(main())
```

## Observed behaviour

```
OBSERVED: state before sleep = ['order.submitting']
OBSERVED: state after pure time.sleep() = ['order.timed_out']
OBSERVED: threads that mutated context = ['after-order.submitting::270610cf-5884-4607-84f0-3ff0f7ff8b5c']
OBSERVED: non-main mutating threads = ['after-order.submitting::270610cf-5884-4607-84f0-3ff0f7ff8b5c']
EXPECTED: a synchronous interpreter never advances without a send(); all context mutation happens on the calling thread.
OBSERVED: bump() executed 60 times, context['n'] = 60
EXPECTED: context['n'] == number of bump() executions.
```

Exit code `1`.

Part 1 confirms the claim outright: the main thread never called `send()`, yet the machine moved `order.submitting → order.timed_out` and the *only* thread that ever touched `context` was `after-order.submitting::…` — a library-owned daemon thread the user never created and cannot see. This half reproduces on every run; the UUID in the thread name and the exact `bump()` count vary run to run.

Part 2 (the lost-update half) did **not** trigger in this run: the counts agreed. This is expected to be intermittent, not absent — a single `after` timer fires once, so there is exactly one window in which the timer thread and the main thread can interleave, and `_is_processing` closes most of that window by making one of the two `send()` calls return without processing (which is itself a dropped-event bug, see *Impact*). The absence of a lost update in one run is not evidence of safety: the data race is structural (no lock guards `context`, `_event_queue`, `_active_state_nodes` or `_is_processing`), and any machine with several concurrent `after`/`_deliver`/actor threads widens the window arbitrarily. Treat part 1 as the reproducer — it is what the exit code rests on — and part 2 as a stress probe.

## Expected behaviour

XState v5's core interpreter is single-threaded by construction — JavaScript has no user threads, and an actor processes one event at a time from its mailbox. The whole point of a *synchronous* interpreter in a Python port is to offer that same guarantee for callers who do not want an event loop: state changes happen only inside a `send()` call, on the calling thread. See https://stately.ai/docs/actors ("Actors… have their own internal state and can only communicate via messages… An actor processes messages one at a time") and https://stately.ai/docs/transitions#delayed-transitions-after, where delayed transitions are scheduled through the actor's injectable `clock` and delivered into the same mailbox, never onto a parallel execution context.

Concretely, one of the following must hold:

1. `after` in a `SyncInterpreter` is scheduled but only *delivered* when the caller pumps the machine (an explicit `tick()` / next `send()`), so everything still runs on the caller's thread; **or**
2. the threaded implementation is kept, but `context`, `_event_queue`, `_active_state_nodes` and the processing flag are guarded by an `RLock` and the threading model is documented as part of the public contract; **or**
3. `after` is rejected in a `SyncInterpreter` with the same loud early `NotSupportedError` already used for `async def` services.

## Root cause analysis

`src/xstate_statemachine/sync_interpreter.py`:

- `:1323-1327` — `_after_timer` ends with
  ```python
  thread = threading.Thread(target=timer_thread, daemon=True, name=f"after-{unique_key}")
  self._after_threads[unique_key] = thread
  thread.start()
  ```
  One daemon OS thread per `after` deadline, per state entry.
- `:1296-1306` — inside `timer_thread`, once the deadline passes: `if self.status == "running" and any(s.id == owner_id for s in self._active_state_nodes): self.send(event)`. Both the guard read (`_active_state_nodes`) and the `send()` happen off the owner's thread and unsynchronised.
- `:311-313` — `send()` appends to `self._event_queue` (a plain `collections.deque`, `:132`) and calls `_process_event_queue()` with no lock. `deque.append` is individually atomic, but the append-then-drain sequence is not, which is where the race lives.
- `:337-340` —
  ```python
  if self._is_processing:
      return
  self._is_processing = True
  ```
  Check-then-set on a plain `bool`. Two threads can both observe `False`; and in the common case the *loser* silently discards its event, because `send()` has already appended to the queue but the early `return` leaves it undrained until the next unrelated `send()`.
- `:1087-1090` — `_deliver` starts another daemon thread (`send-<type>`).
- `:1185-1187` — `_spawn_actor` starts a third (`actor-<id>`).
- `grep -rn "asyncio.Lock\|threading.Lock\|threading.RLock" src/xstate_statemachine/` → **no matches**. The only `threading.Lock` in the reproduction above is one the *test* introduced.

The `_after_threads` / `_after_events` dictionaries are also mutated from both the scheduling thread and the timer thread (`:1320-1322`, `finally:` block) without synchronisation.

## Impact

**General users.** The engine advertised as the simple, no-asyncio option is in fact the one with the least-defended concurrency: it hands user code (actions, guards) to threads the user did not create, at times the user did not choose, against shared mutable `context` with no memory model and no lock. Any user action that does a read-modify-write on `context`, appends to a list, or touches a non-thread-safe external resource (a DB session, a file handle, a `requests.Session`) is a latent race. Worse, the failure mode is usually *silent*: `_is_processing` makes the contended path drop the timer event instead of corrupting, so the machine simply misses a timeout.

Users also cannot reason about their own locking, because the threading model is undocumented — nothing in the `SyncInterpreter` docstring says "your callbacks may run on a background thread".

**CandleViewer trading OMS.** The order machine uses `submitting.after[30000] → timed_out` as the exchange-acknowledgement deadline, and the `FILLED` event arrives on the main thread from the market-data reader. Two concrete failures:

1. *Dropped timeout.* A `FILLED` being processed on the main thread sets `_is_processing = True`; the 30 s timer fires in that window, appends `after.30000.order.submitting` to the queue and returns immediately. The main thread's loop has already passed the queue check. The timeout event is never processed: the order sits in `submitting` forever with no deadline, and the OMS's stuck-order detector — which is the state machine — is the thing that failed.
2. *Corrupt position.* `record_fill` does `context["position"] += qty`. It runs on the market-data thread for `FILLED` and on the `after-…` daemon thread for the timeout's cleanup action, with no lock. A lost update means the machine's believed position diverges from the exchange's — the same class of failure as "position exists on exchange, machine believes order pending", but silently and with a wrong *number* rather than a wrong state, so no reconciliation alarm fires on state alone.

Because of this, `SyncInterpreter` was ruled out entirely for this application. There is no workaround available to a user: the threads are created unconditionally by `after`, and no flag disables them.

**Positive note.** The library already demonstrates the right instinct elsewhere: `SyncInterpreter` rejects `async def` services loudly and early with `NotSupportedError` rather than half-supporting them. Option 3 below simply applies that same existing pattern to `after`.

## Proposed fix

**Preferred — make the sync engine actually synchronous (option 1).**

1. In `_after_timer` (`sync_interpreter.py:1257-1327`), do not start a thread. Record the deadline in a sorted pending-timer list: `(fire_at_monotonic, unique_key, owner_id, event)`.
2. At the top of `_process_event_queue` (`:331`), before draining, move every timer whose `fire_at` has passed into `_event_queue` (preserving the existing owner-still-active check from `:1296`). Timers are thus delivered on the caller's thread, in queue order, with existing macrostep semantics unchanged.
3. Add a public `tick(now: float | None = None) -> None` so a caller with no traffic can advance deadlines deliberately — and so tests can drive them without sleeping. This is the natural seam for the clock injection requested in `LC-27`.
4. Apply the same treatment to `_deliver` (`:1028`).

**If threads must stay (option 2).** Introduce `self._lock = threading.RLock()` in `__init__` (`:115`) and hold it across `_process_event_queue` in full, across all `_event_queue`/`_active_state_nodes`/`_after_threads`/`_after_events` mutations, and replace the `_is_processing` check-then-set with re-entrancy detection under that lock. Note this only fixes *interpreter* state; user actions still run on a foreign thread, so the threading model must be documented regardless.

**Minimum viable (option 3).** Raise `NotSupportedError` at `start()` when any reachable state defines `after` (or `send` with `delay`) — mirroring the existing `async def` service rejection — and document the restriction.

**Backwards compatibility.** Option 1 is a behaviour change for anyone relying on `after` firing without a pump; that reliance is exactly the bug, and it is currently undocumented, so a minor-version change with a CHANGELOG entry is appropriate. `tick()` is purely additive. Option 3 is the most disruptive and should only ship if 1 is rejected. In all cases, the `SyncInterpreter` class docstring must state the threading contract explicitly — the current silence is half the defect.

## Acceptance criteria

- [ ] `SyncInterpreter` creates no OS threads for `after` transitions (assert via `threading.enumerate()` before/after `start()`).
- [ ] All actions, guards and services invoked by a `SyncInterpreter` run on the thread that called `send()` / `start()` / `tick()`.
- [ ] An `after` deadline that elapses while the caller is idle is delivered on the caller's next `send()` or `tick()`, not before.
- [ ] A timer event is never dropped as a result of re-entrancy; it is queued and drained in the same macrostep loop.
- [ ] `SyncInterpreter`'s class docstring states the threading contract explicitly.
- [ ] `repro/LC-38_sync-interpreter-timer-threads.py` exits `0`.
- [ ] Tests added under `tests/test_sync_interpreter_threading.py`:
  - `test_after_creates_no_background_threads`
  - `test_actions_run_on_calling_thread`
  - `test_after_fires_only_on_pump_not_on_bare_sleep`
  - `test_elapsed_timer_delivered_on_next_send`
  - `test_timer_event_not_dropped_when_queue_is_busy`
  - `test_tick_advances_due_timers_without_events`
  - `test_scheduled_send_uses_no_thread`
- [ ] Stress test `test_no_lost_updates_under_many_concurrent_timers` (many `after` states + a hot `send()` loop) passes 1000 iterations.

## Related

- The sync/async comparison that first surfaced this, from the same evaluation.
- `LC-43` — cross-thread `send()` loses events; the same missing synchronisation, reached from the user's side instead of the library's.
- `LC-27` — no clock injection / virtual time; the `tick(now=…)` seam proposed here is the sync-side half of that fix.
- `LC-26` — `after` timer starvation under load (async engine's version of "timers are not what they appear").
- `LC-24` — queued events lost on crash (same unguarded `_event_queue`).
- Found during an independent evaluation of the library for a trading application; the reproduction above is self-contained and needs nothing from that study.

## Verification

Independently verified on 2026-09-15.

- Environment: `xstate-statemachine` 0.7.0, commit `42612cf`, editable install; CPython 3.13.7; Windows 11 x64.
- `repro/LC-38_sync-interpreter-timer-threads.py` run in a fresh process: **exit code 1** (reproduces). Part 1 — the state advancing to `order.timed_out` with no `send()`, mutated solely by an `after-…` daemon thread — reproduced on every run. Part 2 (lost update) did not trigger, as the issue text already states.
- Root-cause references re-checked against the source: `sync_interpreter.py:1323-1327` (daemon thread per `after` deadline), `:1296-1305` (`self.send(event)` from the timer thread after an unsynchronised `_active_state_nodes` read), `:311-313` (`send()` appends then drains), `:337-340` (`_is_processing` check-then-set), `:1087-1090` and `:1185-1187` (two further daemon threads). The lock grep returns no matches, confirming the "no lock of any kind" claim.
- Expected-behaviour claim re-checked against XState v5 docs: https://stately.ai/docs/actors and https://stately.ai/docs/actor-model both state verbatim that "Actors process one message at a time. They have an internal 'mailbox' that acts like an event queue, processing events sequentially." https://stately.ai/docs/delayed-transitions confirms `after` is a scheduled delay with a simulated-clock testing story. The claim is accurate.
- Corrections applied during verification:
  - Method names were wrong: `_schedule_after_timer` does not exist (the method is `_after_timer`, `:1257`) and `_schedule_send` does not exist (it is `_deliver`, `:1028`). Renamed throughout the issue and the repro docstring; `_spawn_actor` is at `:1092`, not `:1185` (that is the `Thread(...)` call inside it). Line ranges corrected accordingly.
  - `_event_queue` is a `collections.deque` (`:132`), not a `list`. Corrected, and the claim sharpened: `deque.append` is atomic, but the append-then-drain sequence is not, which is where the race actually lives.
  - The Observed block's part-2 narrative said "`59 == 59`" while the block showed 60; replaced with a verbatim run and wording that does not depend on the exact count.
  - `__init__` is at `:115`, not `:133`.
- Duplicate check: `gh issue list --state all` returns only #17 (closed, unrelated). **Not a duplicate**.
