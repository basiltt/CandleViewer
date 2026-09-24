---
r5: R5-14
title: "Bug: Any action named `spawn_*` is hijacked by the built-in spawn resolver before user logic is consulted"
labels: [bug, severity/medium, area/actors]
severity: Medium
repro_script: repro/R5-14_spawn-prefix-hijacks-user-action.py
commit: 3ed3099
python: 3.13.7
verified: true
---

## Summary

`_execute_actions` routes any action whose type starts with `spawn_` (or
`spawn_blocking_`) straight to `_spawn_actor`, checked BEFORE
`machine.logic.actions` is even consulted. Every other built-in action name
(`log`, `assign`, `raise`, `sendTo`, ...) is resolved the opposite way — the
source's own comment states built-ins are used "only when the user has NOT
supplied an action of the same name" — so `spawn_` is the single prefix that
silently claims a name out of the user's own action namespace. A machine
that names an action `spawn_place_order` never runs it; the engine instead
tries to spawn a service called `place_order`, which does not exist, and
fails with a fatal `ActorSpawningError`.

## Environment

- Commit: `3ed3099` (`main`, unreleased 0.8.1; `__version__` still reports
  `0.8.0`, so this build is identified by commit).
- Python: CPython 3.13.7
- OS: Windows 11 Pro 10.0.26200
- Editable install of the repo into a local venv; no library source
  modified.

## Minimal reproduction

```python
"""R5-14 repro: a user-supplied action named `spawn_*` is never called.

`_execute_actions` routes any action whose type starts with `spawn_` /
`spawn_blocking_` to the built-in spawn resolver BEFORE consulting
`machine.logic.actions` -- unlike every other built-in name (`log`,
`assign`, ...), which is resolved only when the user has NOT supplied an
action of the same name. So `spawn_*` is the one prefix that silently
steals a name out of the user's own namespace.

Exits 1 while the defect is present, 0 once fixed.
Stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import asyncio
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {
    "id": "m",
    "initial": "a",
    "context": {},
    "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["spawn_place_order"]}}},
        "b": {},
    },
}


async def main() -> int:
    called = []

    def spawn_place_order(interpreter, ctx, event, action_def):
        called.append("spawn_place_order")

    logic = MachineLogic(actions={"spawn_place_order": spawn_place_order})
    interp = Interpreter(create_machine(CFG, logic=logic))
    await interp.start()

    err = None
    try:
        await interp.send("GO")
        await asyncio.sleep(0.05)
    except BaseException as exc:  # noqa: BLE001
        err = exc

    states = sorted(interp.current_state_ids)
    status = interp.status
    await interp.stop()

    print("OBSERVED:")
    print(f"  user_action_called = {called}")
    print(f"  current_state_ids  = {states}")
    print(f"  status             = {status}")
    print(f"  error              = {err!r}")

    print("EXPECTED:")
    print("  user_action_called = ['spawn_place_order']  (the declared action runs,")
    print("                        exactly like a user-defined 'log' or 'assign' does)")
    print("  current_state_ids  = ['m.b']")

    failed = called != ["spawn_place_order"] or states != ["m.b"]
    print("RESULT:", "FAIL - spawn_* hijacked the user action" if failed else "PASS")
    return 1 if failed else 0


sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED:
  user_action_called = []
  current_state_ids  = ['m.a']
  status             = running
  error              = None
EXPECTED:
  user_action_called = ['spawn_place_order']  (the declared action runs,
                        exactly like a user-defined 'log' or 'assign' does)
  current_state_ids  = ['m.b']
RESULT: FAIL - spawn_* hijacked the user action
```

Under `actionErrorPolicy: "rollback"` (used in the adopting project's
strict-mode config) the fatal `ActorSpawningError` is swallowed and the
machine sits in its source state forever instead of surfacing a crash — see
the register's four-case matrix (`place_all_legs` control vs.
`spawn_all_legs` / `spawn_entry_order` / `spawn_blocking_thing`, all three
silently empty).

## Expected behaviour

The library's own documented contract for built-in action names is
"resolved only when the user has NOT supplied an action of the same name"
(`base_interpreter.py`, comment immediately above the built-in-resolution
branch). This is XState v5's own rule for reserved action types: user-
registered implementations always take precedence over any built-in
resolver for the same string key; a spawning action is otherwise configured
exactly like `xstate`'s `assign`/`raise` actions inside `entry`/`on.actions`
(see stately.ai/docs/actions — "Referencing action implementations" — a
named action resolves to the implementation supplied in the actor's
`options`/`logic`). `spawn_*` should follow the same precedence as every
other built-in prefix in this codebase.

## Root cause analysis

`base_interpreter.py:2829-2844` (`_execute_actions`):

```python
for action_def in actions:
    ...
    if action_def.type.startswith(
        (SPAWN_BLOCKING_PREFIX, "spawn_")
    ) and not is_builtin(action_def.type):
        await self._spawn_actor(action_def, event)
        continue

    impl = self.machine.logic.actions.get(action_def.type)

    # 🎬 Built-in action creators. Resolved only when the user has
    #    NOT supplied an action of the same name, ...
    if impl is None:
        canonical = resolve_builtin(action_def.type)
        ...
```

The `spawn_` branch tests the action's *name string* directly and dispatches
to `_spawn_actor` unconditionally (guarded only by `is_builtin`, which is
irrelevant here — `spawn_place_order` is not itself a canonical built-in
name). It never looks at `self.machine.logic.actions` first, unlike the
`impl is None` check three lines below that every other built-in goes
through. The twelve-line-lower comment describing "only when the user has
NOT supplied an action of the same name" applies to the code path this
branch bypasses.

## Impact

General: any action name chosen by an application author that happens to
start with `spawn_` (a natural, common prefix for "kick off a thing") is
silently unreachable, with no build-time warning from `MachineLogic(strict=
True)` — the collision is invisible until the state is entered at runtime.

Order-management scenario: an OMS state machine that names an action
`spawn_entry_order` or `spawn_all_legs` (both used in the adopting project's
catalogue) never places the order; instead the engine attempts to spawn a
non-existent service, throws a fatal `ActorSpawningError`, and — under
`actionErrorPolicy: "rollback"` — the error is absorbed and the machine
appears healthy while stuck in its entry state indefinitely.

## Proposed fix

Move the `machine.logic.actions` lookup ahead of the `spawn_` prefix check,
matching the precedence every other built-in already has:

```python
impl = self.machine.logic.actions.get(action_def.type)
if impl is None and action_def.type.startswith(
    (SPAWN_BLOCKING_PREFIX, "spawn_")
):
    await self._spawn_actor(action_def, event)
    continue
if impl is None:
    canonical = resolve_builtin(action_def.type)
    ...
else:
    await self._run_user_action(impl, action_def, event)
```

Compatibility: a machine that never registered a colliding `spawn_*` action
is unaffected. A machine that (accidentally or intentionally) shadowed
`spawn_*` now runs its own action instead of spawning — this is a
behavioural change but strictly fixes a documented-contract violation, so it
should be called out in the changelog. `MachineLogic(strict=True)` could
additionally warn at build time when a user action name collides with a
recognised built-in prefix.

## Acceptance criteria

- [ ] `repro/R5-14_spawn-prefix-hijacks-user-action.py` exits `0`.
- [ ] `tests/test_actions.py::test_user_action_named_spawn_prefix_takes_precedence`
      — a `spawn_*`-named user action registered in `MachineLogic.actions`
      runs instead of triggering `_spawn_actor`.
- [ ] `tests/test_actions.py::test_spawn_blocking_prefix_still_spawns_when_unregistered`
      — the built-in spawn path is unchanged when no user action shadows it.
- [ ] `tests/test_actions.py::test_spawn_prefix_precedence_matches_other_builtins`
      — parametrised over `log`, `assign`, `spawn_x` confirming identical
      precedence rules across all built-in name families.
- [ ] Changelog entry noting the precedence fix and its (rare) behavioural
      change for machines that named an action `spawn_*`.

## Related

- Register id: `D-2` (§3, `33-r5-findings-register.md`).
- Evidence: `battle-3ed3099/contracts/repro/r2_spawn_prefix_steals_action_name.py`.
- Round-4 issue tracking `#41` (comment cited above, `spawn_blocking_` as a
  distinct mode) documents the intended precedence rule this issue violates.

## Verification

- Date: 2026-09-19
- Python: CPython 3.13.7 (`.venv-main`)
- Commit: `3ed3099` (`main`, unreleased 0.8.1)
- `repro/R5-14_spawn-prefix-hijacks-user-action.py` re-run fresh: exit `1`
  (FAIL — defect still present), matching the recorded observed output.
- Root cause re-checked against source: `base_interpreter.py:2836`
  (`(SPAWN_BLOCKING_PREFIX, "spawn_")` branch) and `:2844`
  (`impl = self.machine.logic.actions.get(action_def.type)`, three lines
  below the spawn-dispatch branch it should precede) — confirms the
  spawn-prefix check runs before the user-action lookup, as described.
  Cited range `2829-2844` is off by a few lines from the exact anchors
  (2836/2844) after intervening edits but refers to the same branch.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 150 --search "spawn_ hijack"` — no matches; not a duplicate of any
  existing issue. Round-4 `#41` (cited under Related) is closed and concerns
  `spawn_blocking_` as a distinct mode, not this precedence bug.
- `verified: true` set in frontmatter.

