---
lc: LC-01
title: "Bug: an action that raises still commits the transition, with no programmatic error channel"
labels: [bug, severity/blocker, area/interpreter, candleviewer]
severity: Blocker
blocks_adoption: true
repro_script: repro/LC-01_action-raise-commits-transition.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

When a user-supplied action raises, `interpreter.py` catches the exception, logs it, skips the remaining actions in that list — and then lets the transition complete anyway. The target state is entered, its `entry` actions run, `status` stays `"running"`, `send()` returns normally, and `on_transition` fires as if the transition succeeded. The only signal is a log line and the `on_action_error` plugin hook, neither of which can stop or roll back the transition. The machine therefore reports a state that its own actions never finished constructing, and that state is durably persistable (see LC-15).

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf` (local clone, `pip install -e`)
- Python: 3.13.7 (CPython, venv)
- OS: Windows 11
- Install: editable install from source clone

## Minimal reproduction

```python
"""LC-01 repro: an action that raises still commits the transition, and there
is no programmatic error channel — `send()` returns normally, the machine keeps
`status == "running"`, the target state is entered, and `on_transition` fires as
though the transition succeeded.

Exits 1 when the defect is present.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase

logging.disable(logging.CRITICAL)  # keep output clean; the library only logs

CONFIG = {
    "id": "oms",
    "initial": "a",
    "context": {"trace": []},
    "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["first", "explode", "third"]}}},
        "b": {"entry": ["entry_b"]},
    },
}


class Spy(PluginBase):
    def __init__(self) -> None:
        self.transitions: list[str] = []
        self.action_errors: list[str] = []

    def on_transition(self, interp, from_states, to_states, transition):
        self.transitions.append(sorted(to_states and interp.current_state_ids)[0])

    def on_action_error(self, interp, action_def, error):  # 0.6.0+
        self.action_errors.append(f"{action_def.type}:{type(error).__name__}")


async def main() -> int:
    def first(i, c, e, a):
        c["trace"].append("first")

    def explode(i, c, e, a):
        c["trace"].append("explode")
        raise RuntimeError("exchange rejected the order")

    def third(i, c, e, a):
        c["trace"].append("third")

    def entry_b(i, c, e, a):
        c["trace"].append("entry_b")

    logic = MachineLogic(
        actions={"first": first, "explode": explode, "third": third, "entry_b": entry_b}
    )
    spy = Spy()
    interp = Interpreter(create_machine(CONFIG, logic=logic))
    interp.use(spy)
    await interp.start()

    raised = None
    try:
        await interp.send("GO")
        await asyncio.sleep(0.05)
    except Exception as exc:  # noqa: BLE001
        raised = f"{type(exc).__name__}: {exc}"

    states = sorted(interp.current_state_ids)
    trace = list(interp.context["trace"])
    status = interp.status
    await interp.stop()

    print(f"OBSERVED send() raised          : {raised}")
    print(f"OBSERVED trace                  : {trace}")
    print(f"OBSERVED state after failed act : {states}")
    print(f"OBSERVED interpreter.status     : {status}")
    print(f"OBSERVED on_transition fired    : {spy.transitions}")
    print(f"OBSERVED on_action_error fired  : {spy.action_errors}")
    print("EXPECTED: transition NOT committed (state stays ['oms.a']) or an error")
    print("EXPECTED: surfaced to the caller / a transition-failed hook; entry_b must")
    print("EXPECTED: not run and on_transition must not report success.")

    bad = states == ["oms.b"] and "entry_b" in trace and raised is None
    print("RESULT: DEFECT REPRODUCED" if bad else "RESULT: not reproduced")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED send() raised          : None
OBSERVED trace                  : ['first', 'explode', 'entry_b']
OBSERVED state after failed act : ['oms.b']
OBSERVED interpreter.status     : running
OBSERVED on_transition fired    : ['oms.b']
OBSERVED on_action_error fired  : ['explode:RuntimeError']
EXPECTED: transition NOT committed (state stays ['oms.a']) or an error
EXPECTED: surfaced to the caller / a transition-failed hook; entry_b must
EXPECTED: not run and on_transition must not report success.
RESULT: DEFECT REPRODUCED
```

Exit code `1`. Reproduced on **both** engines: `SyncInterpreter` contains action errors at `sync_interpreter.py:887` with the identical `return`, and the same containment applies to an `entry` action raising during `start()` (LC-11).

## Expected behaviour

XState v5 lets an action's error propagate to the actor, where it is *observable*. Two verified citations:

- https://stately.ai/docs/migration#use-explicit-eventless-always-transitions (the `escalate` removal note): *"The `escalate` action creator is removed. In XState v5 actions can throw errors, and they will propagate as expected. Errors can be handled using an `onError` transition."*
- https://stately.ai/docs/actors#error-handling: *"You can subscribe to errors thrown by an actor using the `error` callback in the observer object passed to `actor.subscribe()`. This allows you to handle errors emitted by the actor logic."* — i.e. `actor.subscribe({ next, error })` delivers the failure to application code.

So in XState the caller has a programmatic error channel; here the failure exists only as a log line plus `on_action_error`, and it never affects the state the machine reports or persists.

**Scope note.** This issue does *not* claim XState rolls the transition back to the source state — that is this issue's *proposed* `"rollback"` policy, not a documented XState guarantee. The defect being reported is narrower and does not depend on XState at all: **a partially-executed action list is indistinguishable, to the caller, from a successful one.** `send()` returns normally, `status` stays `"running"`, and `on_transition` — whose own docstring (`plugins.py:137`) says it is "called after a **successful** state transition has completed" — fires with the new state. That is a factual misreport by the library's own contract.

At minimum the caller must be able to learn, programmatically and synchronously with the transition, that the state it now sees was produced by a partially executed action list.

## Root cause analysis

`src/xstate_statemachine/interpreter.py:667-689`, inside `_execute_actions`:

```python
            try:
                if inspect.iscoroutinefunction(action_callable):
                    await action_callable(self, self.context, event, action_def)
                else:
                    action_callable(self, self.context, event, action_def)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(
                    "🔥 Action '%s' raised while handling event '%s'; "
                    "skipping remaining actions in this list.", ...
                )
                for plugin in self._plugins:
                    plugin.on_action_error(self, action_def, exc)
                return
```

The `return` swallows the failure and hands control back to the caller. The caller is `base_interpreter.py:1732-1890` (`_execute_transition`), which has no way to know actions failed: the call at `base_interpreter.py:1838` (`await self._execute_actions(transition.actions, event)`) returns `None` whether or not an action raised, so execution proceeds unconditionally to `await self._enter_states(path_to_enter, event)` (line 1839, running the target's `entry`) and then to `plug.on_transition(...)` at lines 1883-1889 with the new state. The in-code comment at `interpreter.py:660-666` is explicit that this is deliberate ("the error is logged, the remaining actions are skipped, and the run loop survives") — the problem is that the containment has no escape hatch and no return value.

Note the `try/except` wrapping lines 1838-1880 *does* roll back (`self._active_state_nodes.clear()` / `.update(snapshot_before)` at 1868-1869) — but only for exceptions that actually escape. Because `_execute_actions` never lets one escape, this rollback path is unreachable for action failures.

The same containment exists on the initial-entry path used by `start()` (LC-11) and in `sync_interpreter.py:887`.

Note that the rollback machinery required already exists: 0.6.0 added "Transition atomicity" for *transition resolution* failures. It is simply not wired to *action execution* failures.

## Impact

**General users:** any machine whose actions can fail (I/O, parsing, validation, third-party calls) silently advances into states whose invariants were never established. Because the failure is log-only, it cannot be asserted on in tests, cannot fail CI, and cannot be turned into an alert without scraping logs. `on_transition` actively lies, which corrupts any audit trail, telemetry, or event-sourcing layer built on it.

**CandleViewer trading OMS:** the order machine's `submitting → submitted` transition carries `[persist_order, send_to_exchange, arm_timeout]`. If `send_to_exchange` raises (network blip, rejected payload), `arm_timeout` is skipped but the machine enters `submitted` and reports an open order that was never placed — or, in the inverse ordering, the order *is* placed and `persist_order` fails, so a position exists on the exchange that the machine and the database both believe does not exist. The broken state is then written to the snapshot as truth (LC-15), so a restart cannot recover it. This is a direct financial-loss path and is the single reason a four-layer mitigation (`@cv_action` wrapper, `FAULT` → `quarantined`, ERROR-log→P1 page, independent exchange reconciliation) is currently mandatory — none of which is sufficient alone.

## Proposed fix

**1. Machine-level `action_error_policy` (primary).** Add to `create_machine(config, logic=..., action_error_policy=...)` and/or the machine config:

| Value | Behaviour |
|---|---|
| `"continue"` | Today's behaviour. **Default in 0.7.x** for backwards compatibility. |
| `"rollback"` | Abort the transition: restore `_active_state_nodes` and `context` from the pre-transition snapshot, do not run `entry` on the target, fire `on_transition_failed`. Reuses the 0.6.0 transition-atomicity rollback path. |
| `"fail"` | Roll back, then stop the interpreter with `status = "error"` and re-raise on the next `await send()` / expose via `interpreter.error`. |

Recommend flipping the default to `"rollback"` in 1.0 with a `DeprecationWarning` emitted in 0.8 when the policy is unset and an action raises.

**2. Error channel (minimum viable, ship even if 1 slips).** Change `_execute_actions` to return `list[ActionDefinition]` of failed actions rather than `None`, and in `_execute_transition`:

- pass `failed_actions: list[str]` into `plug.on_transition(...)`;
- fire a new `plug.on_transition_failed(interpreter, transition, failed_actions, error)` instead of `on_transition` when the list is non-empty;
- expose `interpreter.last_transition_ok: bool` so a persistence layer can gate snapshot writes (closes LC-15 independently).

**Sketch:** `src/xstate_statemachine/interpreter.py:689` (return the failure instead of `return`), `src/xstate_statemachine/base_interpreter.py:1838-1889` (branch on it before `_enter_states` / `on_transition`), `src/xstate_statemachine/plugins.py:130-151` (declare the new hooks on `PluginBase` with no-op bodies, so existing plugins keep working), mirrored in `sync_interpreter.py:887`.

**Backwards compatibility:** all new hooks get no-op defaults on `PluginBase`; `action_error_policy` defaults to today's behaviour; `on_transition`'s new argument is keyword-only with a default so existing subclasses that override it with the old signature still work (detect via `inspect.signature` if necessary).

## Acceptance criteria

- [ ] `action_error_policy` accepted by `create_machine()` and validated (`ValueError` on an unknown value).
- [ ] With `"rollback"`: after the repro's `GO`, state is `['oms.a']`, `trace == ['first', 'explode']`, `entry_b` did **not** run, context is restored.
- [ ] With `"fail"`: the interpreter reaches `status == "error"` and the original `RuntimeError` is retrievable (`interpreter.error`), not just logged.
- [ ] With `"continue"` (default): behaviour is byte-identical to 0.7.0, but `on_transition` reports `failed_actions == ["explode"]` and `on_transition_failed` fires.
- [ ] `PluginBase.on_transition_failed` declared with a no-op default; a plugin subclass written against 0.7.0 still loads unchanged.
- [ ] The same policy is honoured on the initial-entry path used by `start()` (closes LC-11) and by `SyncInterpreter`.
- [ ] `interpreter.last_transition_ok` is `False` after a failed action list (closes LC-15's persistence gate).
- [ ] Tests added:
  - `tests/test_action_error_policy.py::test_continue_is_default_and_reports_failed_actions`
  - `tests/test_action_error_policy.py::test_rollback_does_not_commit_transition`
  - `tests/test_action_error_policy.py::test_rollback_restores_context`
  - `tests/test_action_error_policy.py::test_fail_stops_interpreter_with_error`
  - `tests/test_action_error_policy.py::test_entry_action_failure_during_start`
  - `tests/test_action_error_policy.py::test_sync_interpreter_honours_policy`
  - `tests/test_plugins.py::test_on_transition_failed_hook_fires`
  - `tests/test_persistence.py::test_failed_action_is_not_persisted`
- [ ] `repro/LC-01_action-raise-commits-transition.py` exits `0` under the new default/`rollback` policy.

## Related

- **LC-11** — an entry action raising during `start()` does not fail the start (same containment, initial-entry path). Fix together.
- **LC-15** — a state produced by a failed action is durably persisted as truth. Closing LC-01 closes it; `last_transition_ok` closes it independently.
- **LC-48** — no error-observability hooks (`on_transition_failed`, `on_guard_error`, unhandled-event signal). This issue delivers the first of the three.
- **LC-08**, **LC-36** — same "failures degrade to silent no-ops" design family.
- `CHANGELOG.md` 0.6.0 — added `on_action_error` and transition atomicity; this issue is the unfinished half of both.

## Verification

Independently verified on 2026-09-15.

- Library: `xstate-statemachine` 0.7.0, commit `42612cf` (`main`), editable install.
- Python: 3.13.7 (CPython), Windows 11.
- Repro run in a fresh process: output matches the **Observed behaviour** block verbatim; **exit code `1`**.
- Root cause re-checked against source: `interpreter.py:667-689` (`try` / `except Exception` / `on_action_error` / `return`) and `base_interpreter.py:1838-1889` confirmed. Line numbers corrected from the original draft (`:658-690`, `:1780-1830`).
- XState citation corrected: the previously cited quote and `#actor-error-handling` anchor were not present on the page. Replaced with verified quotes from `/docs/migration` (the `escalate` removal note) and `/docs/actors#error-handling`, and the Expected section was narrowed — XState is cited for the *observable error channel*, not for transition rollback, which is this issue's proposal rather than an XState guarantee.
- Not a duplicate: the upstream tracker (`basiltt/xstate-statemachine`) has one issue, #17 (closed, camelCase→snake_case auto-discovery), unrelated.
