---
lc: LC-48
title: "Feature: no error-observability hooks — no `on_transition_failed`, no `on_guard_error`, no unhandled-event signal"
labels: [enhancement, severity/high, area/interpreter, candleviewer]
severity: High
blocks_adoption: true
repro_script: repro/LC-48_no-error-observability-hooks.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

`PluginBase` is the library's only observability surface, and it has a blind spot around **failure**. Three distinct production failures are either invisible or indistinguishable from normal operation: (1) a transition whose actions raised still reports through `on_transition` as a success, and there is no `on_transition_failed`; (2) a guard that raised is reported through `on_guard_evaluated(..., result=False)`, identical to a guard that legitimately returned `False`, and there is no `on_guard_error`; (3) an event with no enabled transition is dropped with a `logger.debug` line and no hook at all, so a typo'd event name and a legitimately ignored one are the same observation.

Additionally, the interpreter *does* call `on_error` and `on_done` on plugins — but by duck-typed `getattr` lookup, and neither is declared on `PluginBase`, so they are undiscoverable from the class, unchecked by type checkers, and absent from the docs.

For any system that must alert on "the machine did not do what the message said", log-scraping is the only available mechanism today.

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, installed with `pip install -e .`
- Python: 3.13.7 (CPython)
- OS: Windows 11 (x64)
- Install method: `pip install -e .` into a dedicated venv

## Minimal reproduction

```python
"""LC-48 repro: no error-observability hooks on `PluginBase`.

Three failures that a production system must observe are invisible:

1. an action raising -> `on_transition` still fires as a success, and there
   is no `on_transition_failed(failed_actions)` hook;
2. a guard raising -> reported through `on_guard_evaluated(..., result=False)`,
   indistinguishable from a guard that legitimately returned False; there is
   no `on_guard_error`;
3. an event with no enabled transition -> silently discarded, with no
   `on_unhandled_event` hook (so a typo'd event name looks exactly like a
   legitimately ignored one).

Exits 1 when the hooks are absent / the failures are unobservable.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine

logging.disable(logging.CRITICAL)

CFG = {
    "id": "order",
    "initial": "submitting",
    "context": {},
    "states": {
        "submitting": {
            "on": {
                "FILL": {"target": "filled", "actions": ["book"]},
                "CANCEL": {"target": "cancelled", "cond": "may_cancel"},
            }
        },
        "filled": {},
        "cancelled": {},
    },
}


def book(interpreter, context, event, action_def):  # noqa: ANN001
    raise RuntimeError("ledger write failed")


def may_cancel(context, event):  # noqa: ANN001
    raise RuntimeError("risk service unreachable")


class Recorder(PluginBase):
    def __init__(self) -> None:
        self.events: list = []

    def on_transition(self, interpreter, from_states, to_states, transition):  # noqa: ANN001
        self.events.append(("on_transition", sorted(interpreter.current_state_ids)))

    def on_action_error(self, interpreter, action, error):  # noqa: ANN001
        self.events.append(("on_action_error", action.type))

    def on_guard_evaluated(self, interpreter, guard_name, event, result):  # noqa: ANN001
        self.events.append(("on_guard_evaluated", guard_name, result))


async def main() -> int:
    machine = create_machine(
        CFG, logic=MachineLogic(actions={"book": book}, guards={"may_cancel": may_cancel})
    )
    rec = Recorder()
    interp = Interpreter(machine).use(rec)
    await interp.start()
    await interp.send("TYPO_FILLED")  # 3. unhandled event
    await interp.send("CANCEL")  # 2. raising guard
    await interp.send("FILL")  # 1. raising action
    await asyncio.sleep(0.05)
    await interp.stop()

    missing = [
        h
        for h in ("on_transition_failed", "on_guard_error", "on_unhandled_event")
        if not hasattr(PluginBase, h)
    ]
    declared_duck = [h for h in ("on_error", "on_done") if not hasattr(PluginBase, h)]
    print("OBSERVED  plugin events:", rec.events)
    print("OBSERVED  final state:", sorted(interp.current_state_ids))
    print("OBSERVED  missing PluginBase hooks:", missing)
    print("OBSERVED  duck-typed hooks not declared on PluginBase:", declared_duck)
    print(
        "EXPECTED  on_transition_failed / on_guard_error / on_unhandled_event declared; "
        "guard failure distinguishable from a False guard; typo'd event surfaced"
    )
    ok = not missing and not declared_duck
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED  plugin events: [('on_guard_evaluated', 'may_cancel', False), ('on_action_error', 'book'), ('on_transition', ['order.filled'])]
OBSERVED  final state: ['order.filled']
OBSERVED  missing PluginBase hooks: ['on_transition_failed', 'on_guard_error', 'on_unhandled_event']
OBSERVED  duck-typed hooks not declared on PluginBase: ['on_error', 'on_done']
EXPECTED  on_transition_failed / on_guard_error / on_unhandled_event declared; guard failure distinguishable from a False guard; typo'd event surfaced
RESULT: FAIL
```

Three things to read out of that trace:

- `TYPO_FILLED` produced **no plugin event whatsoever**. It is not in the list.
- The raising guard appears as `('on_guard_evaluated', 'may_cancel', False)` — byte-identical to what a correct guard returning `False` would emit.
- The raising action emits `on_action_error`, and then `on_transition` fires anyway reporting `['order.filled']`. A consumer building a state-change feed from `on_transition` records a successful fill that never happened.

## Expected behaviour

XState v5 makes each of these observable as a first-class signal rather than a log line:

- **Inspection API** — <https://stately.ai/docs/inspection> describes the Inspect API as *"a way to inspect the state transitions of your state machines and every aspect of actors in an actor system"*, and defines four inspection event types: `@xstate.actor`, `@xstate.event`, `@xstate.snapshot` and `@xstate.microstep`. Crucially the *event* is itself an observable signal (`@xstate.event` *"is emitted when an event is sent to an actor"*), independent of whether that event produced a transition — so an event that selected no transition is still visible to an inspector, which is exactly the gap in (3). XState does **not** publish a per-action outcome inspection event, so the ask here is not strict XState parity for (1); it is parity with this library's own already-documented rationale for `on_action_error` (see below).
- **Error handling** — <https://stately.ai/docs/actors#error-handling>: *"You can subscribe to errors thrown by an actor using the `error` callback in the observer object passed to `actor.subscribe()`."* Errors have a first-class observable channel rather than being silently absorbed.
- **Guards** — <https://stately.ai/docs/guards> is explicit: *"Guards should be pure, synchronous functions that return either `true` or `false`."* A throwing guard is therefore a defect, and collapsing it to `false` without a distinct signal makes that defect undetectable.

Nothing here demands that this library change its *containment* policy (contain the error, keep the machine alive) — the ask is that containment be **observable**, which is precisely the rationale already written into the `on_action_error` docstring in `plugins.py:167-194` ("The trade-off is that the failure is otherwise invisible to your program… This hook is the supported way to observe it"). That rationale applies equally to the three gaps above.

## Root cause analysis

- `src/xstate_statemachine/plugins.py:70-256` — `PluginBase` declares exactly ten hooks: `on_interpreter_start`, `on_interpreter_stop`, `on_event_received`, `on_transition`, `on_action_execute`, `on_action_error`, `on_guard_evaluated`, `on_service_start`, `on_service_done`, `on_service_error`. There is no transition-failure, guard-error or unhandled-event hook.
- `src/xstate_statemachine/base_interpreter.py:1275-1278` — the unhandled-event path:
  ```python
  transitions = self._select_transitions(event)
  if not transitions:
      logger.debug("🍃 No transition found for event '%s'.", event.type)
      return
  ```
  A `logger.debug` and an early `return`. No plugin loop, no counter, no snapshot flag.
- `src/xstate_statemachine/base_interpreter.py:2910-2935` — the guard path catches `Exception`, logs, sets `result = False`, and then falls into the *same* `for plugin in self._plugins: plugin.on_guard_evaluated(self, guard.type, event, result)` loop used for a legitimate `False`. The exception object is discarded at the `except` and never reaches a plugin.
- `src/xstate_statemachine/interpreter.py:649` and `:688` (and `sync_interpreter.py:898`) — `on_action_error` is fired per failing action, but the surrounding transition machinery in `base_interpreter.py:1754`, `:1776`, `:1884` calls `plugin.on_transition(...)` unconditionally afterwards, with no indication that the action list was truncated by a failure.
- `src/xstate_statemachine/base_interpreter.py:2329-2332` and `:2356-2359` — `on_error` / `on_done` are invoked via `hook = getattr(plugin, "on_error", None); if callable(hook): hook(self, error)`. Working, but undeclared on `PluginBase`, so `mypy` cannot check a plugin's signature and no reader of `plugins.py` learns they exist.

## Impact

**General users.** The library's headline safety property — "errors are contained, the machine stays alive" — is only safe if containment is observable. Today a buggy action, a buggy guard and a misspelled event name all degrade into *silence plus a state graph that looks healthy*. Monitoring has to be built on `logger` string matching, which is fragile across versions and locales, and impossible to attribute to a specific interpreter instance in a multi-machine process.

**CandleViewer trading OMS.** An `order` machine in `submitting` receives `FILL`. The `book` action writes the fill to the ledger and raises because the ledger is unreachable. The machine transitions to `filled` regardless, `on_transition` reports a clean `submitting → filled`, the WS projection broadcasts a filled order to every client, and the ledger has no record of it — a **position exists on the exchange that the books do not know about**. Separately: a gateway rename from `FILLED` to `ORDER_FILLED` makes every fill event unhandled; the order machine sits in `submitting` forever with zero error signal while positions accumulate on the exchange. Our own internal requirement here is to emit a metric counting unhandled events per machine kind and event name, plus a CI gate that fails if any gateway-produced event name is absent from the machine's transition descriptors. Neither half is satisfiable with the current hook set — there is no supported way to observe, let alone count, an unhandled event.

## Proposed fix

Add three hooks to `PluginBase` and declare the two duck-typed ones. All are no-op defaults, so this is **fully backwards compatible** — no existing plugin breaks, and no call site changes semantics.

```python
# src/xstate_statemachine/plugins.py  (additions to PluginBase)

def on_transition_failed(
    self,
    interpreter: TInterpreter,
    transition: "TransitionDefinition",
    failed_actions: List[Tuple["ActionDefinition", BaseException]],
) -> None:
    """Called after a transition completes with one or more failed actions.

    Fires *in addition to* `on_transition`, immediately before it, so a
    consumer can mark the resulting state change as degraded.
    """

def on_guard_error(
    self,
    interpreter: TInterpreter,
    guard_name: str,
    event: "Event",
    error: BaseException,
) -> None:
    """Called when a guard predicate raises. The guard still evaluates to
    `False` (unchanged behaviour); this hook makes that distinguishable from
    a guard that legitimately returned `False`."""

def on_unhandled_event(self, interpreter: TInterpreter, event: "Event") -> None:
    """Called when an event selects no transition in any active region."""

def on_error(self, interpreter: TInterpreter, error: BaseException) -> None:
    """Called when the interpreter enters `status == 'error'`."""

def on_done(self, interpreter: TInterpreter, output: Any) -> None:
    """Called when the machine reaches a top-level final state."""
```

Call sites:

- `base_interpreter.py:1277` — before the early `return`, `for plugin in self._plugins: plugin.on_unhandled_event(self, event)`.
- `base_interpreter.py:2918` (the guard `except Exception as exc:`) — capture `exc` and fan out `on_guard_error` *before* the existing `on_guard_evaluated(..., False)` call, so ordering is deterministic: error first, then the evaluation result.
- `interpreter.py:640-690` / `sync_interpreter.py:890-900` — have `_execute_actions` return the list of `(action_def, exc)` pairs it contained; `base_interpreter.py:1754/1776/1884` fire `on_transition_failed` with that list when it is non-empty, then `on_transition` as today.
- `base_interpreter.py:2329-2332`, `:2356-2359` — keep the `getattr` guard for third-party plugins that predate the declaration, but the declared base method makes it unconditional for `PluginBase` subclasses.

Since the hooks are additive no-ops, no deprecation cycle is needed. `LoggingInspector` in `plugins.py:260+` should implement the three new hooks so the default inspector surfaces failures out of the box.

A follow-on (optional, non-blocking): expose a cheap `interpreter.unhandled_event_count` counter so metrics can be scraped without registering a plugin.

## Acceptance criteria

- [ ] `PluginBase` declares `on_transition_failed`, `on_guard_error`, `on_unhandled_event`, `on_error`, `on_done`, each a documented no-op.
- [ ] `on_unhandled_event` fires exactly once per event that selects no transition, in both `Interpreter` and `SyncInterpreter`.
- [ ] A raising guard fires `on_guard_error` with the original exception, *and* still fires `on_guard_evaluated(..., result=False)` (behaviour unchanged).
- [ ] A transition with a raising action fires `on_action_error`, then `on_transition_failed` with the `(action, exception)` pairs, then `on_transition` — in that order.
- [ ] `LoggingInspector` implements all three new hooks.
- [ ] `repro/LC-48_no-error-observability-hooks.py` exits 0.
- [ ] Tests added:
  - `tests/test_plugins.py::test_on_unhandled_event_fires_for_unknown_event`
  - `tests/test_plugins.py::test_on_unhandled_event_not_fired_for_handled_event`
  - `tests/test_plugins.py::test_on_guard_error_fires_and_guard_still_false`
  - `tests/test_plugins.py::test_on_transition_failed_reports_failed_actions`
  - `tests/test_plugins.py::test_on_transition_failed_precedes_on_transition`
  - `tests/test_plugins.py::test_on_error_and_on_done_declared_on_plugin_base`
  - `tests/test_sync_interpreter.py::test_sync_interpreter_fires_error_observability_hooks`
- [ ] `docs/_guide/plugins.md` documents the five hooks with a worked "route failures to metrics" example.

## Related

Companion findings from the same review (filed separately):

- Action raise commits the transition — the *semantics* side of the same gap; this issue is the *observability* side and is fixable without changing semantics.
- Unhandled events discarded — this issue asks only for a hook; that one questions the discard policy itself.
- Unknown transition targets are not validated at build time — the static-validation counterpart to the unhandled-event problem.
- Guard exception swallowed as `False` — `on_guard_error` is the minimum viable mitigation if the swallow behaviour is kept.
- Docs disagree on whether `status` can be `'error'` — resolved partly by declaring `on_error` on `PluginBase`.

## Verification

Independently verified on **2026-09-15**.

- Repro `repro/LC-48_no-error-observability-hooks.py` run in a fresh process against the local clone at commit `42612cf`: **exit code 1**, output matches the Observed section verbatim.
- Python 3.13.7 (CPython), Windows 11 x64, `pip install -e .` into `.venv-cv`.
- Root-cause citations checked against the source: `plugins.py` declares exactly the ten hooks listed (hook-count corrected from "nine" during verification); `base_interpreter.py:1275-1277` is the `logger.debug` + early `return` unhandled-event path; `:2918` is the guard `except Exception:` that discards the exception and sets `result = False` before the shared `on_guard_evaluated` fan-out at `:2934-2935`; `on_action_error` fires at `interpreter.py:649`/`:688` and `sync_interpreter.py:898`; `plugin.on_transition` is called unconditionally at `base_interpreter.py:1754`, `:1776`, `:1884`; `on_error`/`on_done` are dispatched by `getattr` at `:2330` and `:2357` and are absent from `PluginBase`.
- XState citations re-checked against the live pages and **corrected**: the inspection page defines `@xstate.actor`/`@xstate.event`/`@xstate.snapshot`/`@xstate.microstep` — there is no `@xstate.action` event and no per-action outcome signal, so the original parity claim for the failed-action case was withdrawn and replaced with the `@xstate.event` argument (which does support the unhandled-event ask). The actors and guards quotations now match the published wording.
- Not a duplicate: the only issue on `basiltt/xstate-statemachine` is #17 (closed, camelCase action auto-discovery), unrelated.
