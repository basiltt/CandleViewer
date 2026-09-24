---
lc: LC-05
title: "Semantics: `raise` is queued behind pending external events — no macrostep/microstep distinction"
labels: [bug, severity/high, area/interpreter, candleviewer]
severity: High
blocks_adoption: false
repro_script: repro/LC-05_raise-not-macrostep.py
library_version: 0.7.0 (commit 42612cf)
verified: true
python: 3.13.7
---

## Summary

The `raise` built-in action enqueues onto the **same FIFO `asyncio.Queue`** as external `send()` calls, so an external event that arrived while a transition was executing is processed *before* the event the transition raised. SCXML (and XState v5, which implements it) treat raised events as **internal** events belonging to the current macrostep: the internal queue is drained to exhaustion before the external queue is consulted again. The library's behaviour is deterministic and internally consistent, but it breaks the one guarantee `raise` exists to provide — that a state's self-announced follow-up settles before the outside world is heard from again.

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, installed with `pip install -e .`
- Python: 3.13.7
- OS: Windows 10/11 (x64)

## Minimal reproduction

```python
"""LC-05: `raise` is queued behind pending external events (no macrostep).

Entry into state `b` raises RAISED. An external EXTERNAL event is sent right
after GO. XState/SCXML settle the internal (raised) event within the same
macrostep, so the trace must be entry, RAISED, EXTERNAL.
"""

from __future__ import annotations

import asyncio
import sys
from typing import List

from xstate_statemachine import Interpreter, MachineLogic, create_machine


async def main() -> int:
    trace: List[str] = []

    def mark_entry(i, c, e, a):  # noqa: ANN001
        trace.append("entry")

    def rec(i, c, e, a):  # noqa: ANN001
        trace.append(e.type)

    cfg = {
        "id": "m",
        "initial": "a",
        "context": {},
        "states": {
            "a": {"on": {"GO": "b"}},
            "b": {
                "entry": [
                    "mark_entry",
                    {"type": "raise", "params": {"event": "RAISED"}},
                ],
                "on": {
                    "RAISED": {"actions": ["rec"]},
                    "EXTERNAL": {"actions": ["rec"]},
                },
            },
        },
    }
    logic = MachineLogic(actions={"mark_entry": mark_entry, "rec": rec})
    interp = await Interpreter(create_machine(cfg, logic=logic)).start()
    await interp.send("GO")
    await interp.send("EXTERNAL")
    await asyncio.sleep(0.3)
    await interp.stop()

    expected = ["entry", "RAISED", "EXTERNAL"]
    print("OBSERVED:", trace)
    print("EXPECTED:", expected)
    return 0 if trace == expected else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED: ['entry', 'EXTERNAL', 'RAISED']
EXPECTED: ['entry', 'RAISED', 'EXTERNAL']
```

Exit code `1`. `EXTERNAL` was enqueued while `GO` was still being processed, so it sits ahead of `RAISED` in the single queue and wins.

## Expected behaviour

XState v5 — https://stately.ai/docs/actions#raise-action:

> "The raise action is a special action that *raises* an event that is received by the same machine. Raising an event is how a machine can "send" an event to itself"
>
> "Internally, when an event is raised, it is placed into an "internal event queue". After the current transition is finished, these events are processed in insertion order (first-in first-out, or FIFO). **External events are only processed once all events in the internal event queue are processed.**"

This is the SCXML algorithm (W3C SCXML 1.0 §3.13, `mainEventLoop`/`microstep`): an interpreter loops `selectEventlessTransitions`, then drains **`internalQueue`** to exhaustion, and only when no internal event remains does it block on **`externalQueue`**. Two queues, internal strictly prioritised. The library already implements the eventless (`always`) part of that loop faithfully — `_process_event_and_transient_transitions` — which makes the missing internal queue the odd one out.

## Root cause analysis

There is exactly one queue. `src/xstate_statemachine/interpreter.py:129` declares `self._event_queue: asyncio.Queue[...]`, and both paths feed it:

- External: `Interpreter.send` → `interpreter.py:375` → `await self._event_queue.put(event_obj)`
- Raised: the `raise` built-in resolves to a self-delivery, `_deliver` (`interpreter.py:785-808`) with `delay=None` → `self._send_to_actor(actor, target_event)` → the same `_event_queue.put`.

`_deliver` already *detects* the internal case — `if actor is self and self._processing: self._raise_depth += 1` (`interpreter.py:805-806`) — purely to bound runaway raise chains. So the interpreter knows an event is internal at the exact moment it enqueues it, and then discards that knowledge by putting it on the shared FIFO. `_run_event_loop` (`interpreter.py:406`) pops with a single `await self._event_queue.get()` (`:427`); ordering is therefore pure arrival order.

## Impact

**General:** `raise` is the idiomatic way to decompose one logical step into several transitions — validate, then commit; enter, then immediately classify. Any such decomposition can be interleaved with external traffic, so a state can observe an outside event in the window between its own two halves. The bug is load-dependent and invisible under a quiet event stream: tests pass on a idle machine and the interleaving appears in production. It also makes `raise` unusable for the one thing it is uniquely good at — guaranteeing an atomic multi-transition step.

**CandleViewer (trading OMS):** our order machine uses a self-raised `EVALUATE` on entry to `live` to re-check risk limits immediately after a fill is applied (fill → entry → raise `EVALUATE` → either `live` or `reducing`). A `PARTIAL` fill arriving from the exchange feed during that transition is processed *before* `EVALUATE`, so the risk evaluation runs against a position that has already moved, and the decision it commits is one fill stale. In the worst case the machine sizes a hedge off the pre-fill quantity and leaves residual exposure that no state represents. Our trade-group aggregation machine and our compiled rule engine (which raises between rule stages) have the same exposure.

## Proposed fix

Split the queue, mirroring SCXML:

1. Add `self._internal_queue: Deque[Event]` (a `collections.deque` is enough — internal events are only ever enqueued from the interpreter's own task) alongside `self._event_queue` in `Interpreter.__init__` (`interpreter.py:129`).
2. In `_deliver` (`interpreter.py:800-808`), route the already-detected internal case to it:

   ```python
   if actor is self and self._processing:
       self._raise_depth += 1
       self._internal_queue.append(target_event)
       return
   ```

3. In `_run_event_loop` (`interpreter.py:406`, loop body at `:425-427`), drain internal before touching the external queue:

   ```python
   while self.status == "running":
       while self._internal_queue:
           await self._step(self._internal_queue.popleft())
       event = await self._event_queue.get()
       await self._step(event)
   ```

   where `_step` is the existing try/except body around `_process_event_and_transient_transitions` (`interpreter.py:531`). The `_raise_depth` bound keeps working unchanged and now guards a genuinely unbounded structure, which is more correct than before. XState bounds the same structure the same way — its `maxIterations` throws *"Infinite loop detected: the machine has processed more than N microsteps without reaching a stable state."*
4. Clear `_internal_queue` in `stop()` and exclude it from snapshots (internal events are, by definition, mid-macrostep state that should never be persisted) — or document explicitly that a snapshot is only ever taken between macrosteps.
5. Apply the same split to `SyncInterpreter` so the two engines agree.

Backwards compatibility: the change only reorders events in the window where an external event arrives *during* processing — a window in which the current order is arbitrary from the user's point of view and is not documented anywhere. No API change. It is worth a CHANGELOG note under "behaviour changes" for anyone who has (accidentally) come to depend on the current interleaving.

## Acceptance criteria

- [ ] The repro trace is `["entry", "RAISED", "EXTERNAL"]`.
- [ ] A chain of raises (`A` raises `B` raises `C`) fully settles before a concurrently queued external event is processed.
- [ ] `always`/eventless transitions and raised events interleave per SCXML: eventless transitions are taken before the internal queue is drained at each microstep.
- [ ] The `max_iterations` runaway-raise guard still trips on a self-feeding raise and still does **not** throttle high-volume external `send()` traffic (regression guard for the `interpreter.py:409-422` comment).
- [ ] `SyncInterpreter` exhibits the same ordering.
- [ ] `repro/LC-05_raise-not-macrostep.py` exits 0.
- [ ] Tests added: `tests/test_macrostep.py::test_raised_event_precedes_pending_external`, `::test_raise_chain_settles_before_external`, `::test_raise_interleaves_with_always`, `::test_raise_guard_still_bounds_self_feeding_chain`, `tests/test_sync_interpreter.py::test_sync_raise_precedes_external`.

## Related

- LC-06 (over-forgiving target resolution) and LC-18 (event ordering not preserved across defer/drain) — both also touch `_run_event_loop` ordering. Filed separately.

## Verification

Independently re-verified on **2026-09-15**.

- Python 3.13.7, `xstate-statemachine` 0.7.0, commit `42612cf`, editable install.
- `repro/LC-05_raise-not-macrostep.py` run in a fresh process: **exit code 1**.
  Observed `['entry', 'EXTERNAL', 'RAISED']` vs expected `['entry', 'RAISED', 'EXTERNAL']` — matches the Observed section verbatim. Re-run 5× with identical output (deterministic, not a race).
- Root cause confirmed against source: single `asyncio.Queue` at `interpreter.py:129`; `send` puts at `:375`; `_deliver` self-delivery detection at `:803-806`; single `await self._event_queue.get()` at `:427` inside `_run_event_loop` (`:406`). No internal queue exists anywhere in the package.
- Expected behaviour re-checked against https://stately.ai/docs/actions#raise-action; the quote now reproduces the docs verbatim. The previously quoted wording was a paraphrase and has been replaced.
- No duplicate: the upstream tracker has one issue total (#17, closed, unrelated — camelCase/snake_case action auto-discovery).
