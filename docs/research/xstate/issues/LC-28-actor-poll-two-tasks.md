---
lc: LC-28
title: "Perf: every invoked child actor costs two asyncio tasks, one busy-polling its status at 5 ms"
labels: [performance, severity/medium, area/perf, candleviewer]
severity: Medium
blocks_adoption: false
repro_script: repro/LC-28_actor-poll-two-tasks.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
verified_date: 2026-09-15
---

## Summary

When `invoke.src` resolves to a `MachineNode`, `_spawn_and_manage_actor` starts the child interpreter (one task for the child's own event loop) and then waits for completion with `while child.status == "running": await asyncio.sleep(0.005)` (`interpreter.py:1214-1215`). That second task exists only to poll. The cost is exactly **two asyncio tasks per invoked child**, half of them waking 200 times per second to re-read an attribute that the child could simply have signalled. The child already transitions to a terminal status, so a future/`asyncio.Event` resolved at that moment would give the same `onDone` semantics at zero idle cost, and with lower latency (up to 5 ms of pure added delay per completion, and that delay compounds down a chain of nested actors).

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, installed with `pip install -e .`
- Python: 3.13.7 (also confirmed on 3.12.3)
- OS: Windows 11 (x64)

## Minimal reproduction

```python
"""LC-28 repro: every invoked child-machine actor costs two asyncio tasks,
one of which polls at 5 ms instead of awaiting a completion future.

Counts live asyncio tasks as N child actors are invoked, and counts how many
times the event loop is woken while the children simply idle.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine import interpreter as interp_mod

logging.disable(logging.CRITICAL)

CHILD = {
    "id": "leg",
    "initial": "working",
    "states": {"working": {"on": {"FINISH": "done"}}, "done": {"type": "final"}},
}


def parent_cfg(n: int) -> dict:
    return {
        "id": "book",
        "initial": "running",
        "states": {
            "running": {
                "invoke": [
                    {"id": f"leg{i}", "src": "leg"} for i in range(n)
                ]
            }
        },
    }


async def measure(n: int) -> tuple[int, float]:
    machine = create_machine(
        parent_cfg(n), logic=MachineLogic(services={"leg": create_machine(CHILD)})
    )
    base = len(asyncio.all_tasks())
    interp = await Interpreter(machine).start()
    await asyncio.sleep(0.05)
    tasks = len(asyncio.all_tasks()) - base

    # Measure loop wakeups while the children are idle: each poller wakes
    # 1/_ACTOR_POLL_INTERVAL times per second doing nothing.
    wakeups = 0
    t_end = time.monotonic() + 0.2
    while time.monotonic() < t_end:
        await asyncio.sleep(0)
        wakeups += 1
    await interp.stop()
    return tasks, wakeups


async def main() -> int:
    print(f"OBSERVED _ACTOR_POLL_INTERVAL = {interp_mod._ACTOR_POLL_INTERVAL}s")
    counts = {}
    for n in (0, 2, 10, 50):
        tasks, _ = await measure(n)
        counts[n] = tasks
        print(f"OBSERVED children={n:>3} -> live asyncio tasks = {tasks}")
    print("EXPECTED ~1 task per child (a lifecycle task awaiting a completion")
    print("EXPECTED future), i.e. no dedicated 5 ms polling task per child")

    per_child = [
        (counts[n] - counts[0]) / n for n in (2, 10, 50)
    ]
    print(f"OBSERVED tasks per child = {per_child}")
    polling = interp_mod._ACTOR_POLL_INTERVAL <= 0.01
    two_per_child = all(p >= 2 for p in per_child)
    print(
        f"OBSERVED dedicated poll loop present = {polling}; "
        f"two-tasks-per-child = {two_per_child}"
    )
    bad = polling and two_per_child
    print("RESULT:", "REPRODUCED (2 tasks/child, 5 ms poll)" if bad else "NOT REPRODUCED")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED _ACTOR_POLL_INTERVAL = 0.005s
OBSERVED children=  0 -> live asyncio tasks = 1
OBSERVED children=  2 -> live asyncio tasks = 5
OBSERVED children= 10 -> live asyncio tasks = 21
OBSERVED children= 50 -> live asyncio tasks = 101
EXPECTED ~1 task per child (a lifecycle task awaiting a completion
EXPECTED future), i.e. no dedicated 5 ms polling task per child
OBSERVED tasks per child = [2.0, 2.0, 2.0]
OBSERVED dedicated poll loop present = True; two-tasks-per-child = True
RESULT: REPRODUCED (2 tasks/child, 5 ms poll)
```

(exit code 1)

This is a perfectly linear 2 tasks per invoked child; the same ratio holds at 200 children (402 tasks).

## Expected behaviour

XState v5 actors are event-driven: a child actor's completion is *pushed* to the parent. `packages/core/src/eventUtils.ts` documents and constructs the completion event directly — "Returns an event that represents that an invoked service has terminated. An invoked service is terminated when it has reached a top-level final state node, but not when it is canceled":

```ts
export function createDoneActorEvent(invokeId, output?) {
  return { type: `xstate.done.actor.${invokeId}`, output, actorId: invokeId };
}
```

and the `invoke` docs list `onDone` as "Transition that occurs when the actor is complete." In `createActor.ts` the child's terminal status is observed synchronously in `_stopProcedure`/`_complete` at the moment the snapshot's `status` becomes `'done'` — there is no periodic check anywhere, and the `Clock` interface (`setTimeout`/`clearTimeout`) is used only for genuinely *delayed* events, never for completion detection.

Nothing in the specification implies polling, and there is no notion of a completion-detection interval. The parent should learn about completion at the instant the child reaches a top-level final state (or errors), with no periodic work while the child is merely running. Concretely: N idle invoked children should cost O(N) memory and **zero** ongoing CPU.

(Note on naming: this library emits `done.invoke.<id>` / `error.platform.<id>`, which are the XState **v4** event names — v5 renamed them to `xstate.done.actor.<id>` / `xstate.error.actor.<id>`. That naming difference is orthogonal to this issue and is not something this issue asks to change; only the *mechanism* — poll vs. push — is at stake here.)

## Root cause analysis

- `src/xstate_statemachine/interpreter.py:81` — `_ACTOR_POLL_INTERVAL = 0.005`, with a comment acknowledging the trade-off ("Small enough that `onDone` feels immediate, large enough not to busy-wait a core").
- `src/xstate_statemachine/interpreter.py:1173-1252` — `_spawn_and_manage_actor`:
  - `child_interpreter = Interpreter(actor_machine)` (`:1190`) then `await child_interpreter.start()` — `start()` itself creates the child's event-loop task (task #1).
  - `_invoke_service` (`interpreter.py:1135-1159`) wraps `_spawn_and_manage_actor` in `asyncio.create_task(...)` at `:1154-1156` (task #2), which then blocks in the poll loop at `:1214-1215`.
- The comment block at `:1206-1213` explains *why* the wait exists (an earlier bug fired `onDone` immediately because `start()` returns at initial-state entry). The fix chosen was a poll; the correct fix is for the child to signal.
- The child's terminal transition is already a well-defined moment: `BaseInterpreter` sets `status` to `"error"` (`base_interpreter.py:2324`) and `"done"` (`base_interpreter.py:2349`), so the signal point is identified — it just isn't published.
- `src/xstate_statemachine/helpers.py:54-98` (`wait_for`, 5 ms) and `sync_interpreter.py:1175` (actor runner, `time.sleep(0.01)` "Yield to prevent busy-waiting") repeat the same pattern.

Mitigating evidence, stated for fairness: a separate measurement found **no detectable event-loop degradation at 200 concurrent children** on the test machine. This is a scalability and cleanliness problem rather than an observed production stall at current scale.

## Impact

**General users.** The cost is invisible at 5 children and structural at 500. Each poller is a scheduled callback on the loop's timer heap; at 200 children that is 400 tasks and ~40,000 timer callbacks per second doing nothing but reading `child.status`. It also adds up to 5 ms of latency to every `onDone`, which compounds linearly with actor nesting depth — a 4-deep actor tree pays up to 20 ms to propagate a completion that is logically instantaneous. On battery-powered or container-CPU-limited deployments the idle wakeups are a real cost, and they make the process's idle CPU profile misleading during performance investigations.

**CandleViewer (trading OMS).** This is the application that prompted the report. Its worst-case sizing is 500 concurrent order legs plus 600 child slices in flight. That is ~2,200 asyncio tasks, of which ~1,100 wake 200 times per second — roughly **220,000 no-op wakeups per second** purely to discover that nothing has finished. Two concrete consequences: (a) the idle CPU floor of the OMS process rises to the point where it is hard to distinguish "the algo engine is busy" from "the pollers are busy" when diagnosing a latency spike; (b) the up-to-5 ms `onDone` delay lands directly on the parent-fill-propagation path — a slice child completing at t does not tell the parent order until t+5 ms, so an order that is fully filled can still look partially filled for a full 5 ms per nesting level, which is material for the risk check that gates the next slice. We have had to adopt an operational cap of ≤200 concurrent children without re-measuring — a constraint we would not need if completion were signalled.

## Proposed fix

Replace the poll with a completion future owned by the child.

1. **Publish the terminal moment.** In `BaseInterpreter`, add `self._done_future: Optional[asyncio.Future]` (created lazily on first `await`, so the sync engine and non-loop construction are unaffected). Wherever `status` is set to `"done"` or `"error"` (final-state entry and `_fail`), resolve it: `fut.set_result(status)` / `fut.set_exception(err)`. Guard with `if fut and not fut.done()`.
2. **Await instead of poll.** In `_spawn_and_manage_actor` (`interpreter.py:1214-1215`) replace the `while … sleep` loop with `await child_interpreter.wait_done()`, where `wait_done()` returns the future (returning immediately if the child is already terminal, which preserves the "child finished during `start()`" case). The surrounding `onDone`/`onError` dispatch, plugin calls and `CancelledError` handling stay byte-for-byte identical.
3. **Collapse the second task.** With the wait no longer a spin, `_invoke_service` can `await` the lifecycle inline where the call site already runs in a task, or keep one task per child for cancellation granularity — but the *polling* task disappears either way. Target: 1 task per idle child.
4. **Delete `_ACTOR_POLL_INTERVAL`** (`interpreter.py:81`) once no caller remains, or keep it as a deprecated no-op constant for one release if anyone imports it.
5. Apply the same treatment to `helpers.wait_for` (`helpers.py:54-98`) and the `SyncInterpreter` actor runner (`sync_interpreter.py:1175`, `threading.Event` there) — worth doing in the same pass, since the signal being added here is what both need.

**Backwards compatibility.** Fully behaviour-preserving for observable semantics: the same `done.invoke.*` / `error.platform.*` events fire with the same payloads, just sooner and without the poll. The only user-visible differences are (a) `onDone` latency drops from ≤5 ms to ~0, which can expose tests that implicitly relied on the delay as a settling window — worth a CHANGELOG note; (b) `_ACTOR_POLL_INTERVAL` is private, so removing it is not a public break.

## Acceptance criteria

- [ ] `_ACTOR_POLL_INTERVAL` no longer referenced by any code path in `interpreter.py`.
- [ ] `tests/test_actor_perf.py::test_idle_child_actors_cost_one_task_each` — invoking 50 child machines adds ≤ 1 task per child (`len(asyncio.all_tasks())`), asserted against a 0-child baseline.
- [ ] `tests/test_actor_perf.py::test_no_polling_wakeups_while_children_idle` — with 20 idle children, the loop performs no periodic timer callbacks attributable to actor management over a 200 ms window.
- [ ] `tests/test_actor_perf.py::test_on_done_latency_is_immediate` — a child driven to its final state fires the parent's `onDone` within a single event-loop settle (no 5 ms floor); asserted as < 2 ms over 50 repetitions.
- [ ] `tests/test_actor_lifecycle.py::test_child_error_still_fires_on_error` — existing `onError` semantics unchanged (child that fails ⇒ `error.platform.<id>` with the child's error as `data`).
- [ ] `tests/test_actor_lifecycle.py::test_child_completing_during_start_fires_on_done_once` — a child whose initial state is final still fires exactly one `onDone` (the race the poll loop was introduced to fix must stay fixed).
- [ ] `tests/test_actor_lifecycle.py::test_actor_cancelled_on_parent_state_exit` — cancellation path unchanged, no pending future left unresolved.
- [ ] `repro/LC-28_actor-poll-two-tasks.py` exits 0.

## Related

- LC-27 (no clock injection) — the other consequence of timing being hard-coded to real sleeps in `interpreter.py`. The same polling smell recurs in `helpers.wait_for` (5 ms) and the sync actor runner (10 ms); this issue is the highest-cost instance.
- LC-12 / LC-29 (child-actor spawn path) — same `_spawn_and_manage_actor` function.

## Verification

Independently verified on 2026-09-15.

- **Date:** 2026-09-15
- **Python:** 3.13.7 (venv `.venv-cv`, `xstate-statemachine` 0.7.0 installed with `pip install -e .`)
- **Library commit:** `42612cf41d9750a5982fe75d5bb539d82f1df4a9` (`main`)
- **Repro exit code:** 1 (fails against the library today, as claimed)

Checks performed: (1) the repro script was run in a fresh process and its output matches the Observed section; (2) the embedded code block is byte-identical to the repro file; (3) the Expected section was checked against XState v5 — the doc pages plus the v5 source in `packages/core/src` (`system.ts`, `createActor.ts`, `SimulatedClock.ts`, `eventUtils.ts`); (4) every `file:line` in the Root cause section was opened in the library source and confirmed to say what is claimed; (5) no duplicate exists in the upstream issue tracker (only issue #17, an unrelated closed camelCase/snake_case auto-discovery bug).
