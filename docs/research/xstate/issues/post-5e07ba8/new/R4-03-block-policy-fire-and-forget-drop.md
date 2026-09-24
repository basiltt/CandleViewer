---
r4: R4-03
title: "Bug: OverflowPolicy.BLOCK silently discards every fire-and-forget send(), even on an empty inbox"
labels: [bug, severity/high, area/interpreter]
severity: High
repro_script: repro/R4-03_block_policy_fire_and_forget_drop.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

`Interpreter.send()` documents that *all* of its work — thread check,
normalisation, status guard and the queue put — happens eagerly, "so a
fire-and-forget `interp.send("GO")` from inside the loop is delivered rather
than silently dropped". That contract holds for `OverflowPolicy.RAISE` and
`DROP_NEWEST`, which call the synchronous `_enqueue()` inside `send()` itself.
It is false for `BLOCK`: `send()` returns the *un-started coroutine object*
`_enqueue_blocking(...)`, so a caller that does not `await` loses the event
entirely. Nothing is normalised onto a queue, no `on_event_dropped` hook fires,
no log line is written — the only trace is a GC-timed
`RuntimeWarning: coroutine 'Interpreter._enqueue_blocking' was never awaited`,
which most services never surface, and which under `-W error` becomes a crash
at an arbitrary later point inside the GC rather than at the call site. This
happens on a **completely empty** inbox, so it is not backpressure: it is
unconditional silent loss under one of the library's own recommended
production configurations.

## Environment

- Commit: `5e07ba8` (`main`, unreleased 0.8.1; `__version__` reports `0.8.0`)
- Python: 3.13.7 (CPython, 64-bit)
- OS: Windows 11 Pro (10.0.26200)
- Install: editable (`pip install -e .`) into a project venv
- Found by our adoption audit (#26), round 4.

## Minimal reproduction

```python
# -*- coding: utf-8 -*-
"""R4-03: OverflowPolicy.BLOCK silently discards every fire-and-forget send().

`Interpreter.send()` is documented as doing ALL of its work eagerly so that a
fire-and-forget `interp.send("GO")` is delivered rather than silently dropped.
That holds for RAISE and DROP_NEWEST, which call the synchronous `_enqueue()`.
It is FALSE for BLOCK: `send()` returns the *coroutine object*
`_enqueue_blocking(...)` without ever starting it. Nothing is queued, no hook
fires, no log line is written -- the only trace is a GC-timed RuntimeWarning.

Exits 1 while the defect is present, 0 once fixed.
"""
from __future__ import annotations

import asyncio
import gc
import warnings

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.models import OverflowPolicy

CONFIG = {
    "id": "counter",
    "initial": "idle",
    "context": {"n": 0},
    "states": {"idle": {"on": {"PING": {"actions": ["bump"]}}}},
}


def bump(interp, ctx, event, action_def):  # noqa: ANN001
    ctx["n"] += 1


def build():
    return create_machine(CONFIG, logic=MachineLogic(actions={"bump": bump}))


async def main() -> int:
    interp = Interpreter(
        build(),
        max_queue_size=1000,  # generous: the inbox is never anywhere near full
        overflow_policy=OverflowPolicy.BLOCK,
    )
    await interp.start()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for _ in range(10):
            interp.send("PING")  # fire-and-forget, as the docstring blesses
        await asyncio.sleep(0.05)
        gc.collect()
        await asyncio.sleep(0)
        warn_texts = [str(w.message) for w in caught]

    depth = interp.queue_depth
    n = interp.context["n"]
    await interp.stop()

    print("OBSERVED: sent=10 processed_context_n=%d queue_depth=%d "
          "RuntimeWarnings=%d" % (n, depth, len(warn_texts)))
    for t in sorted(set(warn_texts)):
        print("OBSERVED:   warning:", t)
    print("EXPECTED: sent=10 processed_context_n=10 queue_depth=0 "
          "RuntimeWarnings=0")

    ok = n == 10
    print("RESULT:", "PASS" if ok else "FAIL (all 10 events lost silently)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED: sent=10 processed_context_n=0 queue_depth=0 RuntimeWarnings=10
OBSERVED:   warning: coroutine 'Interpreter._enqueue_blocking' was never awaited
EXPECTED: sent=10 processed_context_n=10 queue_depth=0 RuntimeWarnings=0
RESULT: FAIL (all 10 events lost silently)
```

10/10 events lost. `context["n"]` is unchanged at `0`, `queue_depth` is `0`,
and the `on_event_dropped` plugin hook never fires — from the outside the
interpreter looks perfectly healthy and idle.

## Expected behaviour

The library's own contract, quoted from `send()`'s docstring
(`src/xstate_statemachine/interpreter.py:556-566`):

> 🏛️ Architecture decision (#37): this is a *regular* method that returns an
> awaitable, not an `async def`. An `async def` body runs only when awaited —
> so a call from a foreign thread (which cannot await it) executed NOTHING:
> not the status guard, not the queue put. The coroutine was discarded and
> every event silently lost, with only a GC-timed RuntimeWarning the library
> did not own.
>
> ALL of the work — thread check, normalisation, status guard and the queue
> put — therefore happens eagerly, before anything is awaited. […]
> Consequences: a wrong-thread call raises AT THE CALL SITE, and a
> fire-and-forget `interp.send("GO")` from inside the loop is delivered rather
> than silently dropped.

Issue #37 was fixed precisely to eliminate the "discarded coroutine ⇒ silent
loss, only a GC-timed RuntimeWarning" failure mode. The `BLOCK` branch
reintroduces the exact mode the fix removed. Expected: `BLOCK` takes its queue
slot eagerly whenever a slot is available (the overwhelmingly common case),
and the returned awaitable only genuinely suspends when the inbox is actually
full. Either way, a non-awaited `send()` must not lose the event; if the
library ever cannot accept an event, it must say so at the call site
(`QueueOverflowError`) or through `on_event_dropped` — never silently.

## Root cause analysis

`src/xstate_statemachine/interpreter.py:605-637`, the policy fan-out in
`send()`:

- Priority branch → `self._deliver_priority(event_obj)` — eager.
- `BLOCK` branch, **line 625**: `return self._enqueue_blocking(event_obj, receipt)`.
  `_enqueue_blocking` is an `async def` (`interpreter.py:819`). Calling it
  merely constructs a coroutine object; none of its body — including the
  `put` — runs until awaited. A fire-and-forget caller drops that object on
  the floor and the event never exists as far as the engine is concerned.
- Else branch, **line 637**: `self._enqueue(event_obj)` — eager, synchronous,
  exactly as documented.

The asymmetry is the whole bug: two of three policies enqueue eagerly, the
third defers *everything* (not just the waiting) into the coroutine. Note the
`BLOCK` branch already has an eager path for self-sends from an action
(`interpreter.py:617-623`, routed to `_internal_queue` to avoid the run-loop
self-deadlock of #38), which shows the eager-put shape is available — it is
simply not used on the ordinary path.

## Impact

**General users.** Any service that configures `max_queue_size` +
`OverflowPolicy.BLOCK` (the policy recommended for "suspend the producer under
backpressure") and issues any fire-and-forget `send()` — from a callback, a
signal handler, a background `asyncio` task, a third-party library's
completion hook — loses those events with zero observability. There is no
metric, no hook, no log; `queue_depth` reads `0` and the machine reports
`status="running"`, so health checks and dashboards show green. The
`RuntimeWarning` is emitted by the GC at an unrelated moment, is attributed to
no call site, and under `-W error` crashes an unrelated task.

**Concrete order-management scenario.** An order-management service runs one
interpreter per order with a bounded inbox under `BLOCK`. The venue adapter's
fill callback does `interp.send("FILL", qty=...)` fire-and-forget, as the
docstring explicitly blesses. Every fill, ack and cancel-confirm issued from
that callback is discarded. The order machine stays in `working` forever: the
position is filled at the venue but the service believes it is not, so it
re-sends the order, never books the fill, and the cancel that should have
capped the exposure never arrives. Money is lost and the only forensic trace
is a `RuntimeWarning` in a log nobody reads.

## Proposed fix

**Design.** Make `BLOCK` eager like the other two policies: in `send()`, if
the inbox has room, put immediately (synchronously) and return an
already-completed awaitable (or the pending `Receipt`); only when the inbox is
genuinely full return an awaitable that suspends until a slot frees. The queue
slot must be taken *before* `send()` returns, so the event survives a
non-awaited call.

Sketch in `src/xstate_statemachine/interpreter.py` around line 625:

```python
elif self._overflow_policy is OverflowPolicy.BLOCK and self._max_queue_size is not None:
    if self._processing and not self._refuse_if_not_running(event_obj):
        ...  # unchanged #38 self-send path
    if not self._inbox_full():
        self._enqueue(event_obj)          # eager slot take
        return receipt if receipt is not None else _completed()
    return self._await_slot_then_enqueue(event_obj, receipt)   # genuinely full
```

`_enqueue_blocking` keeps its current body for the genuinely-full path.

**Compatibility.** Fully backward compatible for the supported usage
`await interp.send(...)`: the awaitable still resolves the same way and the
`Receipt` semantics of #39 are untouched. Ordering is preserved — the eager
`put` happens at call time, which is *earlier* than today's (never-reached)
put. The only behaviour that changes is the currently-broken one.

**Alternatives considered.**
1. *Document `BLOCK` as await-only.* Rejected: it contradicts #37's stated
   architecture and leaves a silent-loss footgun in the recommended production
   config.
2. *Emit `on_event_dropped` / a warning from the BLOCK branch.* Insufficient —
   `send()` cannot know at that point whether the caller will await; it makes
   the loss visible but does not prevent it.
3. *Return an eagerly-scheduled `asyncio.Task` instead of a bare coroutine.*
   Prevents the loss and kills the `RuntimeWarning`, but reintroduces
   unordered delivery (the put would happen at an arbitrary later scheduling
   point) and creates an untracked task per send. Eager-put is strictly better.

At minimum, `send()` should refuse to return a bare coroutine on a path the
docstring advertises as fire-and-forget safe.

## Acceptance criteria

- [ ] `send()`'s `BLOCK` branch takes the inbox slot before returning whenever
      a slot is available.
- [ ] `repro/R4-03_block_policy_fire_and_forget_drop.py` exits `0`.
- [ ] `tests/test_interpreter_overflow.py::test_block_policy_fire_and_forget_is_delivered`
      — 10 non-awaited `send()` calls under `BLOCK` with a large
      `max_queue_size` all reach the machine; `context["n"] == 10`.
- [ ] `tests/test_interpreter_overflow.py::test_block_policy_emits_no_runtime_warning`
      — the run produces zero `RuntimeWarning`s (`warnings.simplefilter("error")`).
- [ ] `tests/test_interpreter_overflow.py::test_block_policy_still_suspends_when_full`
      — with `max_queue_size=1` and a stalled run loop, an awaited `send()`
      genuinely suspends and completes once a slot frees; ordering preserved.
- [ ] `tests/test_interpreter_overflow.py::test_block_policy_self_send_from_action_unchanged`
      — the #38 internal-queue routing for self-sends is not regressed.
- [ ] `send()`'s docstring states explicitly that the fire-and-forget guarantee
      holds for all three overflow policies.

## Related

- Register row `R4-03` (filed Blocker → final **High**; refuter graded
  "Major"). Source id `D-concurrency-1`; unmerged 1:1.
- Evidence: `battle-5e07ba8/concurrency/d1_block_fire_and_forget.py`,
  `battle-5e07ba8/concurrency.md` / `.triage.md`;
  final-verification run `probes/main-5e07ba8-final` `fv1_blockers_highs.py`
  (BLOCK `n=0` vs RAISE `n=1` vs DROP_NEWEST `n=1` for an identical
  non-awaited `send()` on a non-full inbox).
- Prior issues: **#37** (the `send()`-as-regular-method architecture decision
  this branch violates), **#38** (bounded inbox / overflow policies, which
  introduced the branch), **#39** (`wait=` receipts / `priority=`).
- Meta: our adoption audit **#26**.

## Verification

- Date: 2026-09-18
- Python: 3.13.7 (`.venv-main`)
- Commit: `5e07ba8`
- `repro/R4-03_block_policy_fire_and_forget_drop.py` re-run in a fresh process:
  exit code `1`, output matches the Observed section verbatim (10/10 events
  lost, `processed_context_n=0`, `queue_depth=0`, 10
  `RuntimeWarning`s for `Interpreter._enqueue_blocking` never awaited).
- Root cause confirmed by direct inspection of
  `src/xstate_statemachine/interpreter.py`: the `BLOCK` branch of `send()`
  returns `self._enqueue_blocking(event_obj, receipt)` (an un-awaited
  coroutine) on the ordinary, non-self-send path, while the `RAISE`/
  `DROP_NEWEST` fallthrough (`else` branch) calls the synchronous
  `self._enqueue(event_obj)` eagerly. `_enqueue_blocking` is `async def` and
  does nothing until awaited. (Line numbers have drifted a few lines from
  those cited in the issue due to intervening edits, but the code shapes and
  surrounding comments — including the `#38` self-send routing this issue's
  fix sketch builds on — match exactly.)
- No self-containedness issues; no project name/label leak found.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --search "BLOCK fire-and-forget"` and `"cross-thread send"` surface only
  issue **#37** (the `send()`-as-regular-method architecture decision this bug
  violates) and **#39**/**#51**/**#47**, none of which cover the `BLOCK`
  branch specifically. No duplicate found.
