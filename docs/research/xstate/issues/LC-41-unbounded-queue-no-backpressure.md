---
lc: LC-41
title: "Feature: interpreter event queue is unbounded, unobservable and has no backpressure signal"
labels: [enhancement, severity/high, area/interpreter, candleviewer]
severity: High
blocks_adoption: false
verified: true
repro_script: repro/LC-41_unbounded-queue-no-backpressure.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
---

## Summary

`Interpreter` buffers every incoming event in a single private, unbounded `asyncio.Queue` (`interpreter.py:129-131`) drained by one consumer task (`_run_event_loop`, `interpreter.py:406-529`). `send()` therefore always succeeds in microseconds regardless of how far behind the machine is: 20,000 events are accepted in 49 ms while the machine holds ~40 s of unprocessed work. There is **no public API of any kind** to observe the backlog — `dir(interpreter)` contains no `queue_depth`, `qsize`, `backlog` or `pending_events` — and no constructor option to bound the queue or choose an overflow policy.

The consequence is that a producer cannot tell a healthy machine from a saturated one, so it cannot shed load, cannot alarm, and cannot apply backpressure upstream. Memory grows without limit, and event latency grows with it, until the process dies or the data it is reacting to is stale enough to be wrong.

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, installed with `pip install -e .`
- Python: 3.13.7
- OS: Windows 11 (x64)
- Install: `pip install -e .` into a dedicated venv

## Current workaround and why it is insufficient

The only way to read the depth today is to reach into the private attribute:

```python
backlog = interp._event_queue.qsize()   # private; no compatibility guarantee
if backlog > THRESHOLD:
    raise BackpressureError          # the caller must also invent the policy
```

This is insufficient for three reasons:

1. `_event_queue` is private and undocumented; its type and even its existence can change in any release, so every deployment that depends on it is silently coupled to an internal.
2. `qsize()` is a *post-hoc* measurement. Because `send()` never blocks, the check is advisory only: any code path that forgets it still enqueues, and there is nothing the library can do to enforce the limit.
3. Depth alone does not describe saturation. What a caller actually needs to know is *time* — "an event enqueued now will be processed in ~40 s" — which requires the service rate as well as the depth, and the library exposes neither.

The realistic mitigation is to place a *separate* bounded queue and a queue-depth gauge in front of the interpreter and never call `send()` directly. That reimplements queueing outside the library, which means two queues, two latency sources, and a machine whose own buffer is still unbounded whenever anything bypasses the gateway.

## Minimal reproduction

```python
"""LC-41 repro: unbounded interpreter queue, no backpressure, no depth API.

`Interpreter._event_queue` is a private, unbounded `asyncio.Queue`. A producer
can enqueue an arbitrary number of events faster than the single consumer
drains them: `send()` never blocks, never raises, never drops, and there is no
public way to observe how far behind the machine is.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

BURST = 20_000
SLOW_MS = 2.0

CFG = {
    "id": "gw",
    "initial": "idle",
    "states": {"idle": {"on": {"TICK": {"actions": ["work"]}}}},
}


async def work(interp, ctx, event, action_def):  # noqa: ANN001
    await asyncio.sleep(SLOW_MS / 1000.0)  # a realistic slow handler


async def main() -> int:
    ok = True
    logic = MachineLogic(actions={"work": work})
    interp = await Interpreter(create_machine(CFG, logic=logic)).start()

    # 1) No public queue-depth API of any kind.
    public = [n for n in dir(interp) if not n.startswith("_")]
    depth_api = [
        n
        for n in public
        if any(
            k in n.lower()
            for k in ("queue", "qsize", "backlog", "pending_event")
        )
    ]
    print(f"OBSERVED public queue/depth API on Interpreter = {depth_api}")
    print("EXPECTED something like `queue_depth` / `qsize()` to be public")
    if not depth_api:
        ok = False

    # 2) A burst of 20,000 events is accepted with zero backpressure.
    t0 = time.monotonic()
    for i in range(BURST):
        await interp.send("TICK", i=i)
    enqueue_ms = (time.monotonic() - t0) * 1000
    backlog = interp._event_queue.qsize()  # private: the only way to see it
    print(
        f"OBSERVED {BURST} send() calls accepted in {enqueue_ms:.1f} ms, "
        f"0 dropped, 0 raised; private backlog = {backlog}"
    )
    print(
        "EXPECTED either a bounded queue that applies backpressure/raises, "
        "or at minimum an observable depth so a caller can shed load"
    )
    if backlog > 1000:
        ok = False

    # 3) The latency an event enqueued now will experience is unbounded and
    #    invisible: nothing in the public API predicts it.
    t1 = time.monotonic()
    await interp.send("TICK", i=-1)
    submit_ms = (time.monotonic() - t1) * 1000
    print(
        f"OBSERVED send() of one more event returned in {submit_ms:.3f} ms "
        f"while ~{backlog} events (~{backlog * SLOW_MS / 1000:.1f} s of work) "
        "are still queued ahead of it"
    )
    print("EXPECTED a way to detect this saturation before enqueuing")

    # 4) Constructing with a bound is not supported.
    try:
        Interpreter(create_machine(CFG, logic=logic), max_queue_size=100)
        print("OBSERVED Interpreter(..., max_queue_size=100) accepted")
    except TypeError as exc:
        print(f"OBSERVED Interpreter(..., max_queue_size=100) -> TypeError: {exc}")
        ok = False
    print("EXPECTED an optional bound + overflow policy")

    await interp.stop()
    print("RESULT:", "REPRODUCED (unbounded, unobservable queue)" if not ok else "NOT REPRODUCED")
    return 1 if not ok else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED public queue/depth API on Interpreter = []
EXPECTED something like `queue_depth` / `qsize()` to be public
OBSERVED 20000 send() calls accepted in 47.1 ms, 0 dropped, 0 raised; private backlog = 20000
EXPECTED either a bounded queue that applies backpressure/raises, or at minimum an observable depth so a caller can shed load
OBSERVED send() of one more event returned in 0.005 ms while ~20000 events (~40.0 s of work) are still queued ahead of it
EXPECTED a way to detect this saturation before enqueuing
OBSERVED Interpreter(..., max_queue_size=100) -> TypeError: Interpreter.__init__() got an unexpected keyword argument 'max_queue_size'
EXPECTED an optional bound + overflow policy
RESULT: REPRODUCED (unbounded, unobservable queue)
```

Corroborating measurement from our own fleet profiling (500 concurrently busy interpreters, each with a mix of `after` timers and short async actions): the in-queue wait between `send()` returning and the event actually being processed is 65 ms p50 / 95 ms p95, rising to ~2.2 s once arrival rate exceeds drain rate — all of it invisible to the producer.

## Expected behaviour

XState's actor model does not need a queue-depth API because its mailbox almost never accumulates. `actor.send()` is a *synchronous* method: when the actor is idle, `Mailbox.enqueue` immediately calls `flush()`, which processes the event on the caller's own stack before `send` returns, so `actor.getSnapshot()` straight afterwards reflects it (`packages/core/src/Mailbox.ts`, `enqueue`/`flush`). The mailbox only defers when a send arrives *while* the actor is already processing — i.e. re-entrant sends during a macrostep — which is bounded by the machine definition rather than by external arrival rate.

The Stately docs describe the mailbox as an implementation of ordering, not a buffer the user is expected to manage: "Actors process one message at a time. They have an internal 'mailbox' that acts like an event queue, processing events sequentially" (https://stately.ai/docs/actors). Because delivery is synchronous, there is no steady-state backlog for a producer to observe, and back-pressure is implicit — a slow machine slows its caller directly.

This library made a legitimate, different design choice — an async engine with a real inter-task queue. That choice is fine, but it introduces a queue the user did not ask for and cannot see. Any system that buffers on behalf of a caller is expected to expose depth and offer a bound; `asyncio.Queue` itself does both (`maxsize`, `qsize()`, `full()`, `put_nowait()` raising `QueueFull`). The library wraps that object and removes both capabilities.

Expected, concretely:

- `interpreter.queue_depth` (or `pending_event_count`) is public and documented.
- An optional bound with an explicit overflow policy is available at construction.
- The semantics of the bound are documented: which policy blocks, which raises, which drops, and what a dropped event does to machine correctness.

## Root cause analysis

`src/xstate_statemachine/interpreter.py:129-131`:

```python
self._event_queue: asyncio.Queue[
    Union[Event, AfterEvent, DoneEvent]
] = asyncio.Queue()
```

`asyncio.Queue()` with no `maxsize` is unbounded by definition. The attribute is private, and no property, method or plugin hook re-exports any part of it.

`send()` (`interpreter.py:335-375`) ends in:

```python
await self._event_queue.put(event_obj)
```

On an unbounded queue `Queue.put` never suspends — it delegates to `put_nowait` — so the `await` is decorative and `send()` completes in ~6 µs whatever the backlog. There is exactly one drop path, `status in ("stopped", "done", "error")` (`interpreter.py:362-369`), which concerns shutdown, not saturation.

The single consumer is `_run_event_loop` (`interpreter.py:406-529`), a `while self.status == "running": event = await self._event_queue.get()` loop created as one task in `start()` (`interpreter.py:234`). Service rate is therefore bounded by the slowest action in the machine, while the arrival rate is bounded by nothing.

Note that `_raise_depth` (`interpreter.py:133-137`, checked at `:429`) is *not* a backpressure mechanism, and the code comment at `:420-423` says so explicitly: it counts only events an action raised onto the machine's own queue during processing, so "external traffic of any volume is never throttled".

## Impact

**General users.** Any producer faster than the machine — a websocket feed, a file tailer, a fan-in from many tasks — grows the queue without limit. The failure mode is the bad one: no error, no log, no slowdown at the call site, just memory growth and steadily increasing staleness, ending in an OOM kill whose stack trace points somewhere unrelated. Because depth is unobservable, this cannot be alarmed on before it happens, and after a restart the evidence is gone. Users who do discover the problem are pushed to depend on `_event_queue`, a private attribute.

**CandleViewer (trading OMS).** The order-state gateway feeds exchange messages into per-order machines. During a volatility burst the inbound rate exceeds the drain rate of a machine whose `submitting` state invokes a slow HTTP confirm. The `FILLED` event for an order is accepted by `send()` in 6 µs and then sits in the queue behind 20,000 older ticks. The OMS believes the order is still pending — it has no signal that it is 40 seconds behind — so risk sizing is computed from a position that does not match the exchange, and the trading kill switch is evaluated against stale state. Measured in our fleet profile: 65 ms p50 / 95 ms p95 at 500 busy machines, ~2.2 s under saturation. With no `queue_depth` there is no queue-depth gauge to page on and no threshold at which the gateway can start shedding, so we must front every interpreter with our own bounded queue and forbid direct `send()` via a lint rule.

## Proposed API

Two additions, both backwards compatible.

**1. Read-only depth (non-breaking, no behaviour change).**

```python
@property
def queue_depth(self) -> int:
    """Number of events accepted but not yet processed."""
    return self._event_queue.qsize()
```

**2. Optional bound with an explicit overflow policy.**

```python
from xstate_statemachine import Interpreter, OverflowPolicy

interp = await Interpreter(
    machine,
    max_queue_size=10_000,            # default None -> today's unbounded queue
    overflow_policy=OverflowPolicy.RAISE,  # RAISE | BLOCK | DROP_NEWEST
).start()

try:
    await interp.send("TICK", price=p)
except QueueOverflowError as exc:
    metrics.shed.inc()
    logger.warning("machine %s saturated at depth %d", exc.interpreter_id, exc.depth)
```

Policies:

| Policy | Behaviour when full | Use |
|---|---|---|
| `BLOCK` (`await queue.put`) | `send()` suspends until space | trusted in-process producers that can be slowed |
| `RAISE` (default when a bound is set) | `QueueOverflowError(interpreter_id, depth, maxsize)` | gateways that must shed load and alarm |
| `DROP_NEWEST` | event discarded, `logger.warning`, `on_event_dropped` plugin hook | telemetry-grade events where staleness beats backlog |

Usage with monitoring:

```python
async def monitor(interp: Interpreter) -> None:
    while interp.status == "running":
        machine_queue_depth.labels(interp.id).set(interp.queue_depth)
        await asyncio.sleep(1.0)
```

**Backwards compatibility.** `max_queue_size` defaults to `None`, which constructs `asyncio.Queue()` exactly as today; `queue_depth` is purely additive. No existing program changes behaviour. `DROP_NEWEST` is the only policy that can lose an event, it is never the default, and its drops are both logged and delivered to `PluginBase.on_event_dropped` (a new no-op hook in `plugins.py`, so existing plugins are unaffected).

**Sketch of the change.**

- `interpreter.py:129-131` — construct `asyncio.Queue(maxsize=max_queue_size or 0)`; store `self._overflow_policy`.
- `interpreter.py` `__init__` signature — add `max_queue_size: Optional[int] = None`, `overflow_policy: OverflowPolicy = OverflowPolicy.RAISE`.
- `interpreter.py:375` — replace the bare `await self._event_queue.put(event_obj)` with a `_enqueue()` helper implementing the policy table.
- `interpreter.py:377-400` (`send_events`) — route through the same helper so a batch cannot bypass the bound.
- `plugins.py` — add `on_event_dropped(self, interpreter, event, reason)` defaulting to `pass`.
- `exceptions.py` — add `QueueOverflowError(StateMachineError)` carrying `interpreter_id`, `depth`, `maxsize`.
- `sync_interpreter.py` — `SyncInterpreter` uses a `deque`, not an `asyncio.Queue`; expose the same `queue_depth` property there for API symmetry.

## Acceptance criteria

- [ ] `Interpreter.queue_depth` is a public, documented, read-only `int` property.
- [ ] `Interpreter(machine, max_queue_size=N, overflow_policy=...)` is accepted; `max_queue_size=None` reproduces today's unbounded behaviour byte-for-byte.
- [ ] `RAISE` raises `QueueOverflowError` from `send()` when full, with `depth` and `maxsize` populated.
- [ ] `BLOCK` suspends `send()` until the consumer makes space, and resumes correctly.
- [ ] `DROP_NEWEST` discards, logs a warning, and invokes `PluginBase.on_event_dropped`.
- [ ] `send_events()` honours the bound and policy identically to `send()`.
- [ ] `SyncInterpreter.queue_depth` exists and reports the pending `deque` length.
- [ ] Docs: a "Backpressure and queue depth" section covering the policy table and the correctness consequences of dropping.
- [ ] `repro/LC-41_unbounded-queue-no-backpressure.py` exits 0.
- [ ] Tests added:
  - `tests/test_interpreter_backpressure.py::test_queue_depth_property_tracks_pending_events`
  - `tests/test_interpreter_backpressure.py::test_unbounded_by_default_preserves_legacy_behaviour`
  - `tests/test_interpreter_backpressure.py::test_raise_policy_raises_queue_overflow_error`
  - `tests/test_interpreter_backpressure.py::test_block_policy_suspends_until_drained`
  - `tests/test_interpreter_backpressure.py::test_drop_newest_policy_logs_and_calls_plugin_hook`
  - `tests/test_interpreter_backpressure.py::test_send_events_batch_respects_bound`
  - `tests/test_sync_interpreter.py::test_sync_queue_depth_property`

## Related

- `LC-42` — `send()` cannot answer synchronously. Same root cause (the queue); grouped with this issue in the register.
- `LC-39`, `LC-40` — throughput is a fixed global budget (~8.8k ev/s realistic), which is what makes saturation reachable in practice.
- `LC-26` — `after` timer starvation under load: the same single consumer, so a deep queue also delays timers.
- `LC-24` — queued events are lost on crash: the deeper the unbounded queue, the more is lost.
- `LC-48` — no error-observability hooks; the `on_event_dropped` hook proposed here is the same gap.

## Verification

Independently verified on 2026-09-15.

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, `pip install -e .`
- Python: 3.13.7 (CPython, MSC v.1944 64-bit), Windows 11 x64
- Repro run in a fresh process: `repro/LC-41_unbounded-queue-no-backpressure.py` → **exit code 1** (fails today), output matches the Observed section.
- Root-cause line cites re-checked against the source: `interpreter.py:129-131` (`asyncio.Queue()`, no `maxsize`), `:335-375` (`send`, ending in `await self._event_queue.put(event_obj)` at `:375`), `:359-368` → corrected to `:362-369` (the shutdown drop path), `:406-529` (`_run_event_loop`), `:427` (`await self._event_queue.get()`), `:429` (`_raise_depth` check), `:234` (single consumer task), `:133-137` + `:418-422` (the "external traffic of any volume is never throttled" comment).
- Corrections made: the XState "Expected behaviour" section previously asserted `actor.send` is synchronous citing only two doc pages that do not state it; replaced with the actual mechanism from `packages/core/src/Mailbox.ts` (`enqueue` calls `flush()` inline when idle, defers only during re-entrant processing) plus the verbatim mailbox sentence from https://stately.ai/docs/actors. Timings in Observed refreshed from this run. CandleViewer-internal references (`01 §11`, budget 1, B1/B2/B9/B13/B18, `cv_machine_queue_depth`) replaced with inline explanations so the issue is self-contained.
- Duplicate check: `gh issue list --repo basiltt/xstate-statemachine --state all` returns a single unrelated issue (#17, camelCase action auto-discovery). Not a duplicate.
