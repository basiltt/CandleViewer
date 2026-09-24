---
lc: LC-08
title: "Feature: Validate transition targets at create_machine() — an unknown target is a silent runtime no-op"
labels: [enhancement, severity/high, area/validation, candleviewer]
severity: High
blocks_adoption: true
repro_script: repro/LC-08_unknown-target-unvalidated.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

The library validates *named logic* — an unknown action name raises `ImplementationMissingError` and an unknown guard name raises the same — but it never validates *transition targets*. A machine whose transition points at a state that does not exist loads cleanly, starts cleanly, and at runtime the async `Interpreter` swallows the resulting `StateNotFoundError` inside its event loop. The event is consumed, the state is unchanged, `is_running` stays `True`, and nothing reaches the caller.

The asymmetry is the core complaint: a typo in an *action* name is a loud configuration error, while a typo in a *target* name is invisible. Both are static properties of the config and both are knowable at `create_machine()` time.

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local editable install (`pip install -e .`)
- Python: 3.13.7 (CPython, MSC v.1944 64-bit)
- OS: Windows 11
- Interpreters under test: `Interpreter` (async) and `SyncInterpreter`

## Minimal reproduction

```python
"""LC-08 repro: an unknown target state is never validated and is a silent no-op.

An unknown ACTION name fails loudly (ImplementationMissingError, raised out of
`start()`). An unknown TARGET name does not: it passes `create_machine()`, and
at runtime the async Interpreter swallows the StateNotFoundError in its event
loop, leaving the machine in its old state, still running, with no signal to
the caller.
"""

import asyncio
import sys

from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.interpreter import Interpreter

BAD_TARGET = {
    "id": "m",
    "initial": "s",
    "states": {"s": {"on": {"GO": "nowhere_at_all"}}, "t": {}},
}

BAD_ACTION = {"id": "m", "initial": "s", "states": {"s": {"entry": ["no_such_action"]}}}


async def main() -> int:
    # Control: an unknown ACTION name fails loudly (at start()).
    action_err = None
    try:
        m = create_machine(BAD_ACTION, logic=MachineLogic())
        await Interpreter(m).start()
    except Exception as exc:  # noqa: BLE001
        action_err = type(exc).__name__

    # Subject: an unknown TARGET name.
    create_err = None
    try:
        machine = create_machine(BAD_TARGET, logic=MachineLogic())
    except Exception as exc:  # noqa: BLE001
        create_err = type(exc).__name__
        print(f"OBSERVED: create_machine raised {create_err}")
        print("RESULT: PASS")
        return 0

    interp = await Interpreter(machine).start()
    send_err = None
    try:
        await interp.send("GO")
        await asyncio.sleep(0.05)
    except Exception as exc:  # noqa: BLE001
        send_err = type(exc).__name__
    state = sorted(interp.current_state_ids)
    running = interp.is_running
    await interp.stop()

    print(f"OBSERVED: unknown action -> {action_err} (raised out of start())")
    print(
        f"OBSERVED: unknown target -> create_machine={create_err} "
        f"send={send_err} state={state} running={running}"
    )
    print("EXPECTED: unknown target raises at create_machine() (like unknown actions)")

    ok = False
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

Verbatim output (exit code 1):

```
OBSERVED: unknown action -> ImplementationMissingError (raised out of start())
OBSERVED: unknown target -> create_machine=None send=None state=['m.s'] running=True
EXPECTED: unknown target raises at create_machine() (like unknown actions)
RESULT: FAIL
```

Corroborating observations:

- The control case in the same script is the contrast: an unknown action name does produce `ImplementationMissingError` out of `start()`.
- With logging enabled the error *is* produced internally, then discarded:
  ```
  ERROR 🚫 All resolution attempts failed for target: 'nowhere_at_all'
  ERROR 📂 Available top-level states in machine 'm': ['s', 't']
  ERROR 💥 Error processing event 'GO' on 'm'; the interpreter remains running. Could not resolve target state 'nowhere_at_all' from state 'm'.
  ```
- `SyncInterpreter` on the identical config **does** surface it to the caller:
  ```
  unknown RAISED StateNotFoundError Could not resolve target state 'nowhere_at_all' from state 'm'.
  ```
  so the two engines have different error contracts for the same machine.

## Expected behaviour

XState v5 resolves and validates targets when the machine is created, not when the event fires.

**Verified empirically against XState 5.33.0** (Node 20.14.0) with the exact analogue of `BAD_TARGET`:

```js
const { createMachine } = require('xstate');
createMachine({ id:'m', initial:'s', states:{ s:{ on:{ GO:'nowhere_at_all' } }, t:{} } });
```

throws immediately from `createMachine` — before any actor exists:

```
Invalid transition definition for state node 'm.s':
Child state 'nowhere_at_all' does not exist on 'm'
```

Targets are part of the static structure of the chart, exactly like state ids, which is why XState can reject them eagerly. SCXML likewise treats a `<transition target="…">` naming a nonexistent state as a document error detectable at load.

The expected contract here: `create_machine()` walks every transition in the config, resolves each target, and raises (`StateNotFoundError` or `InvalidConfigError`) listing every unresolvable target — mirroring how unknown action/guard/service names already fail. Secondarily, a resolution failure that still occurs at runtime must never be silently discarded.

## Root cause analysis

**1. No target validation exists.** `create_machine()` (`src/xstate_statemachine/factory.py`) builds the `MachineNode` tree and validates logic bindings, but there is no pass over `TransitionDefinition.target_str`. Targets are only ever resolved lazily, from `_execute_transition`. A grep for `resolve_target_state` shows call sites exclusively inside `base_interpreter.py` — nothing in `factory.py` or at load time.

**2. Resolution failure returns `None`.** `BaseInterpreter._resolve_target_state_node` (`base_interpreter.py:1164-1261`) tries four standard resolutions plus three fallbacks (root attribute lookup, root `states` dict including a last-segment match, then an exhaustive tree walk matching the last id segment). Every attempt catches `StateNotFoundError` and continues; when all fail it logs two `logger.error` lines and returns `None` (`:1253-1261`).

**3. The caller converts `None` to an exception correctly…** `base_interpreter.py:1763-1765`:

```python
target_state = self._resolve_target_state_node(transition)
if target_state is None:
    raise StateNotFoundError(transition.target_str, self.machine.id)
```

**4. …and the async run loop discards it.** `interpreter.py:479-487` catches every `Exception` escaping the macrostep and logs it. The comment there documents this as a deliberate architecture decision — a failure processing one event must not kill the run loop, which is a sound goal — but it is implemented as "log and continue" with no programmatic signal:

```python
except Exception as exc:
    logger.error(
        "💥 Error processing event '%s' on '%s'; the "
        "interpreter remains running. %s", event.type, self.id, exc, exc_info=True,
    )
```

Since `send()` is fire-and-forget (`await queue.put(...)`, see LC-42), the awaiting caller has no channel through which the error could be delivered even in principle. And `PluginBase` (`plugins.py:70-256`) declares no `on_transition_failed` hook (LC-48), so not even an observer can see it. The result: the one place that knows the machine is misconfigured is a log line.

Keeping the run loop alive is right; degrading the config error to a log line is not. The fix is to move the detection earlier, where it can fail loudly without touching run-loop resilience.

## Impact

**General users.** A transition target is the single most common thing to typo in a state machine config, and it is the only major element of the config with no validation. The failure mode is maximally quiet: the machine loads, starts, reports healthy, consumes the event, and does nothing. Unit tests catch it only if they assert on the post-send state. In a machine with a dozen states, one dead transition can survive code review, CI and staging indefinitely. The problem compounds with the fallback tree walk (LC-06): a target may resolve to the *wrong* state instead of no state, and with no validation pass there is nowhere that reports which of the seven resolution stages actually matched.

**CandleViewer trading OMS.** Our B9 workstream compiles user-authored risk rules into a state-machine IR and deploys it. A compiled rule whose `target` references a state that was renamed in the machine template deploys **clean** — no validation error, no smoke-test failure — and then fails open at runtime: the `BREACH` event fires, the transition into `locked_out` resolves to nothing, the error is logged where nobody is watching, and trading continues with the risk lockout silently disabled. The machine reports `running=True` and the last successful transition throughout. This is the worst possible shape for a safety control: it is indistinguishable from a healthy machine right up to the moment it is needed. It is why we cannot adopt the library without a build-time target validator of our own (house rule: validate every target at compile time, re-validate at deploy time), duplicating work that belongs in `create_machine()`.

## Proposed fix

**Part 1 — a validation pass in `create_machine()`.** After the node tree is built, walk every `TransitionDefinition` (including `on`, `always`, `after`, `onDone`, `onError` and `invoke` handlers) and attempt resolution of each non-empty `target_str` using the *strict* resolver only — the standard four attempts, **not** the last-segment fallbacks. Collect all failures and raise once:

```python
# factory.py, end of create_machine()
def _validate_targets(machine: MachineNode) -> None:
    problems: list[str] = []
    for node in _walk(machine):
        for transition in _all_transitions(node):
            if not transition.target_str:
                continue
            try:
                resolve_target_state(transition.target_str, transition.source)
            except StateNotFoundError:
                problems.append(
                    f"  {node.id}: on '{transition.event}' -> "
                    f"target {transition.target_str!r} does not resolve"
                )
    if problems:
        raise StateNotFoundError(
            "Unresolvable transition targets:\n" + "\n".join(problems)
        )
```

Reporting **all** failures in one message (rather than the first) matters for the compiled-rule use case, where a rename breaks many transitions at once.

**Part 2 — make runtime resolution failures observable.** Keep the run loop alive, but stop making the failure invisible:

- Declare `on_transition_failed(interpreter, transition, event, error)` on `PluginBase` (shared with LC-48) and fire it from the `except` block at `interpreter.py:479`.
- Have `_resolve_target_state_node` log a `warning` on every fallback stage beyond exact resolution (shared with LC-06), so a target that resolved *loosely* is also visible.

**Part 3 — align the two engines.** `SyncInterpreter` raises to the caller while `Interpreter` logs. Once Part 1 lands the divergence is mostly moot for this class of bug, but the contract should be documented explicitly in both docstrings.

**API and backwards compatibility.** Part 1 turns some currently-loading machines into load-time errors. That is the point, but it is a breaking change for anyone relying on a dead transition. Introduce it as `create_machine(config, logic=..., strict_targets: bool = True)`:

- `0.8.0`: parameter added, defaults to `True`; `strict_targets=False` restores today's behaviour and emits a `DeprecationWarning` on each unresolvable target found.
- `1.0.0`: `strict_targets=False` removed.

Users with an intentionally-unresolvable target have a one-line escape hatch and a full release to fix their configs. Part 2 is purely additive (a new optional hook; `PluginBase` provides a no-op default) and needs no migration.

Usage after the change:

```python
>>> create_machine(
...     {"id": "m", "initial": "s", "states": {"s": {"on": {"GO": "nowhere_at_all"}}}},
...     logic=MachineLogic(),
... )
Traceback (most recent call last):
  ...
xstate_statemachine.exceptions.StateNotFoundError: Unresolvable transition targets:
  m.s: on 'GO' -> target 'nowhere_at_all' does not resolve
```

## Acceptance criteria

- [ ] `create_machine()` raises on a transition whose target does not resolve, by default.
- [ ] The error message lists **every** unresolvable target with its source state and event name, not just the first.
- [ ] Validation covers `on`, `always`, `after`, `onDone`, `onError` and `invoke` transition handlers.
- [ ] `strict_targets=False` restores 0.7.0 behaviour and emits a `DeprecationWarning`.
- [ ] Machines with only valid targets are unaffected; the full existing test suite passes unchanged with the default.
- [ ] `PluginBase.on_transition_failed` is declared with a no-op default and fires from the async run loop's `except` block.
- [ ] `repro/LC-08_unknown-target-unvalidated.py` exits 0.
- [ ] Tests added under `tests/`:
  - `tests/test_factory.py::test_unknown_target_raises_at_create_machine`
  - `tests/test_factory.py::test_unknown_target_error_lists_all_offenders`
  - `tests/test_factory.py::test_unknown_target_in_after_and_on_done_is_validated`
  - `tests/test_factory.py::test_strict_targets_false_restores_legacy_behaviour_with_warning`
  - `tests/test_plugins.py::test_on_transition_failed_fires_for_unresolvable_target`

## Related

- **LC-07** — relative `.child` targets silently resolve to nothing; Part 1 of this fix also catches those, so the two should land together.
- **LC-06** — over-forgiving target resolution (last-segment tree walk at `base_interpreter.py:1238-1250`); the validator should use strict resolution, and `strict_targets` is the natural home for making the loose fallbacks opt-in.
- **LC-34** — no strict mode for event names/payloads; a single `strict=True` machine option could cover both unknown events and unknown targets.
- **LC-36** — built-in action params silently ignored when misspelled; same validation gap, same silent-no-op class.
- **LC-48** — no error-observability hooks; Part 2 here is a subset of that issue.

## Verification

Independently re-verified on **2026-09-15**.

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, editable install
- Python: 3.13.7 (CPython, MSC v.1944 64-bit), Windows 11
- `repro/LC-08_unknown-target-unvalidated.py` run in a fresh process → **exit code 1**, output matches the Observed section verbatim.
- Corroborating checks re-run: `SyncInterpreter` on the identical config raises `StateNotFoundError`; with logging enabled the async engine emits `🚫 All resolution attempts failed for target: 'nowhere_at_all'` and then discards the error.
- Root-cause citations confirmed against source: no `resolve_target_state` call site in `factory.py`; `base_interpreter.py:1164-1261` returning `None` at `:1261`; `:1763-1765` converting `None` to `StateNotFoundError`; `interpreter.py:479-487` swallowing it; `plugins.py` declares no `on_transition_failed`.
- Expected behaviour confirmed empirically against **XState 5.33.0** (Node 20.14.0): `createMachine` throws `Invalid transition definition for state node 'm.s': Child state 'nowhere_at_all' does not exist on 'm'` before any actor is created.
