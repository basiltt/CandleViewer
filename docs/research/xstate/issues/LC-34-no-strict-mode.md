---
lc: LC-34
title: "Feature: no strict mode — event names and payloads are unvalidated, so a typo'd event is a silent no-op"
labels: [enhancement, severity/high, area/interpreter, candleviewer]
severity: High
blocks_adoption: true
repro_script: repro/LC-34_no-strict-mode.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

There is no strict mode anywhere in the library: neither `create_machine()` nor `Interpreter.__init__` accepts a `strict` option, and a grep for `strict` across the runtime source returns nothing. Consequently `await interpreter.send("FILLL")` — a typo for `FILL` — returns normally, leaves `status == "running"`, leaves the state unchanged, and gives the caller nothing to branch on. It is indistinguishable, from both the API and the log, from a correctly-named event that the current state legitimately does not handle.

Payloads are equally unchecked: `send("FILL", qty="not-a-number", side=object())` is accepted verbatim and stored in the event, so a type error introduced at the boundary surfaces much later inside an action or guard — or never, if the value is only ever stored in context. For a system where events are commands with consequences, a misdirected command that fails silently is the worst possible failure mode.

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, installed with `pip install -e .`
- Python: 3.13.7
- OS: Windows 11 (x64)

## Impact

**General users.** The typo case is the whole story: a one-character slip in an event name is observationally identical to a correct call. There is no exception, no return value, no status change and no distinguishable log line, so the bug survives code review, passes tests that assert "no exception was raised", and is discovered only when someone notices the machine did not move. Because the same silence covers internal sends (`raise`, `sendTo`, `sendParent`, `forwardTo`), a machine-of-machines design has no dispatch safety net anywhere. Python cannot borrow XState's compile-time solution, so without a runtime flag there is no solution at all.

**CandleViewer (a trading order-management system built on this library).** Events here are commands with money attached: `FILL`, `CANCEL`, `REJECT`, `AMEND`. A misdirected command that fails silently is the worst available failure mode — a `CANCEL` that is a no-op leaves a live order on the exchange while the operator believes it is cancelled, and a typo'd `FILL` leaves an executed order recorded as pending. Unvalidated payloads compound it: `send("FILL", qty="100")` stores a string where every downstream consumer expects a float, and the resulting error surfaces inside an action — where, per this library's containment behaviour, it is logged and swallowed — or never, if the value is only written to context. The mitigation forced on us is the gateway below, which is a partial defence at best.

## Current workaround and why it is insufficient

The only defence available today is to wrap every `send()` behind an application-level gateway that owns a closed enumeration of event names per machine family and validates payloads before dispatch:

```python
from enum import StrEnum

from pydantic import BaseModel


class OrderEvent(StrEnum):          # hand-maintained, must mirror the config
    FILL = "FILL"
    CANCEL = "CANCEL"


class FillPayload(BaseModel):
    qty: float
    price: float


class MachineGateway:
    """The validation layer the library does not provide."""

    def __init__(self, interp, events: type[StrEnum], schemas: dict) -> None:
        self._interp, self._events, self._schemas = interp, events, schemas

    async def send(self, event_type: str, **payload):
        if event_type not in set(self._events):        # closed-world check
            raise ValueError(f"unknown event {event_type!r}")
        model = self._schemas.get(event_type)
        if model is not None:
            payload = model(**payload).model_dump()    # payload validation
        return await self._interp.send(event_type, **payload)
```

This is insufficient for four reasons:

1. **It is not authoritative.** The `StrEnum` is a hand-maintained copy of the descriptor set in the machine config. The two drift the moment anyone edits the JSON, and the drift is silent in exactly the direction that matters — an event removed from the config still passes the gateway and becomes a no-op again.
2. **It cannot be enforced.** Nothing stops a caller from holding the raw `Interpreter` and calling `send()` directly. We enforce this with a lint rule, which is a social control over a language-level affordance.
3. **It does not cover internal sends.** Events raised by the machine itself — `raise`, `sendTo`, `sendParent`, `forwardTo`, `after` — never pass through the gateway. A typo'd `raise` target (see LC-36) is still a silent no-op, and that is the majority of the event traffic in a machine-of-machines design.
4. **It cannot distinguish "unknown" from "not handled here".** Even with the enum, a valid event sent to a state that does not handle it is still swallowed. Strict mode is exactly the option that lets an application declare which of those two it considers a bug.

## Minimal reproduction

```python
"""LC-34 repro: no strict mode — unknown event types and unvalidated payloads.

Three observations:
  1. `send("TYPOD_EVENT")` on a machine that has no such descriptor is a
     silent no-op: no exception, no error status, nothing a caller can
     branch on.
  2. Arbitrary payloads are accepted with no schema: `send("FILL",
     qty="not-a-number")` is stored verbatim in the event.
  3. There is no `strict` option anywhere: neither `create_machine()` nor
     `Interpreter()` accepts one (grep: no `strict=` in the runtime source).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import sys

from xstate_statemachine import Interpreter, create_machine

logging.disable(logging.CRITICAL)

CFG = {
    "id": "order",
    "initial": "pending",
    "context": {"qty": 0},
    "states": {
        "pending": {"on": {"FILL": {"target": "filled"}}},
        "filled": {"type": "final"},
    },
}


async def main() -> int:
    ok = True

    # 1) No `strict` option exists on either public constructor.
    cm_params = list(inspect.signature(create_machine).parameters)
    it_params = list(inspect.signature(Interpreter.__init__).parameters)
    print(f"OBSERVED create_machine params = {cm_params}")
    print(f"OBSERVED Interpreter.__init__ params = {it_params}")
    print("EXPECTED a `strict` option on at least one of them")
    if "strict" in cm_params or "strict" in it_params:
        ok = False  # not reproduced

    # 2) A typo'd event is a silent no-op.
    interp = await Interpreter(create_machine(CFG)).start()
    before = list(interp.current_state_ids)
    raised = None
    try:
        await interp.send("FILLL")  # typo: should be FILL
        await asyncio.sleep(0.05)
    except Exception as exc:  # pragma: no cover - would be the fix
        raised = exc
    print(
        f"OBSERVED send('FILLL'): raised={raised!r} "
        f"status={interp.status} states={list(interp.current_state_ids)} "
        f"(was {before})"
    )
    print("EXPECTED under strict=True: an error naming the unknown event type")
    if raised is not None:
        ok = False

    # 3) Payloads are unvalidated.
    seen: list = []
    machine2 = create_machine(CFG)
    interp2 = await Interpreter(machine2).start()
    interp2.subscribe(lambda snap: seen.append(dict(snap.context)))
    await interp2.send("FILL", qty="not-a-number", side=object())
    await asyncio.sleep(0.05)
    print(
        f"OBSERVED send('FILL', qty='not-a-number') accepted; "
        f"status={interp2.status} states={list(interp2.current_state_ids)}"
    )
    print("EXPECTED under strict=True: payload validated against a schema")
    await interp.stop()
    await interp2.stop()

    print(
        "RESULT:",
        "REPRODUCED (no strict mode; unknown events and payloads unvalidated)"
        if ok
        else "NOT REPRODUCED",
    )
    return 1 if ok else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED create_machine params = ['config', 'logic', 'logic_modules', 'logic_providers']
OBSERVED Interpreter.__init__ params = ['self', 'machine', 'input']
EXPECTED a `strict` option on at least one of them
OBSERVED send('FILLL'): raised=None status=running states=['order.pending'] (was ['order.pending'])
EXPECTED under strict=True: an error naming the unknown event type
OBSERVED send('FILL', qty='not-a-number') accepted; status=done states=['order.filled']
EXPECTED under strict=True: payload validated against a schema
RESULT: REPRODUCED (no strict mode; unknown events and payloads unvalidated)
```

(exit code 1)

The third line is the whole issue: a one-character typo in an event name produced no exception, no status change, no state change and no return value — the call is observationally identical to a successful no-op.

## Expected behaviour

XState v4 shipped a machine-level `strict` option that turned an unhandled event into a thrown error; it was removed in v5 and is *not* present in the current v5 docs. (The v4 docs at <https://xstate.js.org/docs/guides/machines.html> are archived and no longer maintained, and the `strict` flag is not described on that page today, so this issue does not rest on it — it is cited only as precedent that the concern is a long-standing one in the XState lineage.)

In v5 the closed world over event names is expressed at the *type* level instead, via `setup({ types })`. From <https://stately.ai/docs/typescript> under "Specifying types":

> "The recommended way to strongly type your machine is to use the `setup(...)` function"

and:

> "These types will be inferred throughout the machine config and in the created machine and actor so that methods such as `machine.transition(...)` and `actor.send(...)` will be type-safe."

That last sentence is the guarantee this issue is asking for: in XState, `actor.send({ type: 'FILLL' })` is a **compile-time error** when the event union is declared. The typo case simply cannot reach the runtime.

XState's own guidance on wildcard transitions at <https://stately.ai/docs/transitions> shows that unhandled events are ignored *by design* at the statechart level —

> "A wildcard transition has the least priority; it will only be taken if no other transitions are enabled."

— which is correct for the *not handled in this state* case, but says nothing about an event type the machine has never heard of. The distinction this issue asks for is precisely:

- event type **is** in the machine's descriptor set but the current state has no transition for it → ignore (current behaviour, correct);
- event type is **absent from the entire descriptor set** → under `strict=True`, raise.

Python has no TypeScript-style compile-time checking available, so the v5 type-level mechanism has to be re-expressed as a runtime option; hence a `strict` flag plus an optional payload schema is the faithful port.

## Root cause analysis

- `src/xstate_statemachine/interpreter.py:109` — `Interpreter.__init__(self, machine, input=None)`. No `strict` parameter, and no field to store one. `create_machine(config, logic, logic_modules, logic_providers)` likewise has no slot for machine-level options.
- `src/xstate_statemachine/base_interpreter.py:504-531` — `_coerce_event()` is the single normalisation point for every inbound event. It accepts any `str` as `Event(type=event)` with no reference to the machine at all; the only validation it performs is that a dict has a string `type` key. This is the natural place a strict check belongs and the reason its absence is total: nothing on the path from `send()` to the queue ever consults the machine's descriptor set.
- `src/xstate_statemachine/base_interpreter.py:2362+` — `_matching_descriptors(on_map, event_type)` resolves an event type against the `on` keys of the *currently active* states only, returning `[]` when nothing matches. A `[]` result means "no transition", and the caller treats that as a normal quiescent outcome. There is no machine-wide index of every declared descriptor, so even a would-be strict check has no set to test against today — one has to be built at `create_machine()` time by walking all `StateNode.on` keys (plus `after` / `invoke` `onDone` / `onError` generated types).
- A grep for `strict` across `src/` returns hits only in the CLI (`cli/validation.py`, `cli/__main__.py` — an unrelated config-comparison flag) and in unrelated comments; there is nothing in the runtime engine.
- Payload: `Event(type=..., payload=payload)` stores the kwargs verbatim; `models.py` has no schema hook, and there is no `types`/`schema` key read from the machine config. `send("E", qty="not-a-number")` is accepted silently, unknown events are ignored rather than raised, and sending `EE` instead of `E` leaves the machine unchanged while emitting log lines that are byte-identical in shape to a normal unhandled-event log — so even log-scraping cannot separate the two cases.

## Proposed API

A machine-level `strict` option plus an optional event-schema registry, both additive and default-off.

```python
from xstate_statemachine import Interpreter, UnknownEventError, create_machine

machine = create_machine(
    {
        "id": "order",
        "initial": "pending",
        "strict": True,                       # config-level, travels with JSON
        "states": {
            "pending": {"on": {"FILL": "filled", "CANCEL": "cancelled"}},
            "filled": {"type": "final"},
            "cancelled": {"type": "final"},
        },
    }
)

interp = await Interpreter(machine).start()          # or Interpreter(m, strict=True)

await interp.send("FILL", qty=1.0)                   # ok
await interp.send("CANCEL")                          # ok: declared, handled elsewhere
await interp.send("FILLL")                           # ❌ UnknownEventError:
#   Event 'FILLL' is not declared by machine 'order'.
#   Known events: CANCEL, FILL. Did you mean 'FILL'?
```

Payload validation, opt-in and dependency-free (any object exposing a `validate`/`__call__` that raises works, so pydantic, `TypedDict` adapters or hand-written validators all fit):

```python
from pydantic import BaseModel


class Fill(BaseModel):
    qty: float
    price: float


machine = create_machine(CFG, event_schemas={"FILL": Fill})

await interp.send("FILL", qty="not-a-number")
# ❌ InvalidEventPayloadError: payload for 'FILL' failed validation:
#      qty: Input should be a valid number
```

Design notes:

1. **Build the descriptor set once.** At `create_machine()` time, walk every `StateNode` and collect: all `on` keys (expanding partial descriptors `"mouse.*"` and the bare `"*"` into a prefix matcher), every `after` delay's generated type, and every `invoke` `onDone`/`onError` generated type. Store as `machine.known_events`. A machine containing `"*"` disables the unknown-event check for obvious reasons.
2. **Check at the single choke point.** Extend `_coerce_event()` (`base_interpreter.py:504`) — or a thin wrapper called from `send()` — to test `event.type` against `machine.known_events` when `strict` is on. That one site covers external `send()`, and routing it through the same helper from `_deliver()` (`interpreter.py:785`) extends the guarantee to `raise` / `sendTo` / `sendParent` / `forwardTo`, which is what closes workaround gap 3 above.
3. **New exception types.** `UnknownEventError` and `InvalidEventPayloadError`, both subclasses of the existing `XStateMachineError` base so a caller can catch the family. The message must list the known events and offer a `difflib.get_close_matches` suggestion — the typo case is the primary use.
4. **Async `send()` is fire-and-forget.** Today `Interpreter.send()` returns before processing (see LC-42). A strict violation must therefore be raised **synchronously at the call site**, before the event is queued, or the caller still cannot catch it. That places the check in `send()` prior to `_event_queue.put()`, not in the run loop.
5. **Scope overlap with LC-08.** The same `strict` flag should reject unknown *transition targets* at `create_machine()` time (LC-08) and unrecognised built-in action params (LC-36). One option, one mental model: "strict means configuration and dispatch errors are errors, not no-ops."
6. **Relationship to LC-35.** Typed context/events (`setup({types})` analogue) is the compile-time half of the same problem; `strict` is the runtime half and is independently useful. They should share the `event_schemas` registry so declaring a schema once serves both.

**Backwards compatibility.** Fully additive. `strict` defaults to `False` and `event_schemas` to `None`, so every existing machine behaves exactly as today. No deprecation is needed now; a future major version could flip the default to `True` after the option has been available for a release, with the flip announced in the `CHANGELOG`.

## Acceptance criteria

- [ ] `strict` accepted both as a machine-config key and as `Interpreter(machine, strict=True)` / `SyncInterpreter(machine, strict=True)`; `inspect.signature(Interpreter.__init__)` contains `strict`.
- [ ] `UnknownEventError` and `InvalidEventPayloadError` exported from `xstate_statemachine` and subclassing the library's base error.
- [ ] `machine.known_events` exposes the full declared descriptor set, including `after`- and `invoke`-generated event types.
- [ ] `tests/test_strict.py::test_unknown_event_raises_under_strict` — `send("FILLL")` raises `UnknownEventError` naming the event and listing known events.
- [ ] `tests/test_strict.py::test_unknown_event_error_suggests_close_match` — the message contains `Did you mean 'FILL'?`.
- [ ] `tests/test_strict.py::test_declared_but_unhandled_event_is_still_ignored` — an event in the descriptor set but not handled by the current state is a no-op even under `strict=True` (the XState-conformant half).
- [ ] `tests/test_strict.py::test_wildcard_descriptor_disables_unknown_check` — a machine with an `"*"` descriptor accepts anything under `strict=True`.
- [ ] `tests/test_strict.py::test_partial_descriptor_counts_as_known` — `"mouse.*"` makes `mouse.click` a known event.
- [ ] `tests/test_strict.py::test_strict_raises_synchronously_before_queueing` — the error surfaces from the `await send(...)` call itself, and the event never reaches the queue.
- [ ] `tests/test_strict.py::test_internal_raise_of_unknown_event_is_strict` — a `raise` built-in targeting an undeclared event type errors under `strict=True` instead of no-op'ing.
- [ ] `tests/test_strict.py::test_after_and_invoke_generated_events_are_known` — no false positive from `xstate.after.*` / `done.invoke.*` under `strict=True`.
- [ ] `tests/test_strict.py::test_payload_schema_validates` and `::test_payload_schema_rejects` — `event_schemas={"FILL": Fill}` accepts a valid payload and raises `InvalidEventPayloadError` for an invalid one.
- [ ] `tests/test_strict.py::test_non_strict_default_is_unchanged` — without the flag, all of the above are silent no-ops exactly as today.
- [ ] `tests/test_strict_sync.py` — the same unknown-event and payload assertions for `SyncInterpreter`.
- [ ] Docs gain a "Strict mode" section covering the unknown-vs-unhandled distinction and payload schemas.
- [ ] `repro/LC-34_no-strict-mode.py` exits 0.

## Related

- LC-35 — no typed context or events (`TContext` bound to `Dict[str, Any]`, no `setup({types})` analogue). Grouped with this issue in the register; shares the `event_schemas` registry.
- LC-36 — built-in action params silently ignored when misspelled. The internal-send half of the same silent-no-op class; `strict` should cover it.
- LC-08 — unknown transition targets unvalidated; LC-07 — `.child` targets a silent no-op; LC-06 — over-forgiving target resolution. All configuration-time members of the same family, all in scope for one `strict` flag.
- LC-03 — unhandled events discarded. Defines the boundary: LC-03's ignore behaviour is *correct* for declared events and must be preserved by the fix.
- LC-42 — `send()` cannot answer synchronously. Constrains the fix: strict violations must raise before queueing.

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
