---
r4: R4-19
title: "Bug: an invoked child's `output` is discarded — `done.invoke` carries the child's private `context` instead"
labels: [bug, severity/high, area/actors, area/interpreter, area/sync-interpreter]
severity: High
repro_script: repro/R4-19_invoke_done_carries_child_context_not_output.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

When an invoked child machine reaches a top-level final state that declares
`output`, the parent's `done.invoke.<id>` event carries the child's **entire
`context`** rather than its resolved `output`. Both engines do this, at
`interpreter.py:2078` and `sync_interpreter.py:1179`, which both build
`DoneEvent(data=child.context)`. `StateNode.output` is parsed
(`models.py:871`) and the library already has a resolver for it
(`base_interpreter.py:3235`), so the declared value is computed-and-discarded
on this path. This is a double defect: the child's computed result is silently
lost, **and** the child's full private context — credentials, intermediate
working state, anything the child held — is handed to the parent in its place.
The parent still reaches its `onDone` target, so this is a wrong payload on a
*succeeding* path, which no error handling will catch.

## Environment

- Commit: `5e07ba8` (`main`, unreleased 0.8.1; `__version__` reports `0.8.0`)
- Python: 3.13.7 (CPython, 64-bit)
- OS: Windows 11 Pro (10.0.26200)
- Install: editable (`pip install -e .`) into a project venv
- Found by our adoption audit (#26), round 4.

## Minimal reproduction

```python
# -*- coding: utf-8 -*-
"""R4-19: an invoked child's `output` is discarded; `done.invoke` carries the
child's private `context` instead.

`interpreter.py` (async) and `sync_interpreter.py` (sync) both build
`DoneEvent(data=child.context)`. XState v5 delivers the child's resolved
`output` on `done.invoke.<id>`. The result is a double defect: the computed
result is silently lost, and the child's full internal context leaks to the
parent.

Exits 1 while the defect is present, 0 once fixed.
"""
from __future__ import annotations

import asyncio

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

CHILD = {
    "id": "kid",
    "initial": "w",
    "context": {"secret_api_key": "sk-PRIVATE", "ctxkey": 1},
    "states": {
        "w": {"always": "fin"},
        "fin": {"type": "final", "output": {"code": 7}},
    },
}
PARENT = {
    "id": "m",
    "initial": "run",
    "states": {
        "run": {
            "invoke": {
                "id": "kid",
                "src": "kidm",
                "onDone": {"target": "done", "actions": ["cap"]},
            }
        },
        "done": {},
    },
}

seen = {}


def cap(interp, ctx, event, action_def):  # noqa: ANN001
    seen["data"] = event.data


def parent(engine_child):
    return create_machine(
        PARENT,
        logic=MachineLogic(actions={"cap": cap}, services={"kidm": engine_child}),
    )


async def main() -> int:
    expected = {"code": 7}

    i = Interpreter(parent(create_machine(CHILD, logic=MachineLogic())))
    await i.start()
    await asyncio.sleep(0.4)
    async_data = seen.get("data")
    await i.stop()

    seen.clear()
    s = SyncInterpreter(parent(create_machine(CHILD, logic=MachineLogic())))
    s.start()
    sync_data = seen.get("data")

    print("OBSERVED: async done.invoke.kid data = %r" % (async_data,))
    print("OBSERVED: sync  done.invoke.kid data = %r" % (sync_data,))
    print("EXPECTED: both = %r (the child's declared final `output`), and the "
          "child's private context key 'secret_api_key' must NOT appear."
          % (expected,))

    leaked = [
        name
        for name, d in (("async", async_data), ("sync", sync_data))
        if isinstance(d, dict) and "secret_api_key" in d
    ]
    if leaked:
        print("OBSERVED: child private context LEAKED on:", ", ".join(leaked))

    ok = async_data == expected and sync_data == expected
    print("RESULT:", "PASS" if ok else "FAIL (child output discarded)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED: async done.invoke.kid data = {'secret_api_key': 'sk-PRIVATE', 'ctxkey': 1}
OBSERVED: sync  done.invoke.kid data = {'secret_api_key': 'sk-PRIVATE', 'ctxkey': 1}
EXPECTED: both = {'code': 7} (the child's declared final `output`), and the child's private context key 'secret_api_key' must NOT appear.
OBSERVED: child private context LEAKED on: async, sync
RESULT: FAIL (child output discarded)
```

The declared `output` `{"code": 7}` appears nowhere. The parent transitions to
`m.done` normally, so nothing signals that the payload is wrong.

## Expected behaviour

XState v5: "When an invoked actor is done, the `onDone` transition is taken and
the `event.output` contains the actor's output" — the output of a done state
machine actor is the `output` of its final state, not its context
(https://stately.ai/docs/invoke, https://stately.ai/docs/final-states). Context
is explicitly the actor's *private* state; `output` exists precisely so an actor
can choose what to expose to its parent.

W3C SCXML agrees structurally: `<donedata>` on a `<final>` element determines the
data placed on the generated `done.invoke.<id>` event (§3.7.1, §5.7). The
invoked session's datamodel is not transmitted.

The library's own model already encodes this. `models.py:869-871`:

> 🏁 Final states may declare `output` (a.k.a. "done data"), which is surfaced
> on the `done.state.*` / `done.invoke.*` event.
> `self.output: Any = config.get("output")`

That documented contract names `done.invoke.*` explicitly and is not honoured.

Expected: `done.invoke.<id>.data` is the child's resolved `output` when the
reached final state (or the child machine) declares one. For a child that
declares no `output`, the current `context` fallback may be retained for
backward compatibility — but it should be documented as a deliberate,
non-XState extension.

## Root cause analysis

Both engines hard-code `child.context` as the done payload, ignoring `output`.

`src/xstate_statemachine/interpreter.py:2074-2082`:

```python
# ✅ Reached a top-level final state: `onDone` carries the child's
#    final context, as before.
done_event = DoneEvent(
    type=f"done.invoke.{invocation.id}",
    data=child.context,          # <-- line 2078
    src=invocation.id,
)
await self.send(done_event)
for plugin in self._plugins:
    plugin.on_service_done(self, invocation, done_event.data)
```

`src/xstate_statemachine/sync_interpreter.py:1176-1183`:

```python
done_event = DoneEvent(
    type=f"done.invoke.{invoke_id}",
    data=child.context,          # <-- line 1179
    src=invoke_id,
)
logger.info("🏁 Child actor '%s' completed; firing onDone.", child.id)
self.send(done_event)
```

The comment ("carries the child's final context, as before") shows this is a
deliberately preserved pre-`output` behaviour that was never revisited when
`output` support landed.

The machinery to do it correctly already exists and is *already running*:

- `models.py:871` — `StateNode.output` parses a final state's `output`.
- `models.py:1432` — `MachineNode.machine_output` parses machine-level
  `output`.
- `base_interpreter.py:3225-3245` — a resolver that takes the entered final
  state, handles both a literal and a callable of `{context, event}` (XState's
  dynamic-output form), and returns `None` when none is declared.
- `base_interpreter.py:3553` — `self.output = output` stores it on the child
  interpreter, so at the moment `_on_child_done` runs, `child.output` holds the
  resolved value; `base_interpreter.py:441` declares it and `:1002` / `:1230`
  persist and restore it.

So the resolved output is sitting on the child object, one attribute away, and
the done-event construction reaches past it for `context`. The
`on_service_done` plugin hook receives the same wrong payload, so observability
inherits the bug.

## Impact

**General users.** Any parent/child contract built on `output` — the idiomatic
XState way to return a result from a sub-machine — receives the wrong data. It
fails *silently and on the success path*: the child completed, the parent's
`onDone` fired, the parent transitioned. There is no error, no warning, no
parity mismatch (both engines are wrong identically). Downstream code either
`KeyError`s far from the cause, or — worse — finds a key of the same name in the
child's context and proceeds with a wrong value. It is also a confidentiality
leak: a child that holds an API token, a customer record, or scratch
intermediate state hands all of it to its parent, where it flows into the
parent's context, its plugin hooks (`on_service_done`), its logs and its
persisted snapshots. Users who reason from the XState docs, or from this
library's own `models.py` docstring, have no reason to suspect any of it.

**Concrete order-management scenario.** A parent trade-group machine invokes a
per-leg child that runs a risk check and a fill calculation, declaring
`output: {"approved": ..., "fill_price": ..., "qty": ...}`. Its context also
holds the venue credentials it used and the raw quote book it worked from. On
completion the parent's `onDone` receives the credentials and the quote book
instead of the decision. The guard `event.data["approved"]` raises, or —
if the child happened to keep an `approved` working flag in context — the
parent reads a stale mid-computation value and routes the leg on a risk
decision that was never final. Meanwhile venue credentials are copied into the
parent's context and from there into every snapshot that machine persists.

## Proposed fix

**Design.** Use the child's resolved `output` when one is declared, falling back
to `context` only for children that declare none.

In `src/xstate_statemachine/interpreter.py` (≈ line 2074) and
`src/xstate_statemachine/sync_interpreter.py` (≈ line 1176), replace
`data=child.context` with a shared helper — best placed on `BaseInterpreter`
next to the existing output resolver (`base_interpreter.py:3225`) so both
engines cannot drift again:

```python
def _child_done_data(self, child: "BaseInterpreter[Any]") -> Any:
    """The payload for `done.invoke.<id>`: the child's `output` when it
    declares one, else its context (legacy fallback, see #<this issue>)."""
    if child.output is not None:
        return child.output
    if child.machine.machine_output is not None or _declares_output(child):
        return child.output          # declared but resolved to None
    return child.context             # legacy
```

`child.output` is already populated by `_on_machine_done`
(`base_interpreter.py:3553`) before `_on_child_done` runs, so no new resolution
is needed. Pass the same value to the `on_service_done` plugin hook (it already
reads `done_event.data`, so it follows automatically).

Prefer distinguishing "declared `output` that resolved to `None`" from "no
`output` declared" — the former should deliver `None`, not fall through to
context, or a dynamic `output` returning `None` silently leaks context again.
`StateNode.output` / `MachineNode.machine_output` being non-`None` is the
signal; if that is awkward to thread through, record a boolean
`_declared_output` on the child at `base_interpreter.py:3553`.

**Compatibility.** Behaviour changes only for children that declare `output` —
which today receive a value the docs say they should not, so no correct program
depends on it. Children without `output` are unaffected. Worth a CHANGELOG
entry under breaking/behavioural changes. If a stricter break is acceptable,
dropping the `context` fallback entirely would match XState exactly (an actor
with no `output` yields `undefined`); that is the cleaner end state and could
be staged behind a deprecation warning on the fallback path.

**Alternatives considered.**
1. *Merge `output` into `context` on the done event.* Rejected: still leaks the
   child's private context, and makes the payload shape depend on key
   collisions.
2. *Add a separate `event.output` alongside `event.data`.* Non-breaking, but
   leaves `data` — the documented and universally-used field — wrong, and
   diverges from XState where `event.output` is the only channel.
3. *Documentation only (state that `data` is the child's context).* Rejected:
   it contradicts XState, SCXML `<donedata>`, and the library's own
   `models.py:869-871` docstring, and does nothing about the confidentiality
   leak.

## Acceptance criteria

- [ ] `done.invoke.<id>.data` is the child's resolved `output` whenever the
      child declares one, on **both** engines.
- [ ] `repro/R4-19_invoke_done_carries_child_context_not_output.py` exits `0`.
- [ ] `tests/test_invoke_output.py::test_done_invoke_carries_child_output_async`
- [ ] `tests/test_invoke_output.py::test_done_invoke_carries_child_output_sync`
- [ ] `tests/test_invoke_output.py::test_done_invoke_does_not_leak_child_context`
      — a child context key absent from `output` never appears in the parent's
      `done.invoke` payload.
- [ ] `tests/test_invoke_output.py::test_callable_output_resolved_with_context_and_event`
      — the dynamic `output` form (`base_interpreter.py:3235`) is honoured.
- [ ] `tests/test_invoke_output.py::test_machine_level_output_honoured`
      — `MachineNode.machine_output` (`models.py:1432`) is used when the final
      state declares none.
- [ ] `tests/test_invoke_output.py::test_child_without_output_keeps_context_fallback`
      — documented legacy behaviour is explicitly pinned.
- [ ] `tests/test_invoke_output.py::test_on_service_done_hook_receives_output`
- [ ] `tests/test_invoke_output.py::test_sync_and_async_done_payloads_identical`
- [ ] Docs and CHANGELOG state what `done.invoke.*.data` contains and that the
      context fallback applies only to children declaring no `output`.

## Related

- Register row `R4-19` (filed High, **CONFIRMED** at filed severity). Source id
  `D-semantics-1`; unmerged 1:1.
- Evidence: `battle-5e07ba8/semantics/repro/d3_child_output.py`,
  `battle-5e07ba8/semantics.md` / `.triage.md`; final-verification runs
  `probes/main-5e07ba8-final/v3_child_output.py`, `fv1_blockers_highs.py` and
  `fv5_mediums.py` (child `output={"code": 7}` → parent `done.invoke` data is
  the child's context on both engines, parent still reaches `m.done`).
- Meta: our adoption audit **#26**.

## Verification

- Date: 2026-09-18
- Python: 3.13.7 (`.venv-main`)
- Commit: `5e07ba8`
- `repro/R4-19_invoke_done_carries_child_context_not_output.py` re-run in a
  fresh process: exit code `1`, output matches the Observed section verbatim
  (both engines deliver `{'secret_api_key': 'sk-PRIVATE', 'ctxkey': 1}` on
  `done.invoke.kid` instead of the declared `output` `{'code': 7}`; the
  private-context leak is flagged on both `async` and `sync`).
- Root cause confirmed by direct inspection: `src/xstate_statemachine/
  interpreter.py` builds `DoneEvent(type=f"done.invoke.{invocation.id}",
  data=child.context, ...)` at line 2078 inside the block starting ≈ line
  2076, and `src/xstate_statemachine/sync_interpreter.py` does the same at
  line 1179 inside the block at ≈ line 1177 — both match the citations
  exactly, including the comment "carries the child's final context, as
  before" that the issue quotes.
- XState v5 claim checked via `https://stately.ai/docs/invoke` and
  `https://stately.ai/docs/final-states` (fetched): confirmed verbatim —
  "Event object `output` property is provided with actor's output data" for
  `invoke.onDone`, and "Final states can have `output` data, which is sent to
  the parent machine when the machine terminates" — i.e. the resolved
  `output`, not the actor's private context/datamodel. (XState's own event
  type is `xstate.done.actor.<id>`; this library's `done.invoke.<id>` naming
  is its own established convention and not itself in question — only the
  payload contents are.) The claim that context is delivered instead of
  output is correct and contradicts the documented contract.
- No self-containedness issues; no project name/label leak found.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --search "done.invoke output"` surfaces issue **#80** (a related but
  distinct improvement: delivering service failures as a dedicated
  `ErrorEvent` rather than a `DoneEvent` carrying an exception) and **#43**
  (perf, unrelated) — no issue covers the child-`output`-vs-`context` payload
  defect. No duplicate found.
