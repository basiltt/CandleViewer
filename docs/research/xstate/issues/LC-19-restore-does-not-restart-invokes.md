---
lc: LC-19
title: "Feature: restore does not restart invokes or re-run entry actions - parked machines report `running`"
labels: [enhancement, severity/high, area/persistence, candleviewer]
severity: High
blocks_adoption: false
repro_script: repro/LC-19_restore-does-not-restart-invokes.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

`from_snapshot()` performs a static restoration: it reinstates the configuration, context and history, but does not restart `invoke`d services and does not re-run the restored states' `entry` actions. A machine snapshotted while an `invoke` was in flight comes back reporting `status == "running"` and sitting in the invoking state, with nothing in flight and no event that can ever arrive to move it on. The limitation is documented in the docstring, but the library offers no opt-in to restart services and no API to *discover* which restored states have dormant invokes — so every application must walk the machine tree itself to find its own parked actors.

## Environment

- Library: xstate-statemachine 0.7.0, commit `42612cf` (local clone, `pip install -e .`)
- Python: 3.13.7
- OS: Windows-11-10.0.26200-SP0

## Minimal reproduction

```python
"""LC-19 - restoring a snapshot taken mid-`invoke` produces a parked machine.

An order machine is snapshotted while `submitting` has a live `invoke` in
flight. After `from_snapshot(...).start()` the machine reports
`status == "running"` and sits in `o.submitting`, but the service was never
restarted and `submitting`'s entry actions never re-ran: nothing will ever
drive it to `submitted`.
"""

from __future__ import annotations

import asyncio
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

calls = {"place": 0, "entry": 0}


async def place(interp, ctx, evt):  # noqa: ANN001
    calls["place"] += 1
    await asyncio.sleep(5)  # request in flight when the snapshot is taken
    return {"ok": True}


def on_entry(interp, ctx, evt, action):  # noqa: ANN001
    calls["entry"] += 1


CFG = {
    "id": "o",
    "initial": "submitting",
    "states": {
        "submitting": {
            "entry": ["on_entry"],
            "invoke": {"id": "place", "src": "place", "onDone": "submitted"},
        },
        "submitted": {},
    },
}
LOGIC = MachineLogic(actions={"on_entry": on_entry}, services={"place": place})


async def main() -> int:
    interp = await Interpreter(create_machine(CFG, logic=LOGIC)).start()
    await asyncio.sleep(0.1)
    snapshot = interp.get_snapshot()
    await interp.stop()
    print(f"OBSERVED pre-crash : state={sorted(interp.current_state_ids)} "
          f"place_calls={calls['place']} entry_calls={calls['entry']}")

    calls["place"] = calls["entry"] = 0
    restored = Interpreter.from_snapshot(snapshot, create_machine(CFG, logic=LOGIC))
    await restored.start()
    await asyncio.sleep(0.3)
    print(f"OBSERVED restored  : state={sorted(restored.current_state_ids)} "
          f"place_calls={calls['place']} entry_calls={calls['entry']} "
          f"status={restored.status!r}")
    print("OBSERVED no API reports that `o.submitting` has an invoke that is not running")
    print("EXPECTED restored  : the `place` invoke is restarted (place_calls >= 1) "
          "under an opt-in flag, or an API enumerating stalled invokes so the "
          "application can re-drive them")
    await restored.stop()
    return 1 if calls["place"] == 0 else 0


sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED pre-crash : state=['o.submitting'] place_calls=1 entry_calls=1
OBSERVED restored  : state=['o.submitting'] place_calls=0 entry_calls=0 status='running'
OBSERVED no API reports that `o.submitting` has an invoke that is not running
EXPECTED restored  : the `place` invoke is restarted (place_calls >= 1) under an opt-in flag, or an API enumerating stalled invokes so the application can re-drive them
(exit code 1)
```

This is reproducible on every run: the restored machine performs zero service calls and zero entry actions while reporting `status='running'`. The same restore path also drops pending `after` timers (LC-20).

## Expected behaviour

In XState v5, restoring a persisted snapshot with `createActor(machine, { snapshot })` **does** rehydrate invoked actors. The persistence page is explicit on both halves of this issue's behaviour in a single sentence (https://stately.ai/docs/persistence#restoring-state):

> Actions from machine actors will *not* be re-executed, because they are assumed to have been already executed. However, invocations will be restarted, and spawned actors will be restored recursively.

So XState agrees with this library that entry actions are correctly *not* re-run — the state was already entered — but it takes the opposite position on services: "invocations will be restarted" is the default, not an opt-in. The same page reinforces it under deep persistence: "Persisting & restoring state from machine actors is deep; all invoked & spawned actors will be persisted and restored recursively."

XState's own listed caveats (https://stately.ai/docs/persistence#caveats) are incompatible state, non-re-executed actions, and serialisability — none of them covers the whole invoke surface silently going dark. Note this issue asks only for an opt-in flag plus an inspection API, which is *weaker* than XState's default, because re-invoking a non-idempotent service is a genuine hazard this library's users have not been warned about.

## Root cause analysis

- `src/xstate_statemachine/base_interpreter.py:815-958` — `from_snapshot` reconstructs `_active_state_nodes`, `context`, `status`, `_history`, `_system` and child actors from the snapshot dict, then returns at `:958`. There is no traversal of the restored configuration looking for `StateNode.invoke`.
- `src/xstate_statemachine/base_interpreter.py:828-831` — the docstring documents the gap: *"This method performs a static restoration. It does not re-run entry actions of the restored states or restart any invoked services or `after` timers that were active when the snapshot was taken."* So this is a known limitation rather than an accident — but it is documented only in the method docstring, and the `status` field reported afterwards still says `running`.
- The machinery to start invokes already exists and is entirely reusable: `interpreter.py:1135` (`_invoke_service`) dispatches to `_spawn_and_manage_actor` (`:1173`) or `_invoke_service_task` (`:1042`), registering each task with `task_manager` under an owner id (`:1158`, `:1171`). Nothing calls it on the restore path.
- Consequence for `status`: `restored.status == "running"` is assigned verbatim from the snapshot's `status` field at `base_interpreter.py:874`, so a parked machine is indistinguishable from a healthy one via the public API.

## Impact

**General users:** any process that persists machines across restarts — a job runner, a workflow engine, a saga coordinator — restores a fleet of actors that look alive and do nothing. Because the happy path (no crash) works perfectly, this passes every test that does not kill the process mid-invoke. The failure is discovered in production, at the worst time, as "stuck" work items.

**CandleViewer (trading OMS):** this is the highest-consequence persistence gap we found.
- An order machine restored in `submitting` has no HTTP request in flight. The exchange may well have accepted the order — the position exists on the exchange while the machine believes a submission is pending, and no `FILLED` event will ever be produced by the machine's own service.
- A reconciliation machine restored in `fetching` runs no sweep, so the very mechanism that would detect the orphaned order above is itself dormant.
- A TWAP machine restored in `armed` has no deadlines (compounded by LC-20) and silently stops slicing.
- LC-17 is a direct consequence: our persisted deferral buffer is drained in `submitted`'s `entry`, and `submitted` is reachable only via `done.invoke.place` — an invoke that is never restarted — so the buffered fills strand permanently. Fixing LC-19 removes the blocker status of LC-17.

All three machines report `running` to the health endpoint throughout. Our boot procedure exists solely to work around this: on startup we walk every restored machine, hard-coding a list of which states have invokes, and re-drive them by hand — knowledge that has to be kept in sync with each machine definition manually, and that an inspection API would supply directly.

## Proposed fix

Two increments; the second is valuable even without the first.

**1. Opt-in service restart.**

```python
restored = Interpreter.from_snapshot(
    snapshot_str, machine, restart_services=True
)
```

Implementation: after `base_interpreter.py:958` finishes reinstating the configuration, iterate the restored `_active_state_nodes` and, for each node carrying `invoke` definitions, call the same `_invoke_service` path `_enter_states` uses (`interpreter.py:1135`), registering tasks with `task_manager` under the owning state id (as `:1158`/`:1171` already do) so exit-cancellation keeps working. Default `False` preserves today's behaviour exactly. The parallel flag `resume_timers=True` from LC-20 belongs in the same signature.

Semantics to document clearly: restarted services are **re-invoked from scratch, not resumed**, so the service must be idempotent — for an order placement that means a client-supplied idempotency key. This caveat is why the flag is opt-in rather than the default.

**2. An inspection API, unconditionally.**

```python
for stalled in restored.pending_invocations():
    # stalled.state_id, stalled.invoke_id, stalled.src
    ...
```

Returns the invoke definitions that are part of the restored configuration but have no live task. This lets an application re-drive them on its own terms (check the exchange first, *then* decide) without walking `machine.states` itself, and gives health checks a truthful signal. Consider also making `status` reflect it, or adding `is_fully_live` / a warning log at restore time listing the dormant invokes — anything that stops a parked machine from reporting `running` with no qualification.

Backwards compatibility: both additions are purely additive; no existing behaviour changes unless a caller passes the new flag.

## Acceptance criteria

- [ ] `repro/LC-19_restore-does-not-restart-invokes.py` exits 0 (with the script updated to pass `restart_services=True`).
- [ ] `tests/test_persistence.py::test_from_snapshot_restart_services_reinvokes_active_invocations`.
- [ ] `tests/test_persistence.py::test_from_snapshot_default_does_not_restart_services` — pins the existing default.
- [ ] `tests/test_persistence.py::test_restarted_invoke_is_cancelled_on_state_exit` — restarted tasks are owner-registered with `task_manager`, so leaving the state still cancels them (otherwise the fix leaks tasks).
- [ ] `tests/test_persistence.py::test_pending_invocations_lists_dormant_invokes_after_static_restore` and `::test_pending_invocations_is_empty_after_restart_services`.
- [ ] `tests/test_engine_conformance.py::test_restart_services_behaves_identically_on_both_engines`.
- [ ] `docs/_guide/snapshots.md` documents the flag, the "re-invoked, not resumed" idempotency caveat, and `pending_invocations()`; the `from_snapshot` docstring note at `base_interpreter.py:828-831` points at them.

## Related

- LC-20 (grouped): restore does not resume pending `after` timers — same restore path, same proposed signature (`resume_timers=True`).
- LC-17: the persisted deferral buffer is never drained after a crash — stranded *because* the invoke that leads to the draining state is never restarted. LC-19 is its root cause.
- LC-21 / LC-23 (grouped): no snapshot schema version or machine hash.
- LC-50: the snapshot cannot answer "how did this order get here?".

## Verification

Independently verified on 2026-09-15.

- **Repro run:** `repro/LC-19_restore-does-not-restart-invokes.py` executed in a fresh process against a clean `pip install -e .` checkout; exit code **1** (fails against the library today). The "Observed behaviour" block above matches the real output of that run.
- **Library:** xstate-statemachine 0.7.0, commit `42612cf`; Python 3.13.7; Windows-11-10.0.26200-SP0.
- **Root cause:** every cited `file:line` was opened and confirmed to contain the quoted code.
- **XState claims:** checked against the live stately.ai pages cited in the Expected section.
- **Duplicates:** `gh issue list --state all` shows one unrelated issue (#17, camelCase action auto-discovery); this is not a duplicate.
