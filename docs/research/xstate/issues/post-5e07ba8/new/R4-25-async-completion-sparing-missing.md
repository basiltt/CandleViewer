---
r4: R4-25
title: "Docs: 'engine completions are never discarded' (#94) is implemented on the sync engine only"
labels: [documentation, bug, severity/medium, area/interpreter, area/sync-interpreter]
severity: Medium
repro_script: repro/R4-25_async_completion_sparing_missing.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

The library's own documentation (`json-config.md`/CHANGELOG, referencing
fix `#94`) states unconditionally, for "both engines", that engine
completions (e.g. `done.invoke.*`) are never discarded even when a
runaway/self-raise chain trips. `SyncInterpreter` implements this guarantee
by construction: it partitions the event queue into `spare`/`keep`/`victims`
sets specifically to protect completion events from being dropped when a
trip fires (`sync_interpreter.py:656-740`). `Interpreter` has no equivalent
partition at all — its trip handler (`interpreter.py:1173-1196`) simply
drops whatever event is at the head of the queue with no
`is_system_event`/completion check. In the specific construction tested
here the async engine happens to spare the completion anyway (because its
`_raise_depth` accounting spares it in this shape), but that is circumstance,
not a guarantee — and R4-06 (register row R4-06) separately proves the async
trip handler *does* drop events that land at its head in other shapes.

## Environment

- Commit: `5e07ba8` (unreleased 0.8.1; `__version__` reports 0.8.0)
- Python: 3.13.7
- Install: editable clone at `_ref/xstate-statemachine`, run via its
  `.venv-main` interpreter

## Current behaviour and why it is insufficient

```python
"""R4-25: the docs (#94) claim "engine completions are never discarded" by
a runaway/maxIterations trip, on BOTH engines. `SyncInterpreter` implements a
`spare`/`keep`/`victims` partition (sync_interpreter.py:656-740) that protects
completion events from being dropped when a trip fires. `Interpreter`
(interpreter.py:1173-1196) has no such partition: it drops whatever is at the
head of the queue with no `is_system_event`/completion check.

This script trips a runaway-chain guard while a `done.invoke` is in flight on
the async engine and asserts it is NOT dropped, matching the documented
guarantee. It currently reproduces only "by circumstance" (accounting in
_raise_depth happens to spare it in this exact shape) -- so this file is
kept as a semantic regression guard: it exits 1 if the async engine ever
drops the completion in this construction, and can be strengthened later to
target the code path R4-06 shows DOES drop events at the trip head.
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(
    0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src"
)
from xstate_statemachine import create_machine, MachineLogic, Interpreter  # noqa: E402

CFG = {
    "id": "m",
    "maxIterations": 5,
    "initial": "a",
    "states": {
        "a": {
            "invoke": {"id": "svc", "src": "svc", "onDone": {"target": "ok"}},
            "on": {"SPIN": {"actions": [{"type": "raise", "params": {"event": "SPIN"}}]}},
        },
        "ok": {},
    },
}


async def svc(i, c, e):
    await asyncio.sleep(0.25)
    return {"v": 1}


async def main() -> int:
    i = Interpreter(create_machine(CFG, logic=MachineLogic(services={"svc": svc})))
    await i.start()
    await i.send("SPIN")  # runaway; trip fires while svc is in flight
    await asyncio.sleep(1.5)
    delivered = "m.ok" in i.current_state_ids
    print(f"OBSERVED: final state={sorted(i.current_state_ids)} delivered={delivered}")
    print(
        "EXPECTED: done.invoke DELIVERED (per #94/json-config.md/CHANGELOG: "
        "'engine completions are never discarded', documented for both engines, "
        "but only the sync engine implements the sparing partition that "
        "guarantees this by construction)"
    )
    await i.stop()
    return 0 if delivered else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

Output (this construction happens to deliver on this build, which is the
crux of the problem: it looks safe until the shape changes):

```
ERROR:xstate_statemachine.interpreter:🛑 Exceeded 5 chained self-raised events on 'm'. This means an action raises the event that triggers it. Breaking the chain; externally queued events are unaffected.
OBSERVED: final state=['m.ok'] delivered=True
EXPECTED: done.invoke DELIVERED (per #94/json-config.md/CHANGELOG: 'engine completions are never discarded', documented for both engines, but only the sync engine implements the sparing partition that guarantees this by construction)
```

`done.invoke` is delivered here, but only because `Interpreter`'s trip
handler happens not to land on the completion event's queue position in
this particular shape — there is no code path that *guarantees* it, unlike
the sync engine's explicit `spare`/`keep`/`victims` partition. R4-06 shows
the async trip handler drops arbitrary head-of-queue events in other
shapes, which is the exact category `#94` claims is protected.

## Root cause analysis

- `sync_interpreter.py:656-740` — `SyncInterpreter`'s trip handler computes
  `spare = is_completion and not tripped` and partitions the pending queue
  into `keep`/`victims`, explicitly sparing completion events (`done.*`,
  `error.*`) from being dropped by a chain trip.
- `interpreter.py:1173-1196` — `Interpreter`'s equivalent trip handler has
  no such partition: it drops whatever event is at the head of the queue
  unconditionally, with no `is_system_event`/completion check at all.
- `json-config.md` and the CHANGELOG both describe the "completions are
  never discarded" guarantee unconditionally, without qualifying it to the
  sync engine.

## Impact

Documentation states a safety guarantee ("engine completions are never
discarded") that a user of the async engine cannot actually rely on: the
async engine currently *happens* to deliver completions in some runaway-trip
shapes and (per R4-06) *does* drop events at the trip head in others. For a
long-running order-management-style service using the async engine, a
`done.invoke` carrying a fill confirmation that races a runaway/self-raise
chain trip has no structural guarantee of delivery, contrary to what the
docs promise.

## Proposed fix

Port the `spare`/`keep`/`victims` completion-sparing partition from
`sync_interpreter.py:656-740` to the equivalent trip handler in
`interpreter.py:1173-1196`, so both engines honor the same guarantee by
construction. Until that lands, qualify the documented guarantee in
`json-config.md`/CHANGELOG to state it applies to the sync engine only.

## Acceptance criteria

- [ ] `Interpreter`'s runaway/chain-trip handler spares completion events
      (`done.*`, `error.*`) from being dropped, matching
      `SyncInterpreter`'s `spare`/`keep`/`victims` partition.
- [ ] A test named `test_async_trip_spares_completion_events` (or
      equivalent) exists under `tests/`, covering the same shape R4-06 uses
      to show the async trip handler drops head-of-queue events.
- [ ] Documentation in `json-config.md`/CHANGELOG accurately reflects engine
      parity (or lack thereof) for this guarantee.

## Related

- Register row R4-25 (filed Medium, stands as filed on re-triage).
- Source: `probes/main-5e07ba8/r31_async_completion_drop.py`.
- Related to R4-06 (async trip handler drops head-of-queue events in other
  shapes) and R4-21 (sync/async invoke completion timing divergence).

## Verification

- Date: 2026-09-19
- Python: `.venv-main` interpreter, version 3.13.7
- Commit: `5e07ba8` (unreleased 0.8.1; `__version__` reports 0.8.0)
- Ran `repro/R4-25_async_completion_sparing_missing.py` fresh, standalone:
  exit code `0`, output matched the doc's own "Output (this construction
  happens to deliver...)" section verbatim, including the
  `final state=['m.ok'] delivered=True` line and the "Exceeded 5 chained
  self-raised events" log line. This is the documented, expected result for
  this script — the doc explicitly frames it as "kept as a semantic
  regression guard" that currently passes "by circumstance", not as a
  script that must exit 1; the actual defect is structural (absence of a
  sparing partition), independently confirmed below.
- Confirmed root-cause lines: `sync_interpreter.py:656-740` contains the
  `is_completion = is_generated and is_system_event(current_event)`
  spare/keep/victims partition guarding completion events from the trip's
  drop logic. `interpreter.py:1173-1196` (the `_raise_depth > limit` branch)
  drops whatever event is at the head of the queue via
  `plugin.on_event_dropped(self, event, "chain_budget")` with no
  `is_system_event`/completion check anywhere in that branch — confirmed by
  reading the surrounding code; there is no equivalent partition.
- The docs claim checked: `json-config.md`/CHANGELOG's "#94" language states
  the "completions are never discarded" guarantee without qualifying it to
  one engine (confirmed by the sync-only partition above being the sole
  enforcement mechanism in the codebase). This is a same-repo documentation
  claim, not an external XState/SCXML claim, so no external URL fetch
  applies; SCXML/XState do not mandate this specific runaway-chain-budget
  behavior, since it is a library-specific safety feature, not part of the
  standard.
- No project name/label leak found. No duplicate found; `gh issue list`
  search for "invoke completion" surfaced #94 (a different, already-closed
  defect: sync engine dropping a completion that was misclassified as
  self-generated) which is the fix this finding says exists only for the
  sync engine and has no async counterpart — confirming rather than
  duplicating this finding.
