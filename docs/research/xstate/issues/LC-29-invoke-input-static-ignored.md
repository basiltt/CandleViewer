---
lc: LC-29
title: "Feature: `invoke.input` is static and is ignored entirely for child-machine actors"
labels: [enhancement, severity/medium, area/actors, candleviewer]
severity: Medium
blocks_adoption: false
repro_script: repro/LC-29_invoke-input-static-ignored.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
verified_date: 2026-09-15
---

## Summary

`invoke.input` has two independent gaps. First, it is parsed as a static value — `self.input = config.get("input")` (`models.py:469`) — so XState v5's callable form `input: ({ context, event }) => …` is stored verbatim as the function object and never resolved; a machine written that way silently hands a function where a dict was meant. Second, and worse, for an invoked **child machine** the value is discarded outright: `_spawn_and_manage_actor` constructs `Interpreter(actor_machine)` with no `input` argument (`interpreter.py:1188`), so the child starts on its declared default context regardless of what the parent specified. The parameterisation machinery already exists — `BaseInterpreter._build_initial_context` resolves `input` against a context factory (`base_interpreter.py:342-369`) — the invoke path simply never calls it. The failure is silent: no warning, no error, just a child that quietly ran with the wrong data.

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, installed with `pip install -e .`
- Python: 3.13.7 (also confirmed on 3.12.3)
- OS: Windows 11 (x64)

## Minimal reproduction

```python
"""LC-29 repro: `invoke.input` is static, and it is ignored entirely when the
invoked `src` resolves to a child machine.

Two defects:
  1. A callable `input: ({context, event}) => ...` (XState v5) is stored
     verbatim as the function object — never called.
  2. Even a static dict `input` never reaches a spawned child machine's
     context; `_spawn_and_manage_actor` constructs `Interpreter(actor_machine)`
     with no `input` argument.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

CHILD = {
    "id": "leg",
    "initial": "work",
    "context": {"snapshot": None},
    "states": {"work": {"on": {"GO": "done"}}, "done": {"type": "final"}},
}

PARENT = {
    "id": "book",
    "context": {"profile": {"venue": "X", "size": 7}},
    "initial": "running",
    "states": {
        "running": {
            "invoke": {
                "id": "leg1",
                "src": "leg",
                "input": {"snapshot": {"venue": "X", "size": 7}},
            }
        }
    },
}


async def main() -> int:
    ok = True

    # 1) Callable input is never invoked — stored as-is on the definition.
    cfg = {
        **PARENT,
        "states": {
            "running": {
                "invoke": {
                    "id": "leg1",
                    "src": "leg",
                    "input": lambda ctx, evt: {"snapshot": ctx["profile"]},
                }
            }
        },
    }
    m = create_machine(cfg, logic=MachineLogic(services={"leg": create_machine(CHILD)}))
    inv = m.states["running"].invoke[0]
    print(f"OBSERVED type(invoke.input) with a callable = {type(inv.input).__name__}")
    print("EXPECTED it to be resolved per-spawn against {context, event} (a dict)")
    if callable(inv.input):
        ok = False

    # 2) Static input never reaches the spawned child's context.
    parent_m = create_machine(
        PARENT, logic=MachineLogic(services={"leg": create_machine(CHILD)})
    )
    interp = await Interpreter(parent_m).start()
    await asyncio.sleep(0.05)
    child = next(iter(interp._actors.values()))
    print(f"OBSERVED spawned child context = {child.context}")
    print(f"OBSERVED spawned child .input  = {child.input!r}")
    print("EXPECTED context = {'snapshot': {'venue': 'X', 'size': 7}} "
          "(invoke.input seeds the child)")
    if child.context.get("snapshot") != {"venue": "X", "size": 7}:
        ok = False
    await interp.stop()

    print("RESULT:", "REPRODUCED (invoke.input static + ignored)" if not ok else "NOT REPRODUCED")
    return 1 if not ok else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED type(invoke.input) with a callable = function
EXPECTED it to be resolved per-spawn against {context, event} (a dict)
OBSERVED spawned child context = {'snapshot': None}
OBSERVED spawned child .input  = None
EXPECTED context = {'snapshot': {'venue': 'X', 'size': 7}} (invoke.input seeds the child)
RESULT: REPRODUCED (invoke.input static + ignored)
```

(exit code 1)

Note the child's `.input` is `None`, not the supplied dict — confirming the value never reaches the child interpreter at all, rather than reaching it and failing to merge.

## Expected behaviour

From <https://stately.ai/docs/invoke> (the `invoke` property API lists `input` as "The input to pass to the actor"):

> "The `input` property can be a static input value, or a function that returns the input value. The function will be passed an object that contains the current `context` and `event`."

with the two forms given as:

```ts
// static
invoke: { src: 'liveFeedback', input: { domain: 'stately.ai' } }

// function of {context, event}
invoke: {
  src: 'fetchUser',
  input: ({ context }) => ({ userId: context.userId }),
}
```

The same page notes that "behind the scenes, input is conveyed to the actor by an event: `{ type: 'xstate.init', input: ... }`", and <https://stately.ai/docs/input> shows the receiving side — a machine consumes it through a context factory:

```ts
createMachine({
  context: ({ input }) => ({ userId: input.userId, rating: input.defaultRating }),
});
```

The v4→v5 migration guide reinforces the callable form under "Don't use property mappers in `input` or `output`", whose ✅ example is exactly `input: ({ context, event }) => ({ value: event.value })`.

So the expected semantics are: `input` may be a plain value **or** a callable resolved *per spawn* against `{context, event}` (the parent's context and the event that triggered the invoke); the resolved value is passed to the child actor at creation; the child's `context` factory receives it as `{ input }`; and for a child with a plain-dict `context`, the input is available to it rather than dropped.

## Root cause analysis

- `src/xstate_statemachine/models.py:469` — `self.input: Optional[Dict[str, Any]] = config.get("input")`. Stored raw, typed as a dict, never resolved. The docstring at `:439` states the limitation explicitly: *"input: Static data to pass to the invoked service."* Nothing calls the value if it is a callable, and nothing rejects it either.
- `src/xstate_statemachine/interpreter.py:1173-1252` — `_spawn_and_manage_actor` never reads `invocation.input`. At `:1190` it does `child_interpreter = Interpreter(actor_machine)`; the `input` keyword that `Interpreter.__init__` accepts (`interpreter.py:109-113`, forwarded to the base at `:122`) is simply not passed.
- `src/xstate_statemachine/base_interpreter.py:343-369` — `_build_initial_context(machine, input)` already implements the whole XState contract: it calls a callable `machine.initial_context` as `raw({"input": input})`, and for a plain-dict context does `context.setdefault("input", input)`. **This is the exact code that should run for invoked children, and the only reason it does not is the missing argument at `interpreter.py:1190`.**
- Contrast the *callable-service* path, which does surface the value: `_invoke_service_task` (`interpreter.py:1069-1072`) builds `Event(type=f"invoke.{id}", payload={"input": invocation.input or {}})`. So `input` works (statically) for function services and not at all for machine services — the two `src` kinds disagree.
- Contrast also the **`spawn` action** path, which genuinely does seed the child: `_spawn_actor` (`interpreter.py:965-971`) constructs the child and then does `child_interpreter.context.setdefault("input", child_input)` from `spawn_params.get("input")`; `sync_interpreter.py:1142-1148` mirrors it. So within one library, `spawn(..., input=…)` works and `invoke(..., input=…)` does not.
- `src/xstate_statemachine/actions.py:292-320` — the `spawn_child` action helper accepts `input` and threads it into the spawn config, confirming the intent is present in the API surface.
- `src/xstate_statemachine/sync_interpreter.py:1329-1370` — the sync engine's `_invoke_service` routes a `MachineNode` `src` into `_spawn_actor` with `params={"id": invocation.id}` only (`:1360-1365`) — `invocation.input` is dropped on the floor there too, even though the `_spawn_actor` it delegates to would have honoured an `"input"` key.

## Impact

**General users.** The headline use of `invoke` — "run this child machine *for this item*" — cannot be expressed declaratively. Every child that needs per-instance data must instead be spawned imperatively from an action that constructs the interpreter by hand and seeds its context, which forfeits `onDone`/`onError` wiring, `TaskManager` cancel-on-state-exit and the actor registry. Worse, the failure mode is silent: a config that *looks* correct (and would be correct in XState) produces a child running on default context, so bugs surface far downstream as "the child did the right thing to the wrong data". The callable form fails silently in a second way — a function object sitting where a dict is expected typically shows up as a `TypeError` in unrelated code, or not at all.

**CandleViewer (trading OMS).** This is the application that prompted the report. Each order leg's child machine must be seeded with a **frozen `profile_snapshot`** — the venue, size, limit price and risk parameters as they stood at spawn time — precisely so that later mutations of the parent's live profile cannot retroactively change how an in-flight leg behaves. With `invoke.input` ignored, a leg child starts on the machine's default context: either it carries no snapshot at all, or (the tempting workaround) it reads the parent's *current* profile through a shared reference, which reintroduces exactly the mutation hazard the snapshot exists to prevent. Concretely, a parent re-pricing its profile mid-flight would silently alter the limit price that an already-submitted leg uses to evaluate its fills. Our forced mitigation is to abandon `invoke` for legs and spawn every leg interpreter manually, seeding context ourselves — which means the leg lifecycle (cancel on parent state exit, `onDone` roll-up of fills) is hand-managed application code rather than statechart semantics.

## Proposed API

Support both the static and callable forms, and actually apply them to child machines.

```python
# Callable input, resolved per spawn against the parent's context and the
# triggering event — the XState v5 shape.
{
    "id": "leg1",
    "src": "leg",
    "input": lambda ctx, evt: {"profile_snapshot": dict(ctx["profile"])},
}

# Equivalently, a single-mapping signature mirroring XState exactly:
{"src": "leg", "input": lambda args: {"snapshot": args["context"]["profile"]}}

# Static form keeps working unchanged:
{"src": "leg", "input": {"snapshot": {"venue": "X", "size": 7}}}
```

The child then receives it the documented way:

```python
CHILD = {
    "id": "leg",
    # context factory sees {"input": <resolved value>}
    "context": lambda args: {"snapshot": args["input"]["profile_snapshot"], "filled": 0},
    "initial": "work",
    "states": {"work": {"on": {"GO": "done"}}, "done": {"type": "final"}},
}

parent = create_machine(PARENT, logic=MachineLogic(services={"leg": create_machine(CHILD)}))
interp = await Interpreter(parent).start()
# the spawned child's context["snapshot"] == the parent's profile at spawn time,
# and is a deep copy: later parent mutation cannot reach it.
```

### Implementation sketch

1. `models.py:469` — keep the raw value, widen the type to `Optional[Union[Dict[str, Any], Callable[..., Any]]]`, and update the docstring (`:439`) to drop "Static".
2. Add `InvokeDefinition.resolve_input(context, event)` on the same class: returns the value unchanged if not callable; otherwise calls it, accepting both `(context, event)` and the single-mapping `({"context": …, "event": …})` arity via `inspect.signature` (the codebase already does arity-sniffing for actions/guards — reuse that helper). Deep-copy the result so the child cannot alias parent state.
3. `interpreter.py:1190` — `child_interpreter = Interpreter(actor_machine, input=invocation.resolve_input(self.context, triggering_event))`. `_spawn_and_manage_actor` needs the triggering event threaded in from `_invoke_service`/the entry path; if that is awkward in the first pass, resolve against `self.context` and the interpreter's last processed event.
4. `interpreter.py:1069-1072` — route the callable-service path through the same `resolve_input`, so both `src` kinds agree.
5. Mirror 3–4 in `sync_interpreter.py`: `_invoke_service` (`:1360-1365`) should pass the resolved `input` in the `params` dict it hands to `_spawn_actor`, which already knows how to apply it (`:1145-1148`).
6. `actions.py:292-320` — `spawn_child(..., input=…)` resolves through the same helper.
7. If `resolve_input` raises, treat it exactly like a service that failed to start: emit `error.platform.<invoke id>` rather than letting the exception escape into the interpreter loop.

**Backwards compatibility.** Static `input` behaviour is unchanged. Passing a callable currently "works" only in the sense that it is silently stored, so no working code can depend on it — resolving it is safe. The one genuine behaviour change is that invoked child machines now receive `input` where they previously received none; a child whose plain-dict context happens to contain an `"input"` key would previously keep its own value and will still do so, since `_build_initial_context` uses `setdefault`. Worth a CHANGELOG entry under "fixed". No deprecation required.

## Acceptance criteria

- [ ] `InvokeDefinition.input` accepts a callable; `InvokeDefinition.resolve_input(context, event)` resolves both arities and returns a deep copy.
- [ ] Invoked child machines are constructed with the resolved `input`.
- [ ] `tests/test_invoke_input.py::test_static_input_seeds_child_machine_context` — the repro's `PARENT`/`CHILD` pair; child context contains the supplied snapshot.
- [ ] `tests/test_invoke_input.py::test_callable_input_resolved_against_parent_context_and_event` — `input=lambda ctx, evt: {...}` receives the parent's context and the triggering event, and the child sees the result.
- [ ] `tests/test_invoke_input.py::test_callable_input_single_mapping_arity` — the `lambda args: args["context"]` form works.
- [ ] `tests/test_invoke_input.py::test_input_is_deep_copied_not_aliased` — mutating the parent's context after spawn does not change the child's.
- [ ] `tests/test_invoke_input.py::test_child_context_factory_receives_input_key` — a child with `context: lambda args: {...args["input"]}` is parameterised correctly.
- [ ] `tests/test_invoke_input.py::test_callable_service_input_matches_machine_service_input` — both `src` kinds resolve `input` identically.
- [ ] `tests/test_invoke_input.py::test_input_resolver_exception_becomes_on_error` — a raising `input` callable produces `error.platform.<id>`, not an interpreter crash.
- [ ] `tests/test_invoke_input_sync.py` — the static and callable cases for `SyncInterpreter`.
- [ ] Docs: the `invoke` reference documents the callable form and the `{ input }` context-factory contract; `models.py:439` docstring no longer says "Static".
- [ ] `repro/LC-29_invoke-input-static-ignored.py` exits 0.

## Related

- LC-12 (`spawn` blocking on the async engine) — the same child-actor spawn path; fixing both together is natural.
- LC-22 (context assigned wholesale, defaults not merged) — related context-construction semantics in `_build_initial_context`.
- LC-28 (`_spawn_and_manage_actor` polls for child completion) — same function.

## Verification

Independently verified on 2026-09-15.

- **Date:** 2026-09-15
- **Python:** 3.13.7 (venv `.venv-cv`, `xstate-statemachine` 0.7.0 installed with `pip install -e .`)
- **Library commit:** `42612cf41d9750a5982fe75d5bb539d82f1df4a9` (`main`)
- **Repro exit code:** 1 (fails against the library today, as claimed)

Checks performed: (1) the repro script was run in a fresh process and its output matches the Observed section; (2) the embedded code block is byte-identical to the repro file; (3) the Expected section was checked against XState v5 — the doc pages plus the v5 source in `packages/core/src` (`system.ts`, `createActor.ts`, `SimulatedClock.ts`, `eventUtils.ts`); (4) every `file:line` in the Root cause section was opened in the library source and confirmed to say what is claimed; (5) no duplicate exists in the upstream issue tracker (only issue #17, an unrelated closed camelCase/snake_case auto-discovery bug).
