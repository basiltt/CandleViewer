---
lc: LC-36
title: "Bug: built-in action params must be nested under `params` — the obvious spelling parses fine and silently does nothing"
labels: [bug, severity/high, area/validation, candleviewer]
severity: High
blocks_adoption: true
repro_script: repro/LC-36_builtin-action-params-misspelled.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

Every built-in action creator reads its arguments from a nested `"params"` dict. `ActionDefinition.__init__` (`models.py:176`) does exactly one thing with a dict config: `self.type = config.get("type")`, `self.params = config.get("params")`. Any other key is discarded without comment. So `{"type": "raise", "event": "PLACE"}` — the spelling every user tries first, because it is what the action *reads* like — parses cleanly at `create_machine()` time, produces `params=None`, and at runtime does nothing at all.

The failure is worse than a plain no-op: `_execute_builtin_action` resolves `params.get("event")` to `None`, `_resolve_event_spec` passes `None` to `_coerce_event`, which raises `TypeError: Unsupported event type: NoneType` — and `_execute_actions` catches that exception, logs it, and **returns**, silently skipping every remaining action in the list. So one misspelled built-in both fails itself and cancels its siblings, while the transition still completes. This cost this study a false negative before it was caught, and it is the same silent-failure class as LC-07 and LC-08.

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, installed with `pip install -e .`
- Python: 3.13.7
- OS: Windows 11 (x64)

## Minimal reproduction

```python
"""LC-36 repro: built-in action params must be nested under `"params"`.

The obvious spelling `{"type": "raise", "event": "X"}` parses without any
error or warning at `create_machine()` time and is a **silent no-op** at
runtime. Only `{"type": "raise", "params": {"event": "X"}}` works.

The same applies to every built-in action creator (`sendTo`, `log`,
`cancel`, ...): `ActionDefinition.__init__` reads `config.get("params")`
and nothing validates that a built-in got the params it requires.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from xstate_statemachine import Interpreter, create_machine

logging.disable(logging.CRITICAL)


def cfg(raise_action: dict) -> dict:
    return {
        "id": "eval",
        "initial": "idle",
        "states": {
            "idle": {"on": {"EVALUATE": {"target": "scoring"}}},
            "scoring": {"entry": [raise_action], "on": {"PLACE": "placed"}},
            "placed": {"type": "final"},
        },
    }


WRONG = {"type": "raise", "event": "PLACE"}  # the obvious spelling
RIGHT = {"type": "raise", "params": {"event": "PLACE"}}  # the working one


async def run(action: dict) -> tuple[str, list[str]]:
    machine = create_machine(cfg(action))
    interp = await Interpreter(machine).start()
    await interp.send("EVALUATE")
    await asyncio.sleep(0.05)
    states = list(interp.current_state_ids)
    status = interp.status
    await interp.stop()
    return status, states


async def main() -> int:
    ok = True

    # 1) The wrong spelling is accepted by create_machine() with no error.
    try:
        m = create_machine(cfg(WRONG))
        parsed = m.states["scoring"].entry[0]
        print(
            f"OBSERVED create_machine() accepted {WRONG} -> "
            f"type={parsed.type!r} params={parsed.params!r}"
        )
        print(
            "EXPECTED InvalidConfigError: built-in 'raise' requires "
            "params.event"
        )
        ok = False
    except Exception as exc:  # pragma: no cover - would be the fix
        print(f"OBSERVED create_machine() raised {type(exc).__name__}: {exc}")

    # 2) At runtime the wrong spelling does nothing.
    status_w, states_w = await run(WRONG)
    print(f"OBSERVED wrong spelling -> status={status_w} states={states_w}")
    status_r, states_r = await run(RIGHT)
    print(f"OBSERVED right spelling -> status={status_r} states={states_r}")
    print("EXPECTED both to reach 'eval.placed' (or the wrong one to error)")
    if states_w == states_r:
        ok = True and ok  # both worked -> not reproduced

    reproduced = states_w != states_r or not ok
    print(
        "RESULT:",
        "REPRODUCED (misspelled built-in params silently ignored)"
        if reproduced
        else "NOT REPRODUCED",
    )
    return 1 if reproduced else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED create_machine() accepted {'type': 'raise', 'event': 'PLACE'} -> type='raise' params=None
EXPECTED InvalidConfigError: built-in 'raise' requires params.event
OBSERVED wrong spelling -> status=running states=['eval.scoring']
OBSERVED right spelling -> status=done states=['eval.placed']
EXPECTED both to reach 'eval.placed' (or the wrong one to error)
RESULT: REPRODUCED (misspelled built-in params silently ignored)
```

(exit code 1)

The machine with the wrong spelling is stuck in `eval.scoring` forever; the identical machine with the right spelling reaches `eval.placed`. With logging enabled (the repro disables it, as a user's production config typically would at INFO level) the only trace is a single `ERROR` line plus a traceback:

```
ERROR:xstate_statemachine.interpreter:🔥 Built-in action 'raise' raised while handling 'EVALUATE'; skipping remaining actions.
Traceback (most recent call last):
    raise TypeError(f"❌ Unsupported event type: {type(event).__name__}")
TypeError: ❌ Unsupported event type: NoneType
```

Note that message: *"skipping remaining actions"*. The misspelling does not just lose its own effect, it aborts the rest of the entry action list.

## Expected behaviour

XState validates action creator arguments at the point of construction, because in XState the built-ins are *functions*, not dicts — `raise({ type: 'PLACE' })` is a call, so omitting or misnaming the argument is a TypeScript error and, at minimum, a runtime `TypeError` at machine-definition time rather than a silent runtime no-op. From <https://stately.ai/docs/actions> under "Raise action":

> "The raise action is a special action that *raises* an event that is received by the same machine."

with the documented call shape `entry: raise({ type: 'someEvent', data: 'someData' })` — the event object is the first positional argument, not an optional key.

And from the same page under "Send-to action":

> "The `sendTo(...)` action is a special action that sends an event to a specific actor."

with the documented shape `actions: sendTo('someActor', { type: 'someEvent' })` — target first, event object second, both required.

The page is also explicit that these creators are *not* free-form config:

> "Built-in actions, such as `assign(…)`, `sendTo(…)`, and `raise(…)`, are **not imperative**; they return a special [action object](#action-objects) (e.g. `{ type: 'xstate.assign', … }`) that are interpreted by the state machine."

This library's JSON-first design necessarily re-expresses those call signatures as dict keys, which is a legitimate choice — but it inherits the obligation to validate them. A built-in whose required parameters are absent is a **configuration error**, and XState's equivalent is caught before the machine ever runs. The expected behaviour is therefore: `create_machine()` raises `InvalidConfigError` naming the action, the state it appears in, the missing parameter, and (for the specific case here) the fact that sibling keys were found at the top level and probably belong under `params`.

## Root cause analysis

- `src/xstate_statemachine/models.py:154-181` — `ActionDefinition.__init__`. For a dict config it reads exactly two keys:

  ```python
  self.type: str = config.get("type", "UnknownAction")
  self.params: Optional[Dict[str, Any]] = config.get("params")
  ```

  Every other key in the dict is dropped on the floor. There is no validation pass, no "unexpected key" warning, and no awareness of whether `type` names a built-in that requires params. Note also `config.get("type", "UnknownAction")` — an action dict with no `type` at all becomes an action literally named `UnknownAction`, a second instance of the same permissiveness.

- `src/xstate_statemachine/actions.py:65-151` — `BUILTIN_ACTION_ALIASES` maps every accepted spelling to a canonical name, and `resolve_builtin()` / `is_builtin()` (lines 124, 137) expose the lookup. So at parse time the library *already knows* whether an action type is a built-in. The information needed to validate is present and simply not used.

- `src/xstate_statemachine/interpreter.py:695-786` — `_execute_builtin_action`. Line 727 is `params = self._resolve_params(action_def.params, event) or {}`, which turns the `None` from the misspelling into `{}`. Then for `RAISE`:

  ```python
  target_event = self._resolve_event_spec(params.get("event"), event)
  ```

  `params.get("event")` is `None`, which flows into `_resolve_event_spec` (`base_interpreter.py:1299`) → `_coerce_event(None)` (`base_interpreter.py:505`) → `raise TypeError("Unsupported event type: NoneType")` at line 531. Every other built-in has the same shape: `SEND_TO` does `params.get("to")` and warns "could not resolve target; event dropped"; `SEND_PARENT`, `FORWARD_TO`, `ESCALATE`, `STOP_CHILD`, `SPAWN_CHILD` all read missing keys as `None`.

- `src/xstate_statemachine/interpreter.py:635-651` — the containment that converts the `TypeError` into a silent failure:

  ```python
  try:
      await self._execute_builtin_action(canonical, action_def, event)
  except asyncio.CancelledError:
      raise
  except Exception as exc:
      logger.exception("🔥 Built-in action '%s' raised while handling '%s'; "
                       "skipping remaining actions.", action_def.type, event.type)
      for plugin in self._plugins:
          plugin.on_action_error(self, action_def, exc)
      return
  ```

  The `return` is the collateral damage: subsequent entry actions never run. And because the transition itself has already been committed, the machine lands in the target state with a partially-executed action list — observable only via a log line or a plugin `on_action_error` hook that most users do not install.

- `src/xstate_statemachine/sync_interpreter.py:835-905` — identical structure, so `SyncInterpreter` has the same defect.

- `src/xstate_statemachine/logic_loader.py:223-227` — auto-discovery explicitly `continue`s past built-in action types so it will not demand a user implementation for them. Correct in itself, but it means the one existing pass that walks every action definition in the machine also declines to look at built-ins — the natural place a validation hook would sit is currently a deliberate skip.

## Impact

**General users.** The JSON form of every built-in has a "looks right, does nothing" spelling, and nothing — not `create_machine()`, not the type checker, not the logs at default level — reports it. `raise` and `sendTo` are the two actions users reach for first when moving beyond simple context mutation, so this is squarely on the newcomer path. Because the error is contained and the transition commits anyway, the machine ends up in a state that its author believes is transient; debugging starts from "my machine is stuck in a state that has a `raise` in its entry" with no signal pointing at the config. And since the containment `return`s, an unrelated, correctly-spelled action listed *after* the misspelled one also stops working, which sends the investigation in the wrong direction entirely.

**CandleViewer (a trading order-management system built on this library).** The `EVALUATE → raise(PLACE)` chain in our signal-evaluation machines is exactly the shape of the repro. Written with the obvious spelling, the machine enters `scoring`, computes the signal, and then never raises `PLACE`: the order is **never submitted**, and the machine sits in `scoring` looking healthy — `status == "running"`, no error state, no exception at the call site. A strategy silently stops trading. The mirrored failure is worse on the exit path: an entry list of `[raise(PLACE), assign(recordIntent)]` with a misspelled `raise` also skips `recordIntent`, so the audit record of the intended order is lost as well, and the reconciliation job has no trace to flag. The same pattern recurs throughout our order-lifecycle `raise` chains. Our only mitigation is a bespoke lint rule asserting that any action dict whose `type` resolves to a built-in has a `params` key — i.e. reimplementing the library's own validation outside it.

## Proposed fix

Validate built-in action params at machine-construction time, where the alias table already tells us what is required.

1. **A required/optional parameter table** next to `BUILTIN_ACTION_ALIASES` in `actions.py`:

   ```python
   #: canonical built-in -> (required param names, optional param names)
   BUILTIN_ACTION_PARAM_SPEC: Dict[str, Tuple[frozenset, frozenset]] = {
       RAISE:       (frozenset({"event"}), frozenset({"delay", "id"})),
       SEND_TO:     (frozenset({"to", "event"}), frozenset({"delay", "id"})),
       SEND_PARENT: (frozenset({"event"}), frozenset({"delay", "id"})),
       FORWARD_TO:  (frozenset({"to"}), frozenset()),
       ESCALATE:    (frozenset({"error"}), frozenset()),
       CANCEL:      (frozenset({"id"}), frozenset()),
       STOP_CHILD:  (frozenset({"id"}), frozenset()),
       SPAWN_CHILD: (frozenset({"src"}), frozenset({"id", "systemId", "input"})),
       LOG:         (frozenset(), frozenset({"expr", "label"})),
       # assign / pure / choose / enqueueActions: validated by their own shapes
   }
   ```

2. **Check in `ActionDefinition.__init__`** (`models.py:172`), the single place every action dict is parsed, so both engines and every action position (`entry`, `exit`, transition `actions`, `invoke` `onDone`/`onError`) are covered by one change:

   ```python
   canonical = resolve_builtin(self.type)
   if canonical is not None:
       spec = BUILTIN_ACTION_PARAM_SPEC.get(canonical)
       if spec is not None and not callable(self.params):
           required, optional = spec
           supplied = set(self.params or {})
           missing = required - supplied
           if missing:
               stray = set(config) - {"type", "params"}
               hint = (
                   f" Found {sorted(stray)} at the top level — built-in action "
                   f"parameters must be nested under 'params'."
                   if stray & (required | optional) else ""
               )
               raise InvalidConfigError(
                   f"Built-in action '{self.type}' requires params "
                   f"{sorted(missing)}.{hint}"
               )
   ```

   The `stray` hint is the important half: it turns the error into a fix instruction for the exact mistake this issue is about.

3. **Reject unknown top-level keys generally.** Independently of built-ins, any key other than `type` and `params` in an action dict should at least emit a `logger.warning`, since it is *always* dead config. Making it a hard error for built-ins and a warning for user actions is a reasonable split (a user action's dict is their own data, but it still never reaches their function except via `params`).

4. **Also fix `config.get("type", "UnknownAction")`** — a missing `type` should be an `InvalidConfigError`, not an action named `UnknownAction` that later fails as "not implemented" far from its cause.

5. **Do not remove the runtime containment** in `interpreter.py:635`. It stays as defence in depth; construction-time validation simply means it is no longer the only line of defence. Optionally, promote `None`-param built-in failures from the generic handler to a clearer message, since after this fix they can only arise from a *callable* `params` that returned the wrong shape.

**Backwards compatibility.** This turns configurations that currently parse into configurations that raise. That is the point — every such configuration is already broken — but it is a breaking change for anyone whose machine contains a dead built-in they have not noticed. Mitigation: ship the check behind the LC-34 `strict` flag in the first minor release, warn loudly (`logger.warning` at `create_machine()` time) when not strict, and make it unconditional in the next major. Callable `params` (`models.py` allows a function of `{context, event}`, see `_resolve_params`, `base_interpreter.py:2978`) must be exempted from the static check, since their keys are unknown until runtime.

## Acceptance criteria

- [ ] `BUILTIN_ACTION_PARAM_SPEC` added to `actions.py` and exported, covering `raise`, `sendTo`, `sendParent`, `forwardTo`, `escalate`, `cancel`, `stopChild`, `spawnChild`, `log`.
- [ ] `ActionDefinition.__init__` validates built-in params; validation applies to every accepted alias spelling (`raise` / `raise_` / `xstate.raise`).
- [ ] `tests/test_builtin_action_validation.py::test_raise_without_params_raises_invalid_config` — `{"type": "raise", "event": "X"}` raises `InvalidConfigError` at `create_machine()`.
- [ ] `tests/test_builtin_action_validation.py::test_error_message_points_at_misplaced_top_level_key` — the message contains both `'params'` and the stray key name `event`.
- [ ] `tests/test_builtin_action_validation.py::test_send_to_missing_to_raises` and `::test_send_to_missing_event_raises`.
- [ ] `tests/test_builtin_action_validation.py::test_cancel_and_stop_child_require_id`.
- [ ] `tests/test_builtin_action_validation.py::test_correct_params_spelling_still_parses` — `{"type": "raise", "params": {"event": "X"}}` is unaffected.
- [ ] `tests/test_builtin_action_validation.py::test_callable_params_exempt_from_static_check` — a `params` callable does not raise at construction.
- [ ] `tests/test_builtin_action_validation.py::test_user_action_named_log_is_not_validated_as_builtin` — a user-supplied `log` in `MachineLogic.actions` keeps precedence and is not param-checked (mirrors the runtime resolution order at `interpreter.py:622`).
- [ ] `tests/test_builtin_action_validation.py::test_action_dict_without_type_raises` — replaces the `UnknownAction` fallback.
- [ ] `tests/test_builtin_action_validation.py::test_validation_covers_every_action_position` — `entry`, `exit`, transition `actions`, `invoke.onDone`, `invoke.onError`.
- [ ] `tests/test_builtin_action_validation_sync.py` — the same assertions reaching `SyncInterpreter`.
- [ ] Docs: the built-in action reference shows the `params` nesting explicitly in every example, with a call-out that top-level keys are ignored.
- [ ] `repro/LC-36_builtin-action-params-misspelled.py` exits 0.

## Related

- LC-34 — no strict mode. The natural flag to gate this check behind during the compatibility window; both are instances of "dispatch/config errors should be errors".
- LC-07 — `.child` targets a silent no-op; LC-08 — unknown targets unvalidated; LC-06 — over-forgiving target resolution. Same silent-failure class on the *target* side rather than the *action* side; a single construction-time validation pass should cover all four.
- LC-05 — `raise` outside the macrostep. Same built-in, different defect; a machine hitting both sees a `raise` that neither fires nor sequences correctly.
- LC-01 — an action raising still commits the transition. Explains why the contained `TypeError` here leaves the machine in the target state.
- LC-16 — `sendTo` by invoke id: `sendTo` is the other built-in most exposed to this, via a missing or misplaced `to`.

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
