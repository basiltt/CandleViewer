---
lc: LC-12
title: "Semantics: `spawn_blocking_<key>` is silently ignored by the async Interpreter"
labels: [bug, severity/medium, area/actors, candleviewer]
severity: Medium
blocks_adoption: false
repro_script: repro/LC-12_spawn-blocking-async-engine.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

`SyncInterpreter` gives `spawn_blocking_<key>` a distinct meaning: the child actor is started inline and runs to completion before the parent's next action, whereas `spawn_<key>` is dispatched to a background thread. The async `Interpreter` dispatches spawn actions on `action_def.type.startswith("spawn_")` only, so `spawn_blocking_worker` falls into the ordinary non-blocking path and the `blocking` marker is discarded without a warning. The same action string therefore means two different things on the two engines — precisely the class of divergence `tests/test_engine_conformance.py` exists to prevent. A machine authored and tested against `SyncInterpreter` that relies on blocking ordering changes behaviour when it is run on the async engine.

## Environment

- Library: xstate-statemachine 0.7.0, commit `42612cf` (local clone, `pip install -e .`)
- Python: 3.13.7
- OS: Windows-11-10.0.26200-SP0

## Minimal reproduction

```python
"""LC-12 - `spawn_blocking_<key>` is honoured only by the SyncInterpreter.

The async `Interpreter` dispatches on `startswith("spawn_")`, so
`spawn_blocking_worker` takes the ordinary non-blocking path: the same action
name means two different things depending on the engine.

Measured by the wall time `start()` blocks while the child runs a 250 ms entry
action, plus whether the child actor survives in `_actors` (blocking spawn
keeps it, the sync non-blocking path reaps it on its background thread).
"""

from __future__ import annotations

import asyncio
import sys
import time

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

CHILD_WORK_S = 0.25


def parent(action_type: str):
    def slow(interp, ctx, evt, action):  # noqa: ANN001
        time.sleep(CHILD_WORK_S)

    child = create_machine(
        {"id": "w", "initial": "done",
         "states": {"done": {"type": "final", "entry": ["slow"]}}},
        logic=MachineLogic(actions={"slow": slow}),
    )
    return create_machine(
        {"id": "p", "initial": "a", "states": {"a": {"entry": [action_type]}}},
        logic=MachineLogic(services={"worker": child}),
    )


async def main() -> int:
    res = {}
    for t in ("spawn_worker", "spawn_blocking_worker"):
        s = time.perf_counter()
        interp = await Interpreter(parent(t)).start()
        res[("async", t)] = (time.perf_counter() - s, len(interp._actors))
        await interp.stop()
    for t in ("spawn_worker", "spawn_blocking_worker"):
        s = time.perf_counter()
        interp = SyncInterpreter(parent(t)).start()
        res[("sync", t)] = (time.perf_counter() - s, len(interp._actors))
        time.sleep(0.4)
        interp.stop()

    for (engine, t), (el, actors) in res.items():
        print(f"OBSERVED {engine:5s} {t:22s} start_blocked_ms={el * 1000:6.0f} actors_after_spawn={actors}")

    a_plain, a_block = res[("async", "spawn_worker")][0], res[("async", "spawn_blocking_worker")][0]
    s_plain, s_block = res[("sync", "spawn_worker")][0], res[("sync", "spawn_blocking_worker")][0]
    print("OBSERVED async: spawn_ and spawn_blocking_ behave identically "
          f"({a_plain * 1000:.0f} ms vs {a_block * 1000:.0f} ms) - the `blocking` marker is ignored")
    print("OBSERVED sync : spawn_ is non-blocking and spawn_blocking_ blocks "
          f"({s_plain * 1000:.0f} ms vs {s_block * 1000:.0f} ms)")
    print("EXPECTED both engines agree on what `spawn_blocking_<key>` means: "
          "either blocking on both, or a NotSupportedError on the async engine")

    sync_distinguishes = s_block > s_plain + CHILD_WORK_S / 2
    async_distinguishes = abs(a_block - a_plain) > CHILD_WORK_S / 2
    return 0 if (async_distinguishes or not sync_distinguishes) else 1


sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED async spawn_worker           start_blocked_ms=   251 actors_after_spawn=1
OBSERVED async spawn_blocking_worker  start_blocked_ms=   251 actors_after_spawn=1
OBSERVED sync  spawn_worker           start_blocked_ms=     2 actors_after_spawn=1
OBSERVED sync  spawn_blocking_worker  start_blocked_ms=   251 actors_after_spawn=1
OBSERVED async: spawn_ and spawn_blocking_ behave identically (251 ms vs 251 ms) - the `blocking` marker is ignored
OBSERVED sync : spawn_ is non-blocking and spawn_blocking_ blocks (2 ms vs 251 ms)
EXPECTED both engines agree on what `spawn_blocking_<key>` means: either blocking on both, or a NotSupportedError on the async engine
(exit code 1)
```

The sync engine separates the two modes by ~249 ms; the async engine shows a 0 ms difference. Note the async engine only *looks* blocking here because the child's entry action is a synchronous `time.sleep` occupying the event-loop thread — it is on the non-blocking code path, and with an `await`-ing child the parent proceeds immediately. The defect is the loss of the distinction, not the measured duration.

## Expected behaviour

XState v5 has no `spawn_blocking_` concept. Its spawn lifecycle is described entirely as "Created & started when spawned / Stopped when the machine is stopped / Can be manually stopped" (https://stately.ai/docs/spawn#lifecycle), with no synchronous or run-to-completion variant anywhere on the page. `spawn_blocking_` is therefore this library's own extension, and the contract to uphold is the library's own: **an action string must mean the same thing on both engines.** `SyncInterpreter` is documented as the synchronous counterpart of `Interpreter` for the *same* machine definitions, so swapping engines must not silently change semantics.

## Root cause analysis

- `src/xstate_statemachine/interpreter.py:615` — `_execute_actions` dispatches with `if action_def.type.startswith("spawn_") and not is_builtin(...)`: one prefix test, one code path.
- `src/xstate_statemachine/interpreter.py:916-984` — `_spawn_actor` never inspects `action_def.type` for the blocking marker; it always creates the child and `await child_interpreter.start()`s it (`:976`) as a managed background actor.
- `src/xstate_statemachine/sync_interpreter.py:832-837` — the sync engine dispatches on the tuple `("spawn_", "spawn_blocking_")`; at `sync_interpreter.py:1115` it computes `blocking = action_def.type.startswith("spawn_blocking_")` and branches at `:1155-1159` (inline `child.start()`) versus `:1161-1187` (background `threading.Thread`).
- `src/xstate_statemachine/models.py:124-127` — `spawn_service_key` strips *both* prefixes, so `spawn_blocking_worker` resolves to service key `worker` on the async engine too. Key resolution is correct; only the mode is dropped. That is what makes the failure silent: nothing raises, nothing warns, the actor simply spawns in the wrong mode.

## Impact

**General users:** any machine authored against `SyncInterpreter` that uses `spawn_blocking_` for ordering guarantees (child must finish before the parent's next action) loses those guarantees on the async engine with no error. Because the service key still resolves, the actor spawns and the machine still "works" — the bug surfaces only as a race under load.

**CandleViewer (trading OMS):** our order machines spawn a child actor per execution leg. Had we used `spawn_blocking_leg` to guarantee a leg registers its exchange client-order-id before the parent's next entry action writes the order row, the async engine would run the parent's action first and persist a row with a null leg id — a reconciliation break in which the exchange holds a working order the OMS cannot match to any leg. We deliberately avoid `spawn_blocking_` today precisely because its cross-engine meaning is not dependable.

## Proposed fix

Preferred — implement the mode on the async engine:

1. `interpreter.py:615` — widen the dispatch to `startswith(("spawn_", "spawn_blocking_"))` (a no-op today, but explicit for readers) and pass the mode down.
2. `interpreter.py:916` — in `_spawn_actor`, compute `blocking = action_def.type.startswith(SPAWN_BLOCKING_PREFIX)`. On the blocking path, after `await child_interpreter.start()` (`:976`), additionally await the child reaching a top-level final state (queueing `done.invoke.<id>` exactly as the sync engine's `_queue_actor_done` does at `sync_interpreter.py:1189`) before returning, so the parent's subsequent actions observe a completed child.
3. Use the existing `SPAWN_BLOCKING_PREFIX` constant (already defined at `models.py:76`) in both engines instead of repeating a string literal — the literal is currently hard-coded at `sync_interpreter.py:834` and `:1115` even though the constant exists and `spawn_service_key` (`models.py:124`) already uses it.

Fallback, if blocking spawn is not wanted on the async engine: raise `NotSupportedError` from `interpreter.py:_spawn_actor` when the blocking prefix is present, mirroring how the sync engine raises `NotSupportedError` for async actions. Loud and non-portable beats silent and wrong.

Backwards compatibility: option 1 changes async behaviour only for machines already using `spawn_blocking_`, which today receive non-blocking behaviour by accident — any machine depending on that is depending on a bug. The fallback is a hard break for those machines and should carry a minor-version note. Either way, document the chosen semantics in `docs/_guide/actors.md`, whose "Blocking Actors with `spawn_blocking_`" section (`:125-171`) describes the blocking guarantee as a `SyncInterpreter` feature but never states what the async `Interpreter` does with the same prefix; `docs/api/index.md:773` lists the two prefixes side by side with no engine caveat at all.

## Acceptance criteria

- [ ] `repro/LC-12_spawn-blocking-async-engine.py` exits 0.
- [ ] `tests/test_engine_conformance.py::test_spawn_blocking_prefix_means_the_same_on_both_engines` — spawns a child whose completion is observable and asserts the parent's next action sees the child finished on **both** engines (or that the async engine raises `NotSupportedError`, per the chosen design).
- [ ] `tests/test_actors.py::test_async_spawn_blocking_waits_for_child_final_state`.
- [ ] `tests/test_actors.py::test_async_spawn_non_blocking_does_not_wait` — pins the contrast so the two modes cannot re-converge.
- [ ] `SPAWN_BLOCKING_PREFIX` (`models.py:76`) is referenced by both engines; no bare `"spawn_blocking_"` literal remains outside `models.py`.
- [ ] `docs/_guide/actors.md` states which engines support `spawn_blocking_` and what it guarantees; `docs/api/index.md:773` gains the same caveat.

## Related

- LC-57 (umbrella): the two engines duplicate rather than share the core algorithm — this issue is a direct symptom.

## Verification

Independently verified on 2026-09-15.

- **Repro run:** `repro/LC-12_spawn-blocking-async-engine.py` executed in a fresh process against a clean `pip install -e .` checkout; exit code **1** (fails against the library today). The "Observed behaviour" block above matches the real output of that run.
- **Library:** xstate-statemachine 0.7.0, commit `42612cf`; Python 3.13.7; Windows-11-10.0.26200-SP0.
- **Root cause:** every cited `file:line` was opened and confirmed to contain the quoted code.
- **XState claims:** checked against the live stately.ai pages cited in the Expected section.
- **Duplicates:** `gh issue list --state all` shows one unrelated issue (#17, camelCase action auto-discovery); this is not a duplicate.
