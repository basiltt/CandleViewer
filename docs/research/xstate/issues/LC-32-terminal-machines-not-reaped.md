---
lc: LC-32
title: "Improvement: terminal machines are not reaped — a `done` interpreter keeps its children, tasks, context and registry entry"
labels: [enhancement, severity/medium, area/interpreter, candleviewer]
severity: Medium
blocks_adoption: false
repro_script: repro/LC-32_terminal-machines-not-reaped.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

When a machine reaches a top-level final state, `BaseInterpreter._complete()` (`base_interpreter.py:2335`) sets `status = "done"`, records `output` and fires the plugin `on_done` hooks — and does nothing else. No teardown happens: the context is retained in full, spawned child actors keep *running* (their event loops, `after` timers and invoked services are still scheduled), and the actor-system registry entry survives. The interpreter is semantically finished but physically alive.

Worse, the registry entry is never removed by an explicit `stop()` either: `_register_in_system()` (`base_interpreter.py:1417`) writes into the shared registry, and the *only* code anywhere in `src/` that removes an entry is the `stopChild` built-in (`interpreter.py:885`, `sync_interpreter.py:1006`). There is no general deregistration on the stop path, so unless every actor is torn down via an explicit `stopChild` action, `root.system.get_all()` grows monotonically for the lifetime of the root interpreter, holding strong references to stopped children. Any application that creates short-lived machines must hand-roll a reaper.

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, installed with `pip install -e .`
- Python: 3.13.7
- OS: Windows 11 (x64)

## Minimal reproduction

```python
"""LC-32 repro: terminal machines are not reaped.

When a machine reaches a top-level final state, `BaseInterpreter._complete()`
(base_interpreter.py:2335) sets `status = "done"`, records `output`, fires the
plugin `on_done` hooks — and stops. No teardown is performed. Concretely:

  1. `context` is retained in full (nothing is released).
  2. Spawned child actors keep RUNNING: their event loops, `after` timers and
     invoked services are still scheduled on the asyncio loop.
  3. The actor-system registry entry survives — and is *never* removed, not
     even by an explicit `stop()`, so `interpreter.system` grows monotonically
     for the lifetime of the root.

Nothing is released until the owner explicitly calls `stop()`, and even then
the system registry is left dirty. A fleet of short-lived machines therefore
requires an application-level reaper.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

# A child that stays busy: a long `after` timer keeps its loop and timer task
# alive, standing in for a real invoked service (an exchange poll, a stream).
CHILD = {
    "id": "leg",
    "initial": "work",
    "states": {
        "work": {"after": {100_000: {"target": "fin"}}},
        "fin": {"type": "final"},
    },
}

SPAWN = {"type": "spawn_leg", "params": {"id": "legA", "systemId": "legsys"}}

CFG = {
    "id": "order",
    "initial": "pending",
    "context": {"blob": None},
    "states": {
        "pending": {"entry": [SPAWN], "on": {"FILL": "filled"}},
        "filled": {"type": "final"},
    },
}


async def main() -> int:
    ok = True
    machine = create_machine(
        CFG, logic=MachineLogic(services={"leg": create_machine(CHILD)})
    )
    interp = Interpreter(machine)
    interp.context["blob"] = ["x"] * 50_000  # something worth reclaiming
    await interp.start()
    await asyncio.sleep(0.05)
    print(
        f"OBSERVED while running: actors={sorted(interp._actors)} "
        f"system={sorted(interp.system.get_all())}"
    )

    await interp.send("FILL")  # -> top-level final state
    await asyncio.sleep(0.15)

    tasks_live = len([t for t in asyncio.all_tasks() if not t.done()])
    child = next(iter(interp._actors.values()), None)
    print(f"OBSERVED status={interp.status!r} is_running={interp.is_running}")
    print(f"OBSERVED context retained: len(blob)={len(interp.context['blob'])}")
    print(f"OBSERVED actors after done  = {sorted(interp._actors)}")
    print(
        f"OBSERVED child after done: status="
        f"{child.status if child else None!r} event_loop_done="
        f"{child._event_loop_task.done() if child else None}"
    )
    print(f"OBSERVED system registry after done = "
          f"{sorted(interp.system.get_all())}")
    print(f"OBSERVED live asyncio tasks after done = {tasks_live}")

    leaked_on_done = bool(interp._actors) or (
        child is not None and child.status == "running"
    )

    await interp.stop()
    await asyncio.sleep(0.05)
    print(f"OBSERVED after explicit stop(): actors={sorted(interp._actors)} "
          f"system={sorted(interp.system.get_all())}")
    leaked_after_stop = bool(interp.system.get_all())

    print(
        "EXPECTED on reaching a top-level final state: child actors stopped, "
        "their tasks cancelled, system-registry entries removed and context "
        "releasable — without the owner calling stop(); and stop() must in "
        "any case leave the system registry empty"
    )

    ok = leaked_on_done and leaked_after_stop
    print(
        "RESULT:",
        "REPRODUCED (done machine keeps children running; registry entry "
        "survives even stop())"
        if ok
        else "NOT REPRODUCED",
    )
    return 1 if ok else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED while running: actors=['order:legA'] system=['legsys']
OBSERVED status='done' is_running=False
OBSERVED context retained: len(blob)=50000
OBSERVED actors after done  = ['order:legA']
OBSERVED child after done: status='running' event_loop_done=False
OBSERVED system registry after done = ['legsys']
OBSERVED live asyncio tasks after done = 3
OBSERVED after explicit stop(): actors=[] system=['legsys']
EXPECTED on reaching a top-level final state: child actors stopped, their tasks cancelled, system-registry entries removed and context releasable — without the owner calling stop(); and stop() must in any case leave the system registry empty
RESULT: REPRODUCED (done machine keeps children running; registry entry survives even stop())
```

(exit code 1)

Note the two distinct defects visible in that output:

1. `status='done'` yet `actors=['order:legA']` and the child's `status='running'` with a live event-loop task — **completion performs no teardown**.
2. After a full, explicit `await interp.stop()`, `actors=[]` (correct) but `system=['legsys']` still holds a strong reference to the stopped child — **`stop()` leaves the registry dirty**.

## Expected behaviour

XState v5 treats reaching a top-level final state as *terminating the actor and cleaning up everything it owns*. From <https://stately.ai/docs/final-states>:

> "When a machine reaches the final state, it can no longer receive any events, and anything running inside it is canceled and cleaned up."

and, on the same page under "Top-level final states":

> "A top-level final state is a final state that is a direct child state of the machine. When the machine reaches a top-level final state, the machine will terminate. When a machine terminates, it can no longer receive events nor transition."

The child-actor half is stated at <https://stately.ai/docs/actors>:

> "A **spawned actor** is started in a [transition](transitions) and stopped either with a [`stop(...)` action](/docs/actions/#stop-action) or when its parent machine is stopped."

and:

> "Stops the root actor, actor system, and actors in the system"

(the comment on `actor.stop()` in the actors cheatsheet — note that stopping clears the *actor system*, which is precisely the registry this issue shows is never cleared).

So on `_complete()` the expected behaviour is: cancel the interpreter's own tasks (timers, invoked services), recursively stop every child actor, remove this actor and its descendants from the actor-system registry, drain the pending event queue, and leave `status = "done"` (distinct from `"stopped"`) with `output` readable. `stop()` on an already-`done` machine then becomes a no-op. Independently, actor deregistration from the system registry is expected on stop regardless of the completion path.

## Root cause analysis

- `src/xstate_statemachine/base_interpreter.py:2335-2359` — `_complete(output)` sets `self.status = "done"`, sets `self.output`, logs, and calls plugin `on_done` hooks. That is the entire body. It does not touch `self._actors`, `self.task_manager`, `self._event_queue` or the system registry.
- `src/xstate_statemachine/base_interpreter.py:2240-2242` (and the mirror at `sync_interpreter.py:799-801`) — the only call sites of `_complete()`, reached when a top-level final state is entered. So there is no other hook where reaping could be happening.
- `src/xstate_statemachine/interpreter.py:275-325` — `stop()` *does* do the right teardown (recursively stops `self._actors`, `task_manager.cancel_all()`, cancels `_event_loop_task`) and its own comment at line 284 even states the intent:

  > `# 🏛️ `done` and `error` are terminal but NOT torn down: reaching a top-level final state must still release child actors and tasks.`

  i.e. the idempotency guard is `if self.status in ("uninitialized", "stopped"): return`, which deliberately lets `stop()` run on a `done` machine — but nothing ever *calls* `stop()` on completion. The teardown exists and is simply never triggered.
- `src/xstate_statemachine/base_interpreter.py:1417-1438` — `_register_in_system(system_id, actor)` writes `registry[system_id] = actor` into the shared root registry (`_system_registry()`, line 1393). The only removal anywhere in `src/` is inside the `stopChild` built-in (`interpreter.py:880-886`, `sync_interpreter.py:1002-1007`), which deletes by identity scan; `stop()` itself never removes entries and there is no `_unregister_from_system()` helper. So every actor that declared a `systemId` and was *not* torn down via an explicit `stopChild` action is retained by the root for its whole lifetime. This is the reference-holding half of the leak, and it is why `ActorSystem.get_all()` (line 128) grows monotonically.
- Consistent with our own profiling: a `done` machine keeps its object and registry entry until an explicit `stop()` plus manual eviction from the registry; and a fleet of 2,854 interpreters retained ~8.8 MB after full teardown and a forced `gc.collect()` (~3.1 KB each). A follow-up measurement showed 0 live `Interpreter` objects and an empty `gc.garbage` in the *fully evicted* case, so that residual 8.8 MB is allocator-arena retention rather than a reference leak — but the registry defect above *is* a true reference leak whenever `systemId` is used and eviction is not hand-rolled.

## Impact

**General users.** Any program that creates machines per unit of work — a request, a job, a session — accumulates running child actors, live timer tasks and registry entries for every machine that has already finished. Because `status` reads `"done"` and `is_running` reads `False`, the machine *looks* reaped from the public API, so the leak is invisible until the process grows. The child actors are not merely retained, they are *executing*: their `after` timers keep firing and their invoked services keep polling on behalf of a machine that is semantically over, which can produce real side effects (network calls, writes) after completion. The only correct usage today is "always `await interpreter.stop()` in a `finally`, even on success" — undocumented, and still insufficient to clear the system registry.

**CandleViewer (a trading order-management system built on this library).** Order machines are the definition of a high-churn family: one interpreter per order, thousands per session, each terminating in `filled` / `cancelled` / `rejected`. Concretely:

- A parent order machine reaches `filled`; its spawned child *leg* actors — which poll the exchange for leg status via invoked services and hold peg re-price `after` timers — keep running. The OMS therefore continues sending exchange requests for an order it considers complete, and a leg timer can fire a re-price on a filled parent.
- `root.system.get_all()` is the natural place to look up an actor by `systemId` for routing fills; it instead grows without bound and returns stopped actors, so sibling routing can deliver a fill to a dead interpreter.
- The mitigation forced on us is an application-level supervisor that reaps completed interpreters, plus a live-machine-count metric alerting on monotonic growth — infrastructure whose only purpose is to compensate for the missing library-level teardown.

## Proposed fix

Make completion reap, and make stop deregister.

1. **Reap on completion.** Extract the teardown half of `Interpreter.stop()` into an overridable `_teardown()` and call it from `_complete()`:

   ```python
   # base_interpreter.py
   def _complete(self, output: Any) -> None:
       if self.status != "running":
           return
       self.status = "done"
       self.output = output
       for plugin in self._plugins:
           hook = getattr(plugin, "on_done", None)
           if callable(hook):
               hook(self, output)
       self._schedule_teardown()   # async engine: create_task; sync: inline
   ```

   `_teardown()` recursively stops child actors, calls `task_manager.cancel_all()`, clears `self._actors`, drains `self._event_queue`, and deregisters from the system registry — everything `stop()` does *except* setting `status = "stopped"`, so `"done"` and `output` remain observable. `Interpreter.stop()` becomes `if self.status == "done": return` (already torn down), preserving idempotency.

   Ordering matters: `on_done` plugin hooks and subscriber notification must run **before** teardown, so a subscriber reading `output` or `system` at completion sees a consistent snapshot.

2. **Deregister from the actor system.** Add the missing counterpart to `_register_in_system`:

   ```python
   def _unregister_from_system(self) -> None:
       registry = self._system_registry()
       for system_id in [k for k, v in registry.items() if v is self]:
           del registry[system_id]
   ```

   Call it from `_teardown()` (and hence from both `stop()` and `_complete()`), after the actor's own children have been stopped so descendants remove themselves first.

3. **Release context (opt-in).** Do *not* clear `context` by default — reading `interpreter.context` after completion is a legitimate and widely used pattern. Instead document that a `done` interpreter retains its context, and let the owner drop the reference. If a stronger guarantee is wanted, add `Interpreter(machine, release_context_on_done=True)` as a keyword-only opt-in.

**Backwards compatibility.** Item 1 changes observable behaviour: children that previously kept running after completion now stop. That is the XState-conformant behaviour and the current behaviour is very hard to depend on deliberately, but it is a behaviour change and should land in a minor version with a `CHANGELOG` note. Item 2 is a pure bug fix. Item 3 is additive and default-off. Code that already calls `stop()` in a `finally` keeps working unchanged (`stop()` on a torn-down `done` machine is a no-op).

## Acceptance criteria

- [ ] `BaseInterpreter._complete()` triggers teardown; `status` remains `"done"` (not `"stopped"`) and `output` stays readable afterwards.
- [ ] `BaseInterpreter._unregister_from_system()` exists and is called from teardown for both the completion and the explicit-`stop()` paths.
- [ ] `tests/test_reaping.py::test_child_actors_stopped_when_parent_reaches_final_state` — parent spawns a child with a long `after`; on the parent reaching a top-level final state the child's `status == "stopped"` and its event-loop task is done.
- [ ] `tests/test_reaping.py::test_timers_and_service_tasks_cancelled_on_completion` — no interpreter-owned asyncio task remains pending after completion.
- [ ] `tests/test_reaping.py::test_system_registry_empty_after_completion` — `root.system.get_all() == {}` once the root has completed.
- [ ] `tests/test_reaping.py::test_system_registry_empty_after_explicit_stop` — the LC-32 leak proper: a machine that is `stop()`ped without ever completing also leaves an empty registry.
- [ ] `tests/test_reaping.py::test_output_and_context_readable_after_completion` — `output` and `context` are still readable after teardown (no regression for the common read-result-after-done pattern).
- [ ] `tests/test_reaping.py::test_on_done_plugin_hook_runs_before_teardown` — a plugin's `on_done` sees children still registered.
- [ ] `tests/test_reaping.py::test_stop_after_done_is_noop` — calling `stop()` on a completed machine does not warn, raise, or double-cancel.
- [ ] `tests/test_reaping_sync.py` — the same registry and task assertions for `SyncInterpreter`.
- [ ] `tests/test_reaping.py::test_fleet_of_completed_machines_releases_references` — 1,000 spawn/complete cycles leave 0 live child `Interpreter` objects under `gc.get_objects()`.
- [ ] Docs gain a "Lifecycle: completion and teardown" section stating what `done` releases and what it retains.
- [ ] `repro/LC-32_terminal-machines-not-reaped.py` exits 0.

## Related

- LC-12 (spawn blocking the async engine) and LC-28 (actor poll loop uses two tasks) — same actor-lifecycle area of `interpreter.py`; the per-actor task count is what makes non-reaping expensive.
- LC-24 (queued events lost on crash) — teardown must decide what happens to a non-empty `_event_queue`; both issues touch queue drain semantics.
- LC-16 (`sendTo` by invoke id) — depends on the same `_system_registry()` that this issue shows is never cleaned, so a stale entry can shadow a live actor.
- LC-27 (no clock injection) — the child `after` timers that keep running after completion are exactly the timers LC-27 cannot control in tests.

## Verification

Independently re-verified by running the repro script in a fresh process against the local clone.

- Date: 2026-09-15
- Library: `xstate-statemachine` 0.7.0, commit `42612cf`
- Python: 3.13.7 (Windows 11 x64, venv `.venv-cv`, `pip install -e .`)
- Repro exit code: **1** (fails against the library as shipped)
- Observed output matches the "Observed behaviour" block above verbatim.
- Every `file:line` citation in "Root cause analysis" was re-read against the source at commit `42612cf` and corrected where it had drifted.
- The cited XState v5 documentation pages were re-fetched and every quotation was checked against the live text; quotes that could not be found verbatim were replaced with the actual wording.
- Checked against the project's issue tracker: not a duplicate of any existing open or closed issue.
