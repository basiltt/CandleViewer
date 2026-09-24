---
r7: R7-01
title: "Bug: an `async def` invoked service's completion is published on the public inbox lane, so every self-generated invoke cycle is unbounded — 27,722 service calls vs 23 for the identical chart with `def`, `last_error=None`"
labels: [bug, severity/blocker, area/interpreter, area/actors, area/events]
severity: Blocker
engines: async only (SyncInterpreter is correct; plain `def` on async is also correct)
repro_script: repro/R7-01_async_service_lane_uncharged.py
commit: 221ce7c
python: 3.13.7
verified: true
---

## Summary

The chain budget bounds a self-generated invoke cycle when the service is written
as a plain `def`, and does not bound it at all when the **same service** is
written as an `async def`. Same chart, same `maxIterations`, one word changed:

```
maxIterations = 20, run = 2.0s, async Interpreter both times.

def       : service calls=23      status=running  last_error=RunawayChainError
async def : service calls=27722   status=running  last_error=None
```

`status` stays `"running"` and `last_error` stays `None` throughout, so nothing a
caller can observe distinguishes the runaway from healthy operation.

## Environment

- `xstate-statemachine` @ `221ce7c` (unreleased 0.8.1; `__version__` reports `0.8.0`)
- CPython 3.13.7, Windows 11
- async `Interpreter`; `SyncInterpreter` is correct, and so is `Interpreter` with a
  plain `def` service — the discriminating variable is **service kind**, not engine

## Root cause

Two publication paths exist for a service completion:

| Service kind | Path | Charged? |
|---|---|---|
| plain `def` | `_finish_plain_service` → `self._deliver_priority(done_event)` (`interpreter.py:2690`) | **yes** — `_deliver_priority` (`:2287-2288`) does `if self._processing: self._raise_depth += 1` |
| `async def` | `_invoke_service_task` → `await self.send(done_event)` (`interpreter.py:2414`) | **no** — never reaches `_deliver_priority` |
| child-actor `onDone` | same as above, at `interpreter.py:2882` | **no** |

A lane probe counting `done.invoke*` deliveries per lane over a ping-pong `a↔b`
chart at `maxIterations: 20`:

```
{"kind": "plain", "lanes": {"priority": 23, "inbox": 0},    "raise_depth": 0, "last_error": "RunawayChainError"}
{"kind": "async", "lanes": {"priority": 0,  "inbox": 27948}, "raise_depth": 0, "last_error": null}
```

This rules out the obvious hypothesis — it is **not** that `self._processing`
happens to be `False` when the coroutine resolves. The coroutine completion never
passes the charging site under *any* value of `_processing`, because it is
published on the public inbox lane.

**Second, compounding effect.** Arriving from the inbox, the completion also
satisfies the `from_inbox` disjunct at `interpreter.py:1647`
(`if not is_system_event(event) or from_inbox:`) and **resets**
`_settle_iterations` / `_settle_tripped` every lap. So the coroutine path is both
uncharged and actively budget-clearing — which is why `maxIterations` is inert:
2, 5, 25, 100 and 1000 all behave identically.

## Two consequences

**1 — a variant settles into an empty configuration and reports success.** With an
`async def` service, **10/10** runs: a resolved `await send("GO", wait=True)`
returns `ok=True, err=None, status="running"` with `current_state_ids == []`,
still empty 500 ms later. With a plain `def` service, 0/10. The sync engine keeps
a legal configuration on the identical chart. A `get_persisted_snapshot()` at that
instant is refused as `SnapshotMidStepError` — **the interpreter knows it is
mid-step while `send(wait=True)` has already reported the step finished
successfully.**

**2 — the `rollback` + `invoke.onDone` family is the same defect.** One word
changed: `{"kind": "plain", "svc_calls": 23, "last_error": "RunawayChainError"}`
versus `{"kind": "async", "svc_calls": 2783}`. On a realistic kill-switch machine,
one operator press produced **3 547 side-effecting service invocations in 3.0 s**,
still accelerating, `status="running"`, receipt `changed=True, error=None`.

## Why the test suite does not catch it

All three pinned regression tests for this family
(`tests/test_round6_findings.py:124/184/486`) declare `def svc(...)`.

**The single highest-value change in this release is one line:**

```python
@pytest.mark.parametrize("kind", ["def", "async def"])
```

on every test that invokes a service. Six independently-filed findings on our side
collapse into this one defect, and all six would have been caught by that
parametrisation before the fix shipped.

## Suggested fix

1. Publish coroutine-service and child-actor completions on the same charged lane
   the plain-`def` path uses: route `interpreter.py:2414` and `:2882` through
   `_deliver_priority` rather than `await self.send`.
2. Stop treating an engine completion that arrives `from_inbox` as external at
   `interpreter.py:1647`.

## Notes on alternative explanations we tested and discarded

- **Not the `is_system_event` exemption** — that line was already withdrawn as an
  explanation; the lane probe supersedes it.
- **Not API misuse** — `async def` is the style the documentation recommends
  (see the blocking-timer characteristics doc).
- **Not documented** — the docs present `maxIterations` as unconditional
  infinite-loop detection, with no service-kind caveat.
- **No XState v5 precedent** — v5 routes actor-done events through the same
  guarded microstep loop and never exposes an empty configuration while active.
- **No configuration mitigates it.** The only mitigation is plain `def` services,
  which the blocking-timer issue documents as blocking the machine's own `after`
  timers. There is currently no service kind that is safe on both axes.

## Minimal reproduction

`repro/R7-01_async_service_lane_uncharged.py` — standalone, library only, both
lanes in one script. **Exit code 1** means the unbounded coroutine cycle was
observed; it exits 0 once both service kinds are charged on the same lane.

## Expected

Both service kinds charged identically, both tripping `RunawayChainError` at the
same lap count.

- **The library's own contract.** `docs/api/index.md:1789` documents
  `RunawayChainError` as "a self-generated event chain exceeded `maxIterations`
  and was cut (#77, #103)" with no service-kind qualifier. The run loop's
  architecture note (`interpreter.py:1510-1516`) states `_raise_depth` "counts
  only events this loop enqueued *while processing another event*" — a coroutine
  service's completion is exactly such an event, and is not counted.
- **XState v5.** In v5 an invoked actor's `done.invoke.*` is delivered through the
  same internal event queue as any other actor-produced event and is processed
  within the macrostep loop regardless of whether the actor logic is promise-based
  or synchronous (`fromPromise` vs `fromTransition` — see
  <https://stately.ai/docs/actors>). v5 has no lane on which a promise actor's
  completion escapes the microstep guard.

## Impact

**General.** `maxIterations` — the library's only defence against a runaway
statechart — is inert for every machine whose services are written `async def`,
which is the style the documentation recommends. A cycle runs at tens of thousands
of laps per second with `status="running"` and `last_error is None`, so no
supervisor, health check or receipt can distinguish it from healthy operation.

**Order-management scenario.** A kill-switch machine whose `rollback` policy
re-arms an `invoke.onDone` turned one operator press into **3,547 side-effecting
service invocations in 3.0 s**, still accelerating — each of which is a real
order-management call. The empty-configuration variant is worse: `send("GO",
wait=True)` returns `ok=True, err=None` while `current_state_ids == []`, so an
order router believes its command succeeded and the machine has no active state to
act on.

## Acceptance criteria

- `test_invoke_cycle_is_bounded_by_max_iterations` — a self-generated
  `invoke.onDone` cycle trips `RunawayChainError` within `~maxIterations` laps,
  **parametrised over `["def", "async def"]` service kinds and over both
  `Interpreter` and `SyncInterpreter`**.
- `test_invoke_done_event_is_charged_to_chain_budget` — a lane assertion: a
  service completion produced while `_processing` increments `_raise_depth`
  regardless of service kind.
- `test_rollback_reinvoke_cycle_is_bounded` — the `actionErrorPolicy: "rollback"`
  + `invoke.onDone` shape (#167), same parametrisation.
- `test_configuration_never_empty_while_running` — `current_state_ids` is
  non-empty whenever `status == "running"` and a `send(wait=True)` has resolved.
- Retrofit `@pytest.mark.parametrize("kind", ["def", "async def"])` onto the
  existing pins at `tests/test_round6_findings.py:124/184/486`, which all declare
  `def svc(...)` and are therefore structurally blind to this lane.

## Related

Deepens the round-6 work: this is the same family as **#166**, **#167** and
**#168**, all closed against `221ce7c`. #168's stated root cause (the
`is_system_event` exemption at what was then `interpreter.py:1427`) is
**superseded** by the lane probe above — the coroutine completion never reaches
the charging site at all, under any value of `_processing`, because it is
published on the public inbox. #167's rollback shape reproduces unchanged with
`async def`. Also related: **#149** (plain-`def` services run inline and stall the
loop), which is why "use `def` services" is not an available mitigation, and
**#105**, whose provenance change is the mirror image (see R7-02).

Register source ids: `D7-fuzz-1`, `D7-fuzz-2`, `C221-01`, `LD-04` (supersedes
`LD-03`), `CV-221-01`, `LIB-R6-01`, `L-3`; `attack-K` (async half) passes only for
`def` services.

## Verification

- Date: 2026-09-20
- Python: 3.13.7 (CPython, Windows 11)
- Library: `221ce7c` (unreleased 0.8.1; `__version__` reports `0.8.0`)
- Command: `python repro/R7-01_async_service_lane_uncharged.py`
- Exit code: **1** (reproduced)
- Fresh output is quoted verbatim in the Summary above.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 220 --search "invoke onDone loop" / "maxIterations"` — nearest are
  #166/#167/#168, all CLOSED against this commit; no open duplicate.
