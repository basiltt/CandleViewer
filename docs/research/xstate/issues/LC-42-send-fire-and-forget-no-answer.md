---
lc: LC-42
title: "Feature: `send()` is fire-and-forget — a statechart cannot answer a question synchronously"
labels: [enhancement, severity/high, area/interpreter, candleviewer]
severity: High
blocks_adoption: false
verified: true
repro_script: repro/LC-42_send-fire-and-forget-no-answer.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
---

## Summary

`Interpreter.send()` resolves when the event is *queued*, not when it is *processed* (`interpreter.py:375`, `await self._event_queue.put(event_obj)`). It returns `None`, so the caller receives no handle on the transition the event causes. Immediately after `await interp.send("TRIP")` the machine is still in `open`, not `tripped`.

The only way to learn the outcome is to poll `current_state_ids` in a loop, and the answer arrives after every event already queued has been processed — measured at **p50 = 27 ms / max = 48 ms behind a 2,000-event backlog**, and 33.5 ms p50 / 50.8 ms max in our 2,854-interpreter fleet profile. There is no priority or bypass send. This makes a statechart unusable as the authority for any decision a caller must act on *now* — a kill switch, a rate governor, a risk lockout — even though those are exactly the decisions statecharts model best.

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, installed with `pip install -e .`
- Python: 3.13.7
- OS: Windows 11 (x64)
- Install: `pip install -e .` into a dedicated venv

## Current workaround and why it is insufficient

**Workaround A — poll after sending:**

```python
await interp.send("RESERVE", n=1)
while "gov.granted" not in interp.current_state_ids:
    await asyncio.sleep(0)          # burns CPU; no timeout; no failure signal
allowed = "gov.granted" in interp.current_state_ids
```

This is what the repro measures. It is insufficient because: the wait is unbounded and grows with queue depth (LC-41); a busy-wait on `sleep(0)` starves the very loop that must drain the queue; there is no way to distinguish "not decided yet" from "decided against" without inventing a distinct state per outcome; and the polled read is racy — another event may have moved the machine on again before the poll observes it, so the caller can read a state that was never the answer to *its* event.

**Workaround B — a completion event carried in context:**

```python
fut = asyncio.get_running_loop().create_future()
await interp.send("RESERVE", n=1, _reply=fut)   # action must resolve fut
allowed = await asyncio.wait_for(fut, timeout=0.05)
```

This works, but it means every machine that must answer a caller has to thread a future through its payload and have *every* relevant action remember to resolve it, including on the paths that do not transition. Forget one branch and the caller hangs until the timeout. It is the library's dispatch mechanism reimplemented in user actions, per machine, with no help from the engine.

**Workaround C — don't ask the statechart.** This is what CandleViewer actually does: the statechart *records and orchestrates*, and a plain synchronous flag or token bucket *enforces*. The cost is a duplicated source of truth: the authoritative gate and the machine that models the gate can disagree, and reconciling them is manual. The measurement that forces this: a statechart `RESERVE` decision costs `p50 = 35.20 ms, p95 = 44.03 ms, max = 53.18 ms`, against **0.148 µs** for a plain token bucket — **~238,264× slower**.

## Minimal reproduction

```python
"""LC-42 repro: `send()` is fire-and-forget; a statechart cannot answer.

`Interpreter.send()` is `await self._event_queue.put(event)` — it resolves as
soon as the event is *queued*, not when it is *processed*. The caller gets no
handle on the resulting transition, so "ask the machine and act on the answer"
(a kill switch, a rate governor, a risk lockout) has to poll, and the answer
arrives an unbounded time later.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import statistics
import sys
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

CFG = {
    "id": "gov",
    "initial": "open",
    "states": {
        "open": {"on": {"TRIP": {"target": "tripped"}, "NOISE": {}}},
        "tripped": {"type": "final"},
    },
}

BACKGROUND = 2_000


async def main() -> int:
    ok = True
    interp = await Interpreter(create_machine(CFG, logic=MachineLogic())).start()

    # 1) send() returns None — no future/receipt to await.
    ret = await interp.send("NOISE")
    sig = inspect.signature(Interpreter.send)
    print(f"OBSERVED Interpreter.send(...) returned {ret!r}; return annotation "
          f"= {sig.return_annotation!r}")
    print("EXPECTED an awaitable receipt resolving after the event is processed")
    if ret is not None:
        ok = False

    # 2) After `await send(TRIP)` the machine has NOT transitioned yet.
    interp2 = await Interpreter(create_machine(CFG, logic=MachineLogic())).start()
    await interp2.send("TRIP")
    state_right_after = set(interp2.current_state_ids)
    print(f"OBSERVED state immediately after `await send('TRIP')` = {state_right_after}")
    print("EXPECTED {'gov.tripped'} (XState `actor.send` processes synchronously)")
    if "gov.tripped" not in state_right_after:
        ok = False
    await interp2.stop()

    # 3) The decision latency under a modest backlog. Caller must poll.
    lat = []
    for _ in range(5):
        i = await Interpreter(create_machine(CFG, logic=MachineLogic())).start()
        for n in range(BACKGROUND):
            await i.send("NOISE", n=n)
        t0 = time.perf_counter()
        await i.send("TRIP")
        while "gov.tripped" not in i.current_state_ids:
            await asyncio.sleep(0)  # the only available "answer" mechanism
        lat.append((time.perf_counter() - t0) * 1000)
        await i.stop()
    print(
        f"OBSERVED decision latency behind {BACKGROUND} queued events: "
        f"p50={statistics.median(lat):.2f}ms max={max(lat):.2f}ms (poll loop)"
    )
    print("EXPECTED O(1) synchronous answer, or a priority send that jumps the queue")
    if statistics.median(lat) > 1.0:
        ok = False

    # 4) No priority/urgent send exists.
    prio = [n for n in dir(interp) if "prio" in n.lower() or "urgent" in n.lower()]
    print(f"OBSERVED priority-send API = {prio}")
    print("EXPECTED e.g. `send(..., priority=True)` or `send_sync()`")
    if not prio:
        ok = False

    await interp.stop()
    print("RESULT:", "REPRODUCED (send cannot answer)" if not ok else "NOT REPRODUCED")
    return 1 if not ok else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED Interpreter.send(...) returned None; return annotation = None
EXPECTED an awaitable receipt resolving after the event is processed
OBSERVED state immediately after `await send('TRIP')` = {'gov.open'}
EXPECTED {'gov.tripped'} (XState `actor.send` processes synchronously)
OBSERVED decision latency behind 2000 queued events: p50=27.40ms max=47.80ms (poll loop)
EXPECTED O(1) synchronous answer, or a priority send that jumps the queue
OBSERVED priority-send API = []
EXPECTED e.g. `send(..., priority=True)` or `send_sync()`
RESULT: REPRODUCED (send cannot answer)
```

Corroborating measurements from our own profiling: a kill-switch decision across a 2,854-interpreter fleet — 33.5 ms p50 / 50.8 ms max; a governor `RESERVE` decision — p50 35.20 ms, p95 44.03 ms, max 53.18 ms, versus 0.148 µs for an equivalent plain token bucket.

## Expected behaviour

In XState v5, `actor.send(event)` normally processes the event *before it returns*, so the snapshot read straight afterwards reflects that send. This is not a documented guarantee phrased as such, but it is the observable behaviour and it falls out of the mailbox implementation: `Mailbox.enqueue` sets `_current` and, when the actor is not already processing, calls `flush()` synchronously on the caller's stack (`packages/core/src/Mailbox.ts`). The deferral path exists only for re-entrant sends that arrive *while* a macrostep is running.

The docs describe the resulting user-visible contract:

> "Actors process one message at a time. They have an internal 'mailbox' that acts like an event queue, processing events sequentially." — https://stately.ai/docs/actors
>
> "When an actor receives an event, its internal state may change... You can read an actor's snapshot synchronously via `actor.getSnapshot()`." — https://stately.ai/docs/actors

The docs' own testing example relies on exactly this — three `actor.send({type:'inc'})` calls followed immediately by `expect(actor.getSnapshot().context).toEqual({count: 3})` with no awaiting (https://stately.ai/docs/actors, "Testing"). SCXML specifies the same run-to-completion discipline for external events: an event is selected from the external queue and the resulting macrostep runs to quiescence before the processor takes the next one (https://www.w3.org/TR/scxml/#AlgorithmforSCXMLInterpretation).

This library's async engine cannot make `send()` literally synchronous without breaking its model, and it should not try. What is missing is the *receipt*: a way for the caller to await the completion of the macrostep its own event caused, and a way to place an urgent event at the head of the queue. XState users get the answer for free because nothing sits between them and the machine in the common case; here a real inter-task queue was introduced, so the answer needs an explicit channel.

## Root cause analysis

`src/xstate_statemachine/interpreter.py:335-375` — the whole of `send()`:

```python
async def send(self, event_or_type, **payload) -> None:
    ...
    event_obj = self._prepare_event(event_or_type, **payload)
    await self._event_queue.put(event_obj)
```

Three properties follow directly:

1. **Return type is `None`.** Nothing identifying the event is handed back, so nothing can later be correlated with its processing.
2. **`put` on an unbounded queue never suspends** (see LC-41), so `await send(...)` completes in microseconds having done nothing but append.
3. **FIFO only.** `asyncio.Queue` has no priority discipline and `send()` exposes no flag to bypass it, so an urgent event waits behind every routine one.

Processing happens later and elsewhere, in the single consumer `_run_event_loop` (`interpreter.py:406-529`): `event = await self._event_queue.get()` → `_process_event(...)` → `self._event_queue.task_done()` (`:491`). The `task_done()` bookkeeping exists, which means the loop already knows the exact moment an individual event finished — it simply has no reference back to the caller to notify. `Queue.join()` is not a substitute: it waits for the queue to become *entirely* empty, so under continuous traffic it may never return, and it cannot distinguish one caller's event from another's.

Note also that `status` can read `"running"` while `_event_loop_task` is `None` (a `from_snapshot()` restore), i.e. while nothing is draining. The library does provide `is_running` (`interpreter.py:147-166`), which correctly requires a live loop task, so a polling caller has a liveness signal — but it is a separate property from the `status` most callers reach for, and polling still cannot correlate an answer with a specific event.

## Impact

**General users.** The natural reading of `await interp.send(...)` is "the machine has handled this" — it has an `await`, so it looks like it waits for something. It does not, and nothing in the signature says so. Users write `await send(...)` then read state, get the *previous* state, and debug a race that the API invited. Request/response over a statechart (validate, authorise, admit, rate-limit) is not expressible at all; every such use becomes a hand-rolled future-in-payload protocol. The `await` on a method that cannot block is itself misleading API surface.

**CandleViewer (trading OMS).** Three concrete casualties:

- **Kill switch.** "Is trading halted?" must be answered before an order leaves the process. Asking the fleet's statechart costs 33.5 ms p50 / 50.8 ms max — after the order is already in flight. The statechart cannot be the gate; it can only record that the gate fired.
- **Rate governor (never built).** A `RESERVE` decision at 35.20 ms p50 against a token bucket's 0.148 µs — ~238,264× — rules out modelling the governor as a statechart, so the fan-out rate limiter simply does not exist as a machine.
- **Risk lockout.** The lockout decision must precede submission; polling for `locked_out` after `await send("BREACH")` returns the pre-breach state, so an order can be submitted against a book that has already breached.

The architectural consequence is a standing rule in our codebase: statecharts record and orchestrate, a plain synchronous flag enforces. Two sources of truth for every gate, and the divergence between them is a class of bug the library could have prevented.

## Proposed API

**1. An awaitable receipt (opt-in, default off).**

```python
receipt = await interp.send("TRIP", reason="dd_limit", wait=True)
# resolves only after the macrostep caused by this event has run to completion
print(receipt.state_ids)       # frozenset({'gov.tripped'})
print(receipt.changed)         # True — a transition was taken
print(receipt.error)           # None, or the exception raised during processing
```

Full example — the kill switch, expressed the way users want to write it:

```python
async def submit(order, interp: Interpreter) -> bool:
    receipt = await asyncio.wait_for(
        interp.send("CHECK", order_id=order.id, priority=True, wait=True),
        timeout=0.005,
    )
    if "risk.halted" in receipt.state_ids:
        metrics.blocked.inc()
        return False
    return await exchange.submit(order)
```

`wait=False` (the default) returns `None` exactly as today.

**2. A priority send that jumps the queue.**

`priority=True` places the event at the head of the queue (a `PriorityQueue`, or a second high-priority `deque` the consumer checks first), so an urgent decision is not stuck behind routine traffic. Ordering among priority events is FIFO relative to one another. The documentation must state plainly that priority sends reorder events and can therefore change machine semantics, and that they are for out-of-band control events (halt, cancel, shutdown), not for routine traffic.

**3. `SyncInterpreter` as the truly-synchronous option.** `SyncInterpreter.send()` already processes inline, so the "I need an answer now" use case has a home — but this is not documented as the reason to choose it, and `SyncInterpreter` carries its own problems (LC-38). The docs should route the request/response use case there explicitly.

**Backwards compatibility.** Both `wait` and `priority` are keyword-only with defaults preserving current behaviour, so `send()`'s signature and return value are unchanged for every existing call. The one risk is the payload namespace: today `send("E", wait=True)` puts `wait` into the event payload. Mitigation: reserve `wait`/`priority` as keyword-only parameters *after* a `*`, and emit a `DeprecationWarning` for one minor release whenever a payload key collides with a reserved name, so the change is visible before it bites. `Receipt` is a new frozen dataclass; nothing existing references it.

**Sketch of the change.**

- `interpreter.py:129-131` — the queue holds `(priority, seq, event, receipt_future)` tuples, or keep two queues.
- `interpreter.py:335-375` (`send`) — build the event; when `wait=True` create `loop.create_future()`, enqueue it alongside the event, and `return await fut`.
- `interpreter.py:406-529` (`_run_event_loop`) — after `_process_event` completes (and in the `except` path), resolve the attached future with a `Receipt(state_ids, changed, error)` before `task_done()` at `:491`.
- `interpreter.py:377-400` (`send_events`) — accept `wait=True` returning `List[Receipt]`.
- `interpreter.py:275-325` (`stop`) — resolve all outstanding receipt futures with a `InterpreterStoppedError` so no caller hangs on shutdown; likewise for events dropped at `:362-369`.
- New `Receipt` dataclass in `models.py` or `events.py`.

## Acceptance criteria

- [ ] `await interp.send("E", wait=True)` returns a `Receipt` only after the macrostep for that specific event has completed.
- [ ] `Receipt.state_ids` equals `interp.current_state_ids` at the instant processing finished, and `Receipt.changed` reports whether a transition was taken.
- [ ] An exception raised while processing the event surfaces on `Receipt.error` rather than being swallowed.
- [ ] `await interp.send("E")` (no `wait`) still returns `None` and behaves identically to 0.7.0.
- [ ] `send("E", priority=True)` is processed ahead of already-queued non-priority events; priority events preserve FIFO among themselves.
- [ ] Priority + `wait` together yield a bounded decision latency under a 2,000-event backlog (the repro's p50 drops below 1 ms).
- [ ] `stop()` resolves every outstanding receipt future rather than leaving callers awaiting forever.
- [ ] Events dropped because the interpreter is stopped/done/error resolve their receipt with an error.
- [ ] A payload key colliding with a reserved keyword (`wait`, `priority`) emits a `DeprecationWarning`.
- [ ] Docs: "Getting an answer from a machine" — receipts, priority sends, when to use `SyncInterpreter` instead.
- [ ] `repro/LC-42_send-fire-and-forget-no-answer.py` exits 0.
- [ ] Tests added:
  - `tests/test_interpreter_send_receipt.py::test_send_wait_returns_receipt_after_processing`
  - `tests/test_interpreter_send_receipt.py::test_send_wait_receipt_reports_state_and_changed`
  - `tests/test_interpreter_send_receipt.py::test_send_wait_receipt_carries_processing_error`
  - `tests/test_interpreter_send_receipt.py::test_send_without_wait_is_unchanged_and_returns_none`
  - `tests/test_interpreter_send_receipt.py::test_stop_resolves_pending_receipts`
  - `tests/test_interpreter_priority_send.py::test_priority_event_jumps_queued_backlog`
  - `tests/test_interpreter_priority_send.py::test_priority_events_are_fifo_among_themselves`
  - `tests/test_interpreter_send_receipt.py::test_reserved_payload_key_warns`

## Related

- `LC-41` — unbounded queue with no backpressure; same root cause, grouped with this issue in the register. The receipt's latency is exactly the depth LC-41 makes invisible.
- `LC-09` — a raising guard is swallowed as `False`; with no receipt channel there is nowhere to report it even in principle.
- `LC-08` — unknown transition targets fail at runtime with only a log line, for the same reason (cited in that issue's root-cause section).
- `LC-48` — no error-observability hooks.
- `LC-38` — `SyncInterpreter`, the proposed synchronous escape hatch, is itself not single-threaded.
- `LC-39`, `LC-40` — throughput limits that set the floor on how long a receipt takes to resolve.

## Verification

Independently verified on 2026-09-15.

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, `pip install -e .`
- Python: 3.13.7 (CPython, MSC v.1944 64-bit), Windows 11 x64
- Repro run in a fresh process: `repro/LC-42_send-fire-and-forget-no-answer.py` → **exit code 1** (fails today), output matches the Observed section.
- Root-cause line cites re-checked against the source: `interpreter.py:335-375` (`send`, returning `None`, body ending at `:375` in `await self._event_queue.put(event_obj)`), `:406-529` (`_run_event_loop`), `:427` (`get()`), `:491` (`task_done()`). Confirmed `asyncio.Queue` is constructed unbounded at `:129-131`, so `put` never suspends, and confirmed no priority/urgent send exists anywhere in the public API.
- Corrections made: the XState section previously carried two quotes that do not appear on the cited page and asserted synchronous `send` as documented fact; replaced with the actual `Mailbox.enqueue`/`flush` mechanism, two verbatim quotes that do appear, and the docs' own `send`-then-`getSnapshot` testing example. The root-cause claim that a polling caller "has no reliable liveness signal" was wrong — `is_running` (`interpreter.py:147-166`) exists and explicitly requires a live loop task; the paragraph now states the real, narrower limitation. Observed timings refreshed from this run (max was 34.63 ms, now 47.80 ms). CandleViewer-internal references (MUSTNOT-02/05, B18/B20, `adv02`/`adv04`, CR-5, FEATURE_GAP_ANALYSIS) replaced with inline explanations.
- Duplicate check: `gh issue list --repo basiltt/xstate-statemachine --state all` returns a single unrelated issue (#17, camelCase action auto-discovery). Not a duplicate.
