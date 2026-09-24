---
lc: LC-57
title: "Improvement: the two engines duplicate rather than share the core algorithm (umbrella for the code-quality group)"
labels: [enhancement, severity/medium, area/interpreter, candleviewer]
severity: Medium
blocks_adoption: false
repro_script: repro/LC-57_two-engines-duplicate-core-algorithm.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

`Interpreter` (asyncio) and `SyncInterpreter` (threads) each carry their own copy of the statechart algorithm: target resolution, transition execution, entry/exit, action execution and built-in action dispatch are all written twice. `BaseInterpreter` declares those steps as `async def` in a class documented as mode-agnostic, and the sync engine either shadows them with same-named *sync* methods or forks them under new names (`_execute_transition_sync`, `_resolve_target_state_robustly`) — so the base implementations are dead code on the sync path and the Template Method pattern is broken in practice. Every fix must therefore be made twice, and when it is not, the engines diverge silently: `tests/test_engine_conformance.py` exists precisely because six release-blocking divergences survived 2,647 passing tests. The repro measures the duplication from the installed package and demonstrates one live, still-open consequence.

## Environment

- Library: xstate-statemachine 0.7.0, commit `42612cf` (local clone, `pip install -e .`)
- Python: 3.13.7
- OS: Windows-11-10.0.26200-SP0

## Minimal reproduction

```python
"""LC-57 - the two engines duplicate rather than share the core algorithm.

Evidence, all measured from the installed package:

1. The "mode-agnostic" base declares the algorithm as `async def`; `SyncInterpreter`
   re-implements each step as a *separate* sync method, so the base versions are
   dead code for the sync engine. The Template Method pattern is broken.
2. Every core step is written twice, in comparable volume.
3. A live consequence: the duplicated `_is_async_callable` guard in the sync
   engine misclassifies `functools.partial(async_fn)`, so an async action is
   neither rejected nor awaited - it silently no-ops while the transition commits.

Exits 1 when the duplication / the misclassification are present.
"""

from __future__ import annotations

import functools
import inspect
import sys

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    NotSupportedError,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.base_interpreter import BaseInterpreter

STEPS = ("_process_event", "_execute_transition", "_enter_states", "_exit_states",
         "_execute_actions", "_execute_builtin_action")


def sloc(fn) -> int:
    try:
        return len([ln for ln in inspect.getsource(fn).splitlines() if ln.strip()])
    except (TypeError, OSError):
        return 0


broken_template, duplicated = [], []
for name in STEPS:
    base, sync, asy = (getattr(k, name, None) for k in (BaseInterpreter, SyncInterpreter, Interpreter))
    owner = getattr(sync, "__qualname__", "-").split(".")[0]
    if base is not None and inspect.iscoroutinefunction(base) and sync is not base and not inspect.iscoroutinefunction(sync):
        broken_template.append(name)
    if sync is not base and asy is not base and sync is not asy:
        duplicated.append(name)
    print(f"OBSERVED {name:24s} base_async={inspect.iscoroutinefunction(base)!s:5s} "
          f"sync_owner={owner:16s} sync_sloc={sloc(sync):4d} async_sloc={sloc(asy):4d}")

print(f"OBSERVED base async methods shadowed by same-named sync overrides: {broken_template}")
print(f"OBSERVED core steps implemented separately by BOTH engines: {duplicated}")

# The sync engine also forks two steps under *different* names, so the base's
# async originals are never reached at all.
for base_name, sync_name in (("_execute_transition", "_execute_transition_sync"),
                             ("_resolve_target_state_node", "_resolve_target_state_robustly")):
    fork = getattr(SyncInterpreter, sync_name, None)
    print(f"OBSERVED BaseInterpreter.{base_name} (sloc={sloc(getattr(BaseInterpreter, base_name)):3d}) "
          f"forked as SyncInterpreter.{sync_name} (sloc={sloc(fork):3d}) - renamed, so no override, no ABC check")
    if fork is not None:
        duplicated.append(sync_name)

# --- live divergence caused by the duplicated guard -------------------------
async def act(interp, ctx, evt, action_def):  # noqa: ANN001
    ctx["ran"] = True


machine = create_machine(
    {"id": "m", "initial": "a", "context": {},
     "states": {"a": {"on": {"GO": {"target": "b", "actions": ["act"]}}}, "b": {}}},
    logic=MachineLogic(actions={"act": functools.partial(act)}),
)
interp = SyncInterpreter(machine).start()
try:
    interp.send("GO")
    outcome = f"no error; state={sorted(interp.current_state_ids)} context={interp.context}"
    misclassified = True
except NotSupportedError as exc:
    outcome, misclassified = f"NotSupportedError: {exc}", False

print(f"OBSERVED SyncInterpreter._is_async_callable(partial(async_fn)) = "
      f"{bool(SyncInterpreter._is_async_callable(functools.partial(act)))} "
      f"(inspect.iscoroutinefunction says {inspect.iscoroutinefunction(functools.partial(act))})")
print(f"OBSERVED sync engine running an async action wrapped in functools.partial -> {outcome}")
print("EXPECTED one shared sans-io core parameterised over an execution strategy, so each "
      "step (and each guard such as _is_async_callable) exists once and cannot diverge")

sys.exit(1 if (broken_template or duplicated or misclassified) else 0)
```

## Observed behaviour

```
sync_interpreter.py:883: RuntimeWarning: coroutine 'act' was never awaited
  action_impl(self, self.context, event, action_def)
RuntimeWarning: Enable tracemalloc to get the object allocation traceback
OBSERVED _process_event           base_async=True  sync_owner=SyncInterpreter  sync_sloc=  29 async_sloc=  28
OBSERVED _execute_transition      base_async=True  sync_owner=BaseInterpreter  sync_sloc= 147 async_sloc= 147
OBSERVED _enter_states            base_async=True  sync_owner=SyncInterpreter  sync_sloc= 101 async_sloc=  85
OBSERVED _exit_states             base_async=True  sync_owner=SyncInterpreter  sync_sloc=  27 async_sloc=  26
OBSERVED _execute_actions         base_async=False sync_owner=SyncInterpreter  sync_sloc=  85 async_sloc=  93
OBSERVED _execute_builtin_action  base_async=False sync_owner=SyncInterpreter  sync_sloc= 116 async_sloc=  79
OBSERVED base async methods shadowed by same-named sync overrides: ['_process_event', '_enter_states', '_exit_states']
OBSERVED core steps implemented separately by BOTH engines: ['_execute_actions', '_execute_builtin_action']
OBSERVED BaseInterpreter._execute_transition (sloc=147) forked as SyncInterpreter._execute_transition_sync (sloc= 38) - renamed, so no override, no ABC check
OBSERVED BaseInterpreter._resolve_target_state_node (sloc= 87) forked as SyncInterpreter._resolve_target_state_robustly (sloc= 86) - renamed, so no override, no ABC check
OBSERVED SyncInterpreter._is_async_callable(partial(async_fn)) = False (inspect.iscoroutinefunction says True)
OBSERVED sync engine running an async action wrapped in functools.partial -> no error; state=['m.b'] context={}
EXPECTED one shared sans-io core parameterised over an execution strategy, so each step (and each guard such as _is_async_callable) exists once and cannot diverge
(exit code 1)
```

Reading the numbers: the three `base_async=True` rows whose owner is `SyncInterpreter` are the broken Template Method — the base's async body can never run for the sync engine. `_execute_transition` shows `sync_owner=BaseInterpreter` only because the sync engine renamed its copy to `_execute_transition_sync` (38 SLOC of re-implemented ordering against the base's 147). `_resolve_target_state_robustly` is an 86-SLOC near-clone of the base's 87-SLOC resolver. And the last two lines are the cost being paid today: the sync engine's private `_is_async_callable` copy fails to recognise `functools.partial(async_fn)`, so the coroutine is created, never awaited, the context update is lost — and the transition to `m.b` commits anyway.

## Expected behaviour

There is no XState-spec rule about internal layout; the applicable contract is the library's own. `SyncInterpreter` is documented as the synchronous counterpart of `Interpreter` for the *same* machine definitions, and `tests/test_engine_conformance.py:1-25` states the requirement explicitly: "tests here drive the SAME machine config through BOTH engines and assert IDENTICAL observable behaviour". XState v5 itself is built the other way round — the transition algorithm is pure and sans-io, and the actor layer decides *when* effects run. https://stately.ai/docs/machines#transitioning-state (XState ≥ 5.19.0): "you can also determine the next **state** and **actions** from the current state and event by using the pure `transition(machine, state, event)` and `initialTransition(machine)` functions", which return `[nextState, actions]` — the actions are *returned as data*, not executed, leaving execution entirely to the caller. Sans-io means one algorithm, two drivers, and divergence becomes structurally impossible rather than something a conformance suite must chase after the fact.

## Root cause analysis

Pairs of independent implementations (`src/xstate_statemachine/`):

| Step | Async / base | Sync |
|---|---|---|
| Target resolution | `base_interpreter.py:1164` `_resolve_target_state_node` | `sync_interpreter.py:1431` `_resolve_target_state_robustly` |
| Transition execution | `base_interpreter.py:1732` `_execute_transition` (async) | `sync_interpreter.py:413` `_execute_transition_sync` |
| Event processing | `base_interpreter.py:1263` `_process_event` (async) | `sync_interpreter.py:380` `_process_event` (shadows) |
| Entry / exit | `base_interpreter.py:1896` / `:2108` (async) | `sync_interpreter.py:614` / `:724` |
| Action execution | `interpreter.py:588` | `sync_interpreter.py:807` |
| Built-in action dispatch | `interpreter.py:695` | `sync_interpreter.py:901` |

`BaseInterpreter` is 3,046 lines, `interpreter.py` 1,292 and `sync_interpreter.py` 1,568; the genuinely shared portion is little more than `_collect_builtin_followups` (`base_interpreter.py:1594`) and the bookkeeping around it. Because the sync forks are *renamed*, Python's override machinery and any ABC check give no signal that the base bodies are unreachable, and a change to `base_interpreter.py` silently fails to reach the sync engine.

The mechanism generalises. Each of the grouped findings below is one duplicated site drifting on its own:

- **LC-58** — `sync_interpreter.py:1532-1548` `_is_async_callable` tests `__code__.co_flags & 0x80` instead of `inspect.iscoroutinefunction`; it misses `functools.partial`, objects with an async `__call__`, and async generators (demonstrated above). The async engine never needed this predicate, so only one side has it, and only one side is wrong.
- **LC-47** — `base_interpreter.py:1195` and `sync_interpreter.py:1478` both memoise by mutating `transition.target_str` on the shared `MachineNode` (the sync copy is even commented "‼️ CRITICAL: This mutation logic is restored from the original code"). We probed this and found it is *not* a live risk for the async engine (200 interpreters driven over one shared node: the mutation is idempotent and the event loop serialises it), but the sync engine's threaded timers have no such serialisation — and either way the fix must now be applied in two places.
- **LC-14** — `base_interpreter.py:1148-1153` `_prepare_event` forwards any object with `.type`/`.payload` unvalidated.
- **LC-59** — `models.py:416-423` has eight lines of unreachable `logger.debug` after `return` (line 414); `models.py:1032-1034` has a misindented comment block inside a method body.
- **LC-51** — `exceptions.py` defines `RestoredError` but `__init__.py:176-232` omits it from `__all__`, and the publish workflow smoke-tests `len(__all__) == 48`, pinning the omission. Verified: `"RestoredError" in xstate_statemachine.__all__` → `False`.
- **LC-52** — `interpreter.py:1121-1125` delivers `error.platform.*` as a `DoneEvent` carrying the exception in `.data`; naming a failure "Done" forces consumers to branch on `type`.
- **LC-61** — `ci.yml:62,79` lints with `black --check` + `flake8` (`--max-complexity=35`) on py3.13 only, and there is no mypy job anywhere in `.github/workflows/` despite the `Typed` classifier; `ci.yml:187` runs `pytest --cov-fail-under=86`. Two copies of one algorithm need roughly twice the tests to reach the same confidence, which is a large part of why the coverage floor sits where it does.
- **LC-12** (already filed separately) is the clearest symptom: `spawn_blocking_<key>` blocks on the sync engine and is silently ignored by the async one, because the prefix test was written twice and only one copy learned about the blocking mode.

## Impact

**General users:** the library's headline promise — write the machine once, run it on either engine — is enforced only by a conformance suite that was written *after* six release-blocking divergences shipped. Every new feature must be implemented twice and pinned by a cross-engine test; contributors touching `base_interpreter.py` cannot tell from the code that the sync engine will not pick up their fix. The `functools.partial` hole above is a working example: a perfectly ordinary way to pre-bind arguments to an action silently drops the action's effect while the transition commits.

**CandleViewer (trading OMS):** we run the async engine only, and LC-57 is a large part of why — adopting `SyncInterpreter` anywhere (for deterministic backtests, say) would mean re-validating every semantic we depend on, because a guarantee proven on one engine says nothing about the other. Concretely, our order machines wrap venue-specific submit callables with `functools.partial(submit, venue=..., client_id=...)`; on the sync engine that action would neither run nor raise, so `submitting → submitted` would commit with **no order ever sent to the exchange** and no error anywhere — the machine reports a working order that does not exist. The same duplication is why LC-12 forced us to avoid `spawn_blocking_` for leg actors.

## Proposed fix

Extract a sans-io core, mirroring XState v5's own split, and keep the public API unchanged:

1. **New `core/` module** — `algorithm.py` containing pure functions over immutable inputs: `select_transitions(config, event, machine)`, `resolve_target(node, target_str)`, `compute_exit_set` / `compute_entry_set`, and a `Microstep` result object listing `actions_to_run`, `states_to_exit`, `states_to_enter`, `next_configuration`. No `await`, no I/O, no interpreter reference — directly unit-testable and shared verbatim.
2. **Execution strategy protocol** — `class ExecutionStrategy(Protocol)` with `run_action(impl, ctx, event, action_def)`, `start_service(...)`, `schedule_after(delay, event)`, `spawn(child, blocking: bool)`. `AsyncStrategy` awaits and uses `TaskManager`; `SyncStrategy` calls inline, raises `NotSupportedError` for genuinely async-only features, and uses threads for timers.
3. **One driver** — `BaseInterpreter` keeps the queue/macrostep loop and calls `core.algorithm` for *what* to do and `self._strategy` for *how*. Delete `sync_interpreter.py`'s `_execute_transition_sync`, `_resolve_target_state_robustly`, `_enter_states`, `_exit_states`, `_process_event`, `_execute_actions`, `_execute_builtin_action`; `SyncInterpreter` becomes a thin `BaseInterpreter` + `SyncStrategy`.
4. **Fold in the grouped fixes as the code moves**, since each duplicated site collapses to one: `_is_async_callable` → `inspect.iscoroutinefunction` after `inspect.unwrap` and a `functools.partial.func` walk, plus `inspect.isasyncgenfunction` and an async `__call__` check (LC-58); target-resolution memoisation into a per-interpreter dict keyed by `id(transition)` so the shared `MachineNode` stays immutable (LC-47); validate or drop the duck-typed `_prepare_event` branch (LC-14); delete the unreachable code in `models.py` (LC-59); add `RestoredError` to `__all__` and update the `len(__all__)` smoke test to 49 (LC-51); introduce an `ErrorEvent` type for `error.platform.*`, keeping `DoneEvent` as a deprecated alias for one minor version (LC-52).
5. **CI** (LC-61): add a mypy job now that there is one algorithm to type; ratchet coverage on the rollback/cancellation branches of the extracted core.

Backwards compatibility: items 1–4 are internal; every public name, signature and documented behaviour is preserved, so this is a patch/minor-level refactor, with two deliberate exceptions. `NotSupportedError` will now be raised for `partial`-wrapped and `__call__`-style async actions that today silently no-op — a bug fix, worth a changelog note. The `ErrorEvent` rename needs the usual one-release deprecation path. Sequence the work: land the sans-io `core/algorithm.py` behind the existing engines first (both delegate, `test_engine_conformance.py` stays green as the safety net), then remove the sync forks, then the strategy protocol. `test_engine_conformance.py` should be kept permanently even once divergence is structurally impossible — it becomes cheap regression insurance.

## Acceptance criteria

- [ ] `repro/LC-57_two-engines-duplicate-core-algorithm.py` exits 0 — no core step is implemented by both engines, no base `async def` is shadowed by a same-named sync override, no renamed fork of a base step remains, and the sync engine rejects `functools.partial(async_fn)`.
- [ ] `tests/test_core_algorithm.py` — unit tests for the pure `select_transitions` / `resolve_target` / entry-exit-set functions, with no interpreter instantiated.
- [ ] `tests/test_engine_conformance.py::test_both_engines_share_one_algorithm_implementation` — asserts structurally (via `inspect`) that neither engine defines its own copy of the core steps.
- [ ] `tests/test_sync_interpreter.py::test_partial_wrapped_async_action_raises_not_supported` and `::test_async_call_object_raises_not_supported` and `::test_async_generator_action_raises_not_supported` (LC-58).
- [ ] `tests/test_models.py::test_transition_target_str_is_not_mutated_by_resolution` (LC-47).
- [ ] `tests/test_public_api_surface.py` — `RestoredError` in `__all__`, smoke test updated to 49 (LC-51).
- [ ] `tests/test_engine_conformance.py::test_error_platform_event_is_an_error_event` (LC-52).
- [ ] `tests/test_engine_conformance.py::test_spawn_blocking_prefix_means_the_same_on_both_engines` (LC-12) passes without an engine-specific branch.
- [ ] No unreachable statement after `return` anywhere in `src/` (LC-59) — enforced by a flake8 `B012`/`unreachable` check in CI.
- [ ] CI runs mypy on `src/`; `base_interpreter.py`/`core/` coverage above the current 86 % floor, with the rollback and cancellation branches covered (LC-61).

## Related

- Umbrella for group H: LC-14, LC-47, LC-51, LC-52, LC-58, LC-59, LC-61 — each summarised inline under "Root cause analysis" above, with its own `src/` file:line, so this issue stands alone.
- LC-12 (filed) — `spawn_blocking_<key>` silently ignored by the async engine; the canonical symptom of this duplication.
- LC-60 — polling instead of futures (grouped with LC-28); a second cross-cutting pattern repeated in both engines.
- `tests/test_engine_conformance.py:1-25` (in this repository) documents the six release-blocking divergences that motivated the cross-engine suite.

## Verification

Independently verified on **2026-09-15**.

- Library: xstate-statemachine 0.7.0, commit `42612cf41d9750a5982fe75d5bb539d82f1df4a9` (local clone, editable install)
- Python: 3.13.7 (CPython, MSC v.1944 64-bit) on Windows-11-10.0.26200-SP0
- Repro run in a fresh process: **exit code 1** (fails today), stdout matches the "Observed behaviour" block above verbatim.

Checks performed:

1. **Repro reproduces.** All twelve `OBSERVED` lines, the `RuntimeWarning: coroutine 'act' was never awaited` at `sync_interpreter.py:883`, and the exit code were reproduced exactly.
2. **Root-cause lines confirmed** by reading the source: `_prepare_event` at `base_interpreter.py:1105` (duck-typed forward at 1148-1153), `_resolve_target_state_node` :1164 (mutation at :1195), `_process_event` :1263, `_collect_builtin_followups` :1594, `_execute_transition` :1732, `_enter_states` :1896, `_exit_states` :2108; `interpreter.py` `_execute_actions` :588, `_execute_builtin_action` :695; `sync_interpreter.py` `_process_event` :380, `_execute_transition_sync` :413, `_enter_states` :614, `_exit_states` :724, `_execute_actions` :807, `_execute_builtin_action` :901, `_resolve_target_state_robustly` :1431, `_is_async_callable` :1533 (confirmed `__code__.co_flags & 0x80`). File sizes confirmed: 3,046 / 1,292 / 1,568 lines.
3. **Grouped findings spot-checked.** LC-51: `RestoredError` is defined at `exceptions.py:212`, `len(__all__) == 48` and `"RestoredError" in __all__` is `False`; the pin is at `publish.yml:80`. LC-59: unreachable `logger.debug` after `return` at `models.py:414`, misindented block at `models.py:1032`. LC-52: `DoneEvent(type=f"error.platform.{...}", data=e)` at `interpreter.py:1121`. LC-61: `ci.yml:62,79,187`; no mypy job present.
4. **Duplicate check.** `gh issue list --state all` (read-only) returns a single unrelated issue (#17, camelCase auto-discovery, closed). Not a duplicate.

Corrections applied during verification:

- **Expected behaviour — bad citation (material).** The draft attributed to `https://stately.ai/docs/actors` a quotation ("An actor is a running process… the machine's `transition` function is pure") that does not appear there or anywhere in the v5 docs. The underlying claim is nonetheless correct and is now cited accurately to `https://stately.ai/docs/machines#transitioning-state` (XState ≥ 5.19.0), which documents the **pure** `transition(machine, state, event)` / `initialTransition(machine)` functions returning `[nextState, actions]` — actions returned as data rather than executed. This is in fact *stronger* support for the sans-io argument than the invented quote.
- **Self-containment.** Removed the "Related" pointers to CandleViewer-internal documents (`01-library-core.md`, `02-quality-and-tests.md`, `11-adversarial-review.md`, probe `adv07`), which a library maintainer cannot open; the probe result for LC-47 is now described inline instead.
- **Observed block** was missing the interpreter's third warning line (`RuntimeWarning: Enable tracemalloc...`); added so the block matches real output exactly.
- **LC-59 line range** corrected to `models.py:416-423` (the `return` is at :414).
- **LC-61** reworded: the draft asserted `base_interpreter.py` sits at exactly 86 % with misses "concentrated in the rollback/cancellation branches". The `--cov-fail-under=86` threshold and the absent mypy job are verified, but the per-file percentage and the location of the misses were not measured here, so that unsupported precision was dropped.

No claim was rejected; the issue reproduces and is accurate as corrected.
