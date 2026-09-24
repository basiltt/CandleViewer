---
r4: R4-20
title: "Bug: escalate() from an invoked child is unroutable -- reaches neither onError nor \"*\""
labels: [bug, severity/low, area/actors, area/events]
severity: Low
repro_script: repro/R4-20_escalate_unroutable.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

`escalate()` is the documented mechanism for an invoked child machine to
report a failure up to its parent for handling via `onError` on the invoking
state. In this build the escalation event's `type`/`src` are minted from the
*runtime* actor id (`self.id`, e.g. `parent.id:explicit_id`), while the
transition collector matching `onError` requires the event's `src` to equal
the invocation's *declared* id (`inv.id`, e.g. `"kid"`). The two never match,
so the escalation silently fails to route to `onError` -- and because the
event is also treated as a system event, it does not even reach a catch-all
`"*"` handler. A documented supervision primitive is 100% silently lost, and
worse than having no `escalate()` at all, because the `onError` config looks
correct on inspection and a code reviewer sees nothing wrong.

## Environment

- Commit: `5e07ba8` (`main`, unreleased 0.8.1; `__version__` reports `0.8.0`)
- Python: 3.13.7 (CPython, 64-bit)
- OS: Windows 11 Pro (10.0.26200)
- Install: editable (`pip install -e .`) into a project venv
- Found by our adoption audit (#26), round 4.

## Minimal reproduction

```python
"""R4-20: `escalate()` from an invoked child is unroutable -- it reaches
neither `onError` nor `"*"`, because the escalation event's `type`/`src` are
minted from the runtime actor id, not the declared invoke id."""
import asyncio
import logging

logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, create_machine

got = []


def spy(i, c, e, a):  # noqa: ANN001
    got.append(e.type)


child = create_machine(
    {
        "id": "child",
        "initial": "w",
        "states": {"w": {"entry": [{"type": "escalate", "params": {"error": "child failed"}}]}},
    },
    logic=MachineLogic(),
)

CFG = {
    "id": "m",
    "initial": "run",
    "states": {
        "run": {
            "invoke": {"id": "kid", "src": "childMachine", "onError": "caught"},
            "on": {"*": {"actions": ["spy"]}},
        },
        "caught": {},
    },
}


async def main() -> int:
    i = await Interpreter(
        create_machine(CFG, logic=MachineLogic(services={"childMachine": child}, actions={"spy": spy}))
    ).start()
    await asyncio.sleep(0.4)
    states = sorted(i.current_state_ids)
    print("OBSERVED parent state     :", states)
    print("OBSERVED events seen by '*':", got)
    print("EXPECTED: parent reaches ['m.caught'] via onError")
    ok = "m.caught" in states
    print("RESULT:", "PASS" if ok else "FAIL (escalate unroutable to onError)")
    await i.stop()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED parent state     : ['m.run']
OBSERVED events seen by '*': []
EXPECTED: parent reaches ['m.caught'] via onError
RESULT: FAIL (escalate unroutable to onError)
```

The parent stays in `m.run`; its `onError` transition to `caught` never
fires, and the catch-all `"*"` handler sees zero events -- the escalation
vanishes entirely, indistinguishable from the child never having called
`escalate()` at all.

## Expected behaviour

XState v5 documents `escalate` (via `sendParent({ type: 'xstate.error.actor.<childId>', ... })`
patterns and the newer `emit`/error propagation) as reaching the parent's
`onError` for the invocation that spawned the failing child
(https://stately.ai/docs/invoke#invoke-and-error-handling: "if the invoked
actor produces an error, the invoking machine can handle it with `onError`").
The **declared** invoke id (`"kid"` in this repro's `invoke.id`) is the only
identifier a machine's config can name; the transition-matching code should
therefore key on the same declared id used everywhere else an invocation is
addressed (`onDone`/`onError` for normal service completion already do,
per `_collect_eligible_transitions`).

## Root cause analysis

`src/xstate_statemachine/base_interpreter.py:2686-2703`, the `ESCALATE`
branch of the action-execution dispatcher:

```python
elif canonical == ESCALATE:
    error_payload = params.get("error")
    err = (
        error_payload
        if isinstance(error_payload, BaseException)
        else RuntimeError(str(error_payload))
    )
    escalate_event = ErrorEvent(
        type=f"xstate.error.actor.{self.id}", error=err, src=self.id
    )
    if self.parent is not None:
        await self._deliver(self.parent, escalate_event, None, None)
    ...
```

`self.id` here is the *child's own runtime actor id* (assigned by the actor
system, e.g. `"m:1.kid"` or similar runtime-namespaced value depending on
spawn path) -- not the string the parent's `invoke.id` config declared
(`"kid"`).

The parent's transition matching,
`_collect_eligible_transitions` (`base_interpreter.py:3642` /
match block at `3742-3749`):

```python
if isinstance(event, (DoneEvent, ErrorEvent)):
    for inv in current.invoke:
        if event.src == inv.id:
            for t in inv.on_done + inv.on_error:
                if t.event == event.type and _passes(t):
                    eligible.append(t)
```

requires `event.src == inv.id`, i.e. the **declared** id from the parent's
own config (`"kid"`). Since `escalate_event.src` was set to `self.id`
(the *child's* runtime id, not `"kid"`), this comparison always fails for an
escalated error, and the transition is never collected. This is the same
data (declared invoke id) that a normal service's `DoneEvent`/`ErrorEvent`
already carry correctly via a different construction path -- `escalate` is
the outlier that mints its own `src`.

Additionally, `xstate.error.actor.*` events are recognized elsewhere in the
codebase as system/error events (see the taxonomy comment at
`base_interpreter.py:272`), and the wildcard `"*"` handler in this build
does not receive them either, so there is no fallback path a defensive
config could use to observe the escalation.

## Impact

**General users.** Any use of `escalate()` inside an invoked child machine
silently fails to reach the parent's `onError`, regardless of how the
`invoke` block is configured. The failure mode is worse than a missing
feature: the config (`invoke: {id: "kid", onError: "caught"}`) is exactly
what the documentation prescribes and passes any code review, yet the
transition never fires. There is no exception, no log at the point of
mismatch, and no wildcard fallback -- an escalated failure is simply
absorbed.

**Concrete order-management scenario.** A child actor supervises a specific
venue connection and calls `escalate({error: "order rejected"})` on a hard
rejection so the parent order machine can route to a cancellation/retry
state via `onError`. With this defect, the parent never learns the child
escalated; it continues to believe the order is progressing normally while
the child has already given up. A supervision hierarchy that looks correct
in review provides zero actual supervision.

## Proposed fix

**Design.** Mint the escalation event's `type`/`src` from the child's
**declared** invoke id (as seen from the parent), not its runtime actor id,
so `_collect_eligible_transitions`'s `event.src == inv.id` check succeeds.

1. The child actor needs access to the id its parent declared for it in
   `invoke.id` -- this is very likely already threaded through at spawn time
   (it is what the actor is registered under in the parent's actor
   registry / `self._actors`); use that value instead of `self.id` when
   constructing `escalate_event` at `base_interpreter.py:2697-2698`.
2. If the spawned child does not currently retain its declared parent-facing
   id distinctly from its runtime id, add a small attribute
   (`self._declared_invoke_id` or similar) set at invoke time, mirroring how
   normal `DoneEvent`/`ErrorEvent` sources are populated for the same
   invocation so both paths agree.
3. Add a regression test asserting `onError` fires for `escalate()` on both
   `Interpreter` and `SyncInterpreter`, and that `"*"` also observes the
   event (since it is a normal application-level error, this should not be
   suppressed from wildcard handlers either -- or if suppression is
   intentional for `xstate.error.actor.*`, document that explicitly since it
   currently reads as an unintended side effect of a separate mismatch).

**Compatibility.** Behavior-only fix: the `type`/`src` string values change,
but no application-visible API changes; any config that depended on the
current (broken) mismatch was, by construction, never receiving the event.

**Alternatives considered.**
1. *Change `_collect_eligible_transitions` to match on runtime id instead.*
   Rejected: the parent's config can only name the declared id; the
   collector has no way to learn the child's runtime id without a lookup
   the current code does not perform, and every other invoke-addressed
   mechanism (`onDone`) already keys on the declared id, so this alternative
   would create a second inconsistency instead of removing the first.

## Acceptance criteria

- [ ] `escalate()` from an invoked child reaches the parent's `onError`
      transition for that invocation, on both engines.
- [ ] `repro/R4-20_escalate_unroutable.py` exits `0`.
- [ ] `tests/test_escalate.py::test_escalate_reaches_parent_on_error_async`
- [ ] `tests/test_escalate.py::test_escalate_reaches_parent_on_error_sync`
- [ ] `tests/test_escalate.py::test_escalate_type_uses_declared_invoke_id`
- [ ] Documentation for `escalate` states explicitly which id (declared vs.
      runtime) the resulting event's `src`/`type` carries.

## Related

- Register row `R4-20` (filed High, DOWNGRADE to Low). Source id
  `D-semantics-2`; unmerged 1:1.
- Evidence: `battle-5e07ba8/semantics/repro/d6_escalate_route.py`.
- **`R4-35`** -- `sendTo` with an unresolvable target is also silently
  dropped; together the two are the actor-messaging paths with no observable
  failure signal.
- Meta: our adoption audit **#26**.

## Verification

- Date: 2026-09-19
- Python: 3.13.7 (`.venv-main`)
- Commit: `5e07ba8`
- Ran `repro/R4-20_escalate_unroutable.py` in a fresh process: exit code `1`,
  output matches the Observed section verbatim (parent stays in `['m.run']`,
  `"*"` handler sees zero events).
- Root cause confirmed: `base_interpreter.py`'s `ESCALATE` branch mints
  `escalate_event = ErrorEvent(type=f"xstate.error.actor.{self.id}", ...,
  src=self.id)` using the child's runtime id, while
  `_collect_eligible_transitions`'s invoke-matching block requires
  `event.src == inv.id` (the parent's *declared* invoke id) -- confirmed by
  direct inspection of both sites; the two ids never match.
- XState v5 `onError` semantics confirmed against
  https://stately.ai/docs/invoke: "errors thrown by invoked actors can be
  handled directly" via `onError`, keyed to the invocation, consistent with
  the issue's claim that the declared invoke id is the only identifier a
  parent's config can name.
- Duplicate check: `gh issue list --search "escalate"` surfaces **#97**
  (`escalate` emits a plain `Event` instead of `ErrorEvent`, so
  `event.error` raises `AttributeError`) -- a related but *distinct* defect
  (wrong event class/attribute access) from this one (wrong `src`/`type`
  breaking `onError` routing entirely); no overlap in root cause or repro.
  No other duplicate found.
- Self-contained; no project-name/label leak.
