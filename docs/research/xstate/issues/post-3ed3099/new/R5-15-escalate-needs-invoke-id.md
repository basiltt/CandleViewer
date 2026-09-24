---
r5: R5-15
title: "Bug: escalate() only reaches the parent's onError when the invoke declares an explicit id"
labels: [bug, severity/medium, area/actors]
severity: Medium
repro_script: repro/R5-15_escalate-needs-invoke-id.py
commit: 3ed3099
python: 3.13.7
verified: true
---

## Summary

Round 4's `#130` closed a reproducer showing `escalate` from an invoked
child reaches the parent's `onError`; that reproducer (and the library's own
regression test) always declares an explicit `invoke.id`. `id` is optional
on an `invoke` — the parser defaults it to the hosting state's own id — and
when it is omitted, `escalate`'s parent-lookup logic compares against the
wrong id and the escalation is silently lost: the parent sits in the
invoking state forever, with no `onError` transition, no hook, and no
receipt error. A plain callable service that raises reaches `onError` in
both the explicit-id and id-less shapes, so this defect is specific to the
`escalate` built-in, not to id-less invokes generally.

## Environment

- Commit: `3ed3099` (`main`, unreleased 0.8.1; `__version__` still reports
  `0.8.0`, so this build is identified by commit).
- Python: CPython 3.13.7
- OS: Windows 11 Pro 10.0.26200
- Editable install of the repo into a local venv; no library source
  modified.

## Minimal reproduction

```python
"""R5-15 repro: #130 `escalate` reaches the parent's `onError` only when the
`invoke` declares an explicit `id`.

`id` is OPTIONAL on an `invoke`; the parser defaults it to the state's own
id (`models.py`, `_parse_invoke`: `invoke_id = i_config.get("id", self.id)`),
and the runtime actor address for an id-less invoke keeps that synthesised
id (`interpreter.py::_start_invoked_actor`: `f"{self.id}:{invocation.src}:{uuid4()}"`
only when NOT `invocation.id_is_explicit`... but the ESCALATE handler at
`base_interpreter.py` strips the parent-id prefix off `self.id` and matches
it against the invoke's `id`, which for the id-less shape is the STATE id,
not the synthesised actor id -- so the match fails and the parent never
hears about it. A plain callable service that raises reaches `onError` in
both shapes; this is specific to `escalate`.

Exits 1 while the defect is present, 0 once fixed.
Stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import asyncio
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CHILD = {
    "id": "c",
    "initial": "w",
    "states": {
        "w": {"entry": [{"type": "escalate", "params": {"error": "child exploded"}}]},
    },
}

PARENT = {
    "id": "p",
    "initial": "w",
    # No explicit `id` on the invoke -- legal per the schema, and the
    # library's own default fills one in.
    "states": {"w": {"invoke": {"src": "kid", "onError": "caught"}}, "caught": {}},
}


async def main() -> int:
    logic = MachineLogic(services={"kid": create_machine(CHILD, logic=MachineLogic())})
    interp = Interpreter(create_machine(PARENT, logic=logic))
    await interp.start()

    for _ in range(60):
        if "p.caught" in interp.current_state_ids:
            break
        await asyncio.sleep(0.02)

    states = sorted(interp.current_state_ids)
    status = interp.status
    reached = "p.caught" in states
    await interp.stop()

    print("OBSERVED:")
    print(f"  current_state_ids = {states}")
    print(f"  status            = {status}")
    print(f"  reached_onError   = {reached}")

    print("EXPECTED:")
    print("  current_state_ids = ['p.caught']  (escalate from an id-less invoke")
    print("                       reaches onError exactly like an explicit-id one)")

    print("RESULT:", "PASS" if reached else "FAIL - escalate lost with no explicit invoke.id")
    return 0 if reached else 1


sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED:
  current_state_ids = ['p.w']
  status            = running
  reached_onError   = False
EXPECTED:
  current_state_ids = ['p.caught']  (escalate from an id-less invoke
                       reaches onError exactly like an explicit-id one)
RESULT: FAIL - escalate lost with no explicit invoke.id
```

The full four-case matrix from the battle script (`concurrency/n8b_escalate_needs_invoke_id.py`,
re-run fresh):

```
callable, id=True  -> reached_onError = True
callable, id=False -> reached_onError = True
escalate, id=True  -> reached_onError = True
escalate, id=False -> reached_onError = False   <-- only failing cell
```

## Expected behaviour

XState v5's `invoke.id` is documented as optional — stately.ai/docs/invoke
states the actor gets an auto-generated id when `id` is omitted, and error
events from that actor are still addressed and matched the same way
(`onError` fires regardless of whether the id was chosen by the author or
generated). The library's own contract is the same: `models.py`'s
`_parse_invoke` explicitly defaults `invoke_id` to the state id rather than
rejecting an id-less `invoke`, so an id-less invoke is documented-legal
configuration, not user error. `escalate()` must reach `onError` in that
configuration exactly as it does with an explicit id, matching the plain
callable-service failure path's behaviour in the same script.

## Root cause analysis

Two ids are in play and the `escalate` handler conflates them:

- `models.py:1219` (`_parse_invoke`): `invoke_id = i_config.get("id", self.id)`
  — for the id-less case, `invoke_id` (used to build the `onError`
  transition's event name, `error.platform.<invoke_id>`) is the **state
  id**, e.g. `"w"` for a state whose full id is `"p.w"`.
- `interpreter.py:2263-2267` (`_start_invoked_actor`): the runtime actor
  address is `f"{self.id}:{invocation.id}"` when `invocation.id_is_explicit`,
  else `f"{self.id}:{invocation.src}:{uuid4()}"` — for the id-less case this
  is `"p.w:kid:<uuid>"`, NOT `"p.w:w"`.

`base_interpreter.py:3000-3014` (the `ESCALATE` branch) derives `declared`
from the CHILD's own `self.id` (its own actor id, e.g. `"c"` for a spawned
child machine, or the invoke's runtime address for an invoked one) by
stripping the parent's id prefix, then builds
`ErrorEvent(type=f"xstate.error.actor.{self.id}", ..., src=declared)` and
delivers it via `_deliver(self.parent, escalate_event, ...)`. This event's
`type` is `xstate.error.actor.<child's actual runtime id>`, which for an
invoked child is `xstate.error.actor.p.w:kid:<uuid>` — but the parent's
`onError` transition (built at `models.py:1219`, id-less case) listens for
`error.platform.w`. The two never match: `escalate` emits an
`xstate.error.actor.*`-typed event while the id-less `onError` transition
was registered under `error.platform.<state-id>`. (In the explicit-id case
both still don't literally match by string, but the failing-service path
that DOES work goes through `_report_service_failure`, which emits
`error.platform.{invocation.id}` directly — the id the `onError` transition
was actually built against — while `escalate`'s handler never goes through
that helper at all and mints its own differently-typed event.)

## Impact

General: any machine that uses `escalate` from an invoked child and does
not go out of its way to write an explicit `invoke.id` — the common,
terser, documented-legal shape — loses the escalation silently: no
`onError` transition fires, no hook runs, `last_error` is `None`, and
`status` remains `"running"`, so no health check surfaces the failure.

Order-management scenario: a child order-leg actor that calls `escalate()`
to report a broker rejection up to its parent order-management state (a
natural use of `escalate` for exactly the "abnormal condition needing
supervisor attention" case) is silently dropped whenever the parent's
`invoke` omits `id` — which nothing in the schema or documentation
discourages — leaving the parent stuck in its dispatching state with no
error surfaced anywhere.

## Proposed fix

Route `escalate` through the same completion machinery invoked-service
failures already use (`_report_service_failure` / the invocation's own
`InvokeDefinition.id`) rather than re-deriving an id from `self.id` string
manipulation:

1. Give the child interpreter a back-reference to its owning
   `InvokeDefinition` (or its resolved `invoke_id`) at spawn/invoke time —
   already computed once in `_start_invoked_actor`/`_spawn_actor` — instead
   of re-parsing it out of the actor id string in the `escalate` handler.
2. In the `ESCALATE` branch, build the error event's type from that stored
   `invoke_id` (`f"error.platform.{invoke_id}"`), matching exactly what the
   `onDone`/`onError` transitions were parsed against in `models.py:1219`,
   instead of `f"xstate.error.actor.{self.id}"`.
3. Keep the `xstate.error.actor.*` alias for any handler written against
   the runtime actor id ( `on: {"xstate.error.actor.p:kid": ...}` still
   works), but ALSO deliver — or additionally trigger — the
   `error.platform.<invoke_id>` transition the parser actually registered,
   for both the explicit and id-less shapes.

Compatibility: additive — existing explicit-id machines keep working
because their invoke_id already happens to line up; id-less machines start
receiving an event they should always have received. No public API change.

## Acceptance criteria

- [ ] `repro/R5-15_escalate-needs-invoke-id.py` exits `0`.
- [ ] `tests/test_actors.py::test_escalate_reaches_onError_without_explicit_invoke_id`
      — the id-less shape from this repro reaches `onError`.
- [ ] `tests/test_actors.py::test_escalate_reaches_onError_with_explicit_invoke_id`
      — regression guard for the existing passing case
      (`tests/test_round4_findings.py:1134-1157`).
- [ ] `tests/test_actors.py::test_escalate_matches_error_platform_transition_type`
      — asserts the delivered event type matches what `models.py::_parse_invoke`
      registered the `onError` transition against, for both shapes.
- [ ] Changelog entry noting the id-less `escalate` fix under `#130`
      follow-up.

## Related

- Round-4 issue: `#130` (escalate → parent onError; this issue is the
  id-less configuration `#130`'s own reproducer and regression test never
  covered).
- Register id: `D5-concurrency-4` (§3, `33-r5-findings-register.md`).
- Evidence: `battle-3ed3099/concurrency/n8b_escalate_needs_invoke_id.py`;
  regression test `tests/test_round4_findings.py:1134-1157` (declares
  `"id": "kid"` explicitly, hence the gap going uncaught).

## Verification

- Date: 2026-09-19
- Python: CPython 3.13.7 (`.venv-main`)
- Commit: `3ed3099` (`main`, unreleased 0.8.1)
- `repro/R5-15_escalate-needs-invoke-id.py` re-run fresh: exit `1` (FAIL —
  defect still present), matching the recorded observed output
  (`current_state_ids = ['p.w']`, `reached_onError = False`).
- Root cause re-checked against source: `models.py:1219`
  (`invoke_id = i_config.get("id", self.id)`, exact line match);
  `interpreter.py:2263-2267` (`actor_id = f"{self.id}:{invocation.id}" if
  invocation.id_is_explicit else f"{self.id}:{invocation.src}:{uuid.uuid4()}"`,
  `id_is_explicit` at line 2265, exact match); `base_interpreter.py:2990-3014`
  (the `ESCALATE` branch, `declared = self.id` prefix-stripping and
  `escalate_event = ErrorEvent(type=f"xstate.error.actor.{self.id}", ...,
  src=declared)`, comment explicitly citing `#130` and the mismatch this
  issue reports) — confirms the escalate handler derives its event type from
  the runtime actor id rather than the invoke's declared id used to build
  the `onError` transition, for the id-less case. Cited range `3000-3014`
  is a few lines off the exact anchor (2990) but refers to the same branch.
- Expected-behaviour citation checked: stately.ai/docs/invoke confirms `id`
  is documented as an optional string identifying the actor (`invoke`
  property API, `id` — "A string identifying the actor, unique within its
  parent machine"), consistent with the id-less shape being legal
  configuration, not user error.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 150 --search "escalate invoke id"` — no direct hits beyond the
  tracking issue `#26`; `gh issue view 130` confirms `#130` is CLOSED and
  covers only the explicit-id shape, so this issue correctly frames itself
  as a follow-up deepening `#130` rather than a duplicate.
- `verified: true` set in frontmatter.

