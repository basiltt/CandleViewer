---
r7: R7-02
title: "Bug: an EXTERNAL `send(..., priority=True)` is charged to the chain budget — 748 of 1500 external sends silently dropped as `reason=\"chain_budget\"`, `last_error` reads `None`"
labels: [bug, severity/blocker, area/interpreter, area/events]
severity: Blocker
engines: async `Interpreter`
repro_script: repro/R7-02_external_priority_charged_to_chain_budget.py
commit: 221ce7c
python: 3.13.7
verified: true
---

## Summary

An external producer calling the public `send(..., priority=True)` has its events
charged to the **chain budget** and silently shed. Measured on `221ce7c` with a
market-data-shaped producer (one send per 0.1 ms, a 0.5 ms `await` in the action):

```
priority=True  : sent=1500  processed=752   dropped=748   reasons=['chain_budget']
priority=False : sent=1500  processed=887   dropped=0     reasons={}
```

A burst producer loses more: `sent=3000 processed=1162 dropped=1838
reasons={'chain_budget'}`. The control — identical load, `priority=True` removed —
drops **zero**, which isolates the cause to the public priority lane itself.

## Why this contradicts the intended design

`_deliver_priority` (`interpreter.py:2287-2288`) charges the budget on
`self._processing`:

```python
if self._processing:
    self._raise_depth += 1
```

That decides provenance by **when the event arrived**, not by **who issued it**.
Every other enqueue path in the file still asks `_issued_from_own_action()`
(`interpreter.py:826`, `:854`, `:1206`). The public priority lane
(`interpreter.py:811-812`) therefore leaks onto the chain budget: an external
producer that happens to send while the loop is inside a macrostep is treated as a
self-generated chain and shed.

The run loop's own architecture note at `interpreter.py:1510-1516` promises the
opposite — that external traffic of any volume is never throttled.

## Why it is nearly invisible

The drop path resets `_raise_depth` / `_chain_tripped` (`interpreter.py:1596-1599`),
so `last_error` reads `None` afterwards and `status` stays `"running"`. The loss
surfaces **only** through the opt-in `on_event_dropped` hook. A caller not using
plugins sees a healthy machine that quietly processed half its input.

## Relationship to the invoke-cycle fixes in this release

This looks like the mirror image of the work done for the invoke-cycle issues.
Those concern completions produced *while processing*, and the WHO→WHEN change at
`:2287-2288` that implements them is precisely what leaks onto the public external
path. Stated together:

- self-generated work **escapes** the budget on the coroutine completion lane;
- external work is **charged** on the priority lane.

Same mistake, opposite halves: provenance has been replaced by timing.

## Suggested fix

Make the charge in `_deliver_priority` depend on provenance, not on `_processing`
— an explicit internal flag on the delivery, or a gate on
`_issued_from_own_action()` the way every other enqueue path already does.

(If provenance moves onto an explicit flag, note that `send_threadsafe(internal=True)`
becomes a load-bearing trust boundary rather than an informational one, and may
deserve a second look.)

## Refutations tested and failed

- **Not documented.** `send()`'s docstring promises ordering plus the
  `max_queue_size` exemption; nothing about the chain budget. No caveat in the
  README, docs or CHANGELOG.
- **Not API misuse.** Public kwarg / `send_priority()`, called on the owning
  thread, documented as fire-and-forget.
- **Not a burst artefact.** We built the non-burst probe specifically to refute
  the finding; it still loses 30 %.
- **No XState v5 parity.** v5 applies no chain budget to external `actor.send()`;
  its microstep guard covers raised and eventless transitions only.

## Environment

- `xstate-statemachine` @ `221ce7c` (unreleased 0.8.1; `__version__` reports `0.8.0`)
- CPython 3.13.7, Windows 11
- async `Interpreter`; producer on the owning loop, `maxIterations=25`

## Minimal reproduction

`repro/R7-02_external_priority_charged_to_chain_budget.py` — standalone, library
only, and it runs its own control (identical load with `priority=True` removed) in
the same process. **Exit code 1** means external sends were shed as
`chain_budget`; it exits 0 once the priority lane stops charging external traffic.

## Expected

Zero external sends dropped, exactly as the control run shows.

- **The library's own contract, quoted.** `interpreter.py:1510-1516`:

  > "An earlier version incremented whenever the queue was non-empty after
  > processing, which cannot tell a runaway `raise` from a merely busy producer —
  > 5,000 legitimate concurrent `send()` calls lost 3,999 of them. `_raise_depth`
  > counts only events this loop enqueued *while processing another event*, so
  > **external traffic of any volume is never throttled**."

  The measured behaviour is the precise failure that note says was fixed.
- **XState v5.** `actor.send()` is unthrottled; v5's microstep guard bounds raised
  and eventless (`always`) transitions only, never events delivered from outside
  the actor (<https://stately.ai/docs/actors>).

## Impact

**General.** Any producer that calls the public `send(..., priority=True)` while
the loop is inside a macrostep loses a large fraction of its events — 50 % in the
steady-state probe, 61 % in a burst — with `status="running"` and
`last_error is None`. The loss is visible only through the opt-in
`on_event_dropped` hook, so a caller not running plugins sees a healthy machine
that quietly processed half its input.

**Order-management scenario.** Market-data ticks and fill notifications are
exactly the priority-lane traffic this affects. Half the fills silently
disappearing means positions, average price and risk state diverge from the
venue's truth with no error anywhere — the machine reports healthy while its view
of the book is wrong.

## Acceptance criteria

- `test_external_priority_send_is_never_charged_to_chain_budget` — N external
  `send(..., priority=True)` calls issued while a macrostep is in flight are all
  processed, zero dropped with `reason="chain_budget"`; **parametrised over `def` /
  `async def` action kinds and over both `Interpreter` and `SyncInterpreter`**.
- `test_priority_lane_matches_non_priority_drop_count` — the control equivalence:
  same load with and without `priority=True` drops the same number (zero).
- `test_self_raised_chain_still_trips_with_external_priority_traffic` — the
  converse is not regressed: a genuine self-generated chain still raises
  `RunawayChainError` while external priority traffic flows.
- A drop attributed to `chain_budget` must never be reachable from a call that did
  not originate in an action — assert on provenance, not timing.

## Related

Deepens round-6 **#105** ("external `send()` issued while a macrostep is in flight
is charged to the self-raised chain budget and silently dropped", CLOSED) — this
is that exact defect resurfacing on the **public priority lane**, so it is a
regression of #105's fix rather than a new family. Also **#150**
(`send_threadsafe` and the self-send gate) and **#104** (silent drops on a
fire-and-forget send). The mirror image of **R7-01** / **#166**/**#167**/**#168**:
`_deliver_priority`'s WHO→WHEN change lets self-generated work escape the budget on
one lane while charging external work on this one.

Register source ids: `D7-concurrency-2`, `p1_priority_lane_charged`,
`p1b_priority_realistic_producer`, `p1c_control_nonpriority`; `p9` (`after`-timer
charged mid-step) folded in here as the same mechanism.

## Verification

- Date: 2026-09-20
- Python: 3.13.7 (CPython, Windows 11)
- Library: `221ce7c` (unreleased 0.8.1; `__version__` reports `0.8.0`)
- Command: `python repro/R7-02_external_priority_charged_to_chain_budget.py`
- Exit code: **1** (reproduced)
- Fresh output is quoted verbatim in the Summary above.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 220 --search "priority" / "maxIterations"` — #105 and #107 are CLOSED;
  no open duplicate.
