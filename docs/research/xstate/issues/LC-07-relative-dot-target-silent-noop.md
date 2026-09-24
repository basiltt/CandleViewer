---
lc: LC-07
title: "Bug: Relative `.child` targets resolve to nothing and are silently dropped"
labels: [bug, severity/high, area/interpreter, candleviewer]
severity: High
blocks_adoption: true
repro_script: repro/LC-07_relative-dot-target-silent-noop.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

XState v5 defines a leading-dot transition target (`target: ".A2"`) as relative to the **transition's source state** — that is, `.A2` on source `A` means the child `A.A2`. This library's resolver instead bases the lookup on the source's **parent**, so `.A2` on `m.A` searches for the sibling `m.A2`. When no such sibling exists the resolution fails, and the resulting `StateNotFoundError` is then swallowed by the async `Interpreter` run loop. The net effect is a completely silent no-op: no exit/entry actions run, the state is unchanged, `is_running` stays `True`, and nothing is raised to the caller.

This is the same silent-failure class as LC-08 and LC-36: a configuration mistake (or a correct XState config copied from the Stately docs) degrades to "nothing happened" rather than an error.

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local editable install (`pip install -e .`)
- Python: 3.13.7 (CPython, MSC v.1944 64-bit)
- OS: Windows 11
- Interpreter under test: `xstate_statemachine.interpreter.Interpreter` (async)

## Minimal reproduction

```python
"""LC-07 repro: relative `.child` targets resolve to nothing, silently.

XState v5 defines a leading-dot target (`target: ".A2"`) as relative to the
*transition's source state* — i.e. a CHILD of the source. This library's
resolver bases the lookup on the source's PARENT instead (resolver.py:199-207),
so `.A2` on source `m.A` looks for `m.A2`, which does not exist. The resulting
StateNotFoundError is then swallowed by the async Interpreter's run loop
(interpreter.py:479-487): no exit/entry actions, no state change, no error
reaches the caller and the machine keeps running.
"""

import asyncio
import sys

from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.interpreter import Interpreter

CONFIG = {
    "id": "m",
    "initial": "A",
    "states": {
        "A": {
            "initial": "A1",
            "on": {"GO": {"target": ".A2"}},
            "states": {"A1": {"exit": ["xA1"]}, "A2": {"entry": ["eA2"]}},
        }
    },
}


async def main() -> int:
    log = []
    logic = MachineLogic(
        actions={n: (lambda c, e, a, n=n: log.append(n)) for n in ("xA1", "eA2")}
    )
    machine = create_machine(CONFIG, logic=logic)
    interp = await Interpreter(machine).start()

    raised = None
    try:
        await interp.send("GO")
        await asyncio.sleep(0.05)
    except Exception as exc:  # noqa: BLE001
        raised = f"{type(exc).__name__}: {exc}"

    state = sorted(interp.current_state_ids)
    await interp.stop()

    print(f"OBSERVED: state={state} actions={log} raised={raised}")
    print("EXPECTED: state=['m.A.A2'] actions=['xA1', 'eA2'] raised=None")
    print("EXPECTED (acceptable alternative): create_machine() rejects '.A2'")
    print(
        "NOTE: the dot is resolved parent-relative, so '.A2' from source 'm.A' "
        "looks for 'm.A2' (a sibling), not the child 'm.A.A2'."
    )

    ok = state == ["m.A.A2"] and log == ["xA1", "eA2"]
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

Verbatim output (exit code 1):

```
OBSERVED: state=['m.A.A1'] actions=[] raised=None
EXPECTED: state=['m.A.A2'] actions=['xA1', 'eA2'] raised=None
EXPECTED (acceptable alternative): create_machine() rejects '.A2'
NOTE: the dot is resolved parent-relative, so '.A2' from source 'm.A' looks for 'm.A2' (a sibling), not the child 'm.A.A2'.
RESULT: FAIL
```

Corroborating observations from the same investigation (each reproduced with the script above, varying only the target string):

- A `.zzz` target that matches nothing anywhere leaves `state=["m.A.A1"]`, `running=True`, `raised=None` — the same silent no-op.
- The *same* config on `SyncInterpreter` **does** raise, showing the two engines disagree:
  ```
  dot RAISED StateNotFoundError Could not resolve target state '.A2' from state 'm'.
  ```
- A parent-relative dot target *does* work, confirming the semantic is sibling-relative rather than child-relative:
  ```
  # states A and B are siblings; source A, target ".B"
  sibling .B -> ['m.B']
  ```
- Both `"A2"` (plain id) and `"#m.A.A2"` (absolute) resolve correctly; only the dot form fails.

## Expected behaviour

XState v5 — https://stately.ai/docs/transitions — documents a leading dot as resolving into the **source** state's own descendants. From the "Transitions to any state" section:

> **Parent to descendant states:** `{ target: '.child.grandchild' }` — target a nested state within the current state

and the transitions cheatsheet on the same page labels `target: '.child'`, declared on a state `c` whose `states` contain `child`, as a "Child target".

**Verified empirically against XState 5.33.0** (Node 20.14.0) with the exact analogue of the repro config:

```js
const m = createMachine({ id:'m', initial:'A', states:{ A:{ initial:'A1',
  on:{ GO:{ target:'.A2' } },
  states:{ A1:{ exit:()=>console.log('xA1') }, A2:{ entry:()=>console.log('eA2') } } } } });
const a = createActor(m).start(); a.send({ type:'GO' });
console.log(a.getSnapshot().value);
```

```
xA1
eA2
{"A":"A2"}
```

So for `on: { GO: { target: '.A2' } }` declared on state `A`, XState enters `A.A2`, exiting `A.A1` and running `xA1` then `eA2` — exactly the order this library fails to produce.

(For completeness: SCXML has no leading-dot syntax at all. A `<transition target="…">` there names a state by its globally-unique `id`, so there is no relative form to compare against. The XState semantic above is the one that matters for this library, which models itself on XState.)

Two acceptable outcomes, in order of preference:

1. Implement the XState semantic: `.X` resolves against the **source** state's descendants.
2. If the library deliberately keeps the parent-relative meaning, then a dot target that does not resolve **must** raise at `create_machine()` time. A `None` resolution must never be silently swallowed.

## Root cause analysis

Two defects compose.

**1. Wrong base node for the relative lookup** — `src/xstate_statemachine/resolver.py:199-207`:

```python
# 🏛️ Strategy 3: Relative path resolution (e.g., '.sibling')
if target.startswith("."):
    segments = target[1:].split(".")
    _validate_segments(segments, target, reference_state.id)
    # ✅ Base the search from the parent of the current state.
    base = reference_state.parent or reference_state
    return _find_descendant(base, segments)
```

`base` is `reference_state.parent`. XState's rule bases the search on `reference_state` itself. The docstring at `resolver.py:131-132` states the intent explicitly ("*it's resolved relative to the parent of the `reference_state`*"), so this is a deliberate but non-conformant choice, and the inline comment at `:199` even calls it `'.sibling'`.

**2. The failure is then swallowed.** `BaseInterpreter._resolve_target_state_node` (`base_interpreter.py:1164-1261`) runs four resolution attempts, each catching `StateNotFoundError` and continuing, plus three fallbacks; when all fail it logs and **returns `None`** (`:1261`). `_execute_transition` correctly converts that to an exception (`base_interpreter.py:1763-1765`):

```python
target_state = self._resolve_target_state_node(transition)
if target_state is None:
    raise StateNotFoundError(transition.target_str, self.machine.id)
```

…but the async run loop catches every `Exception` from the macrostep and only logs it (`interpreter.py:479-487`):

```python
except Exception as exc:
    logger.error(
        "💥 Error processing event '%s' on '%s'; the "
        "interpreter remains running. %s", event.type, self.id, exc, exc_info=True,
    )
```

Because `send()` is fire-and-forget, the caller never learns. `SyncInterpreter` propagates the same error to the caller, so the two engines have materially different error contracts for identical configs.

Note also that the four standard attempts at `:1184-1189` try `(target_str, source)` **and** `(target_str, parent)`. For a dot target, `resolve_target_state` re-derives `.parent` from whichever reference it is handed, so the "source" attempt already behaves as parent-relative and the "parent" attempt reaches the grandparent — neither ever looks at the source's children.

## Impact

**General users.** Any config authored against the Stately docs — where `.child` is the idiomatic way to re-enter a sub-state — silently does nothing. The machine appears healthy: `is_running` is `True`, no exception, no failing test unless the test asserts on the resulting state. Because the parent-relative form *does* work for siblings, developers get inconsistent reinforcement: the same syntax works in one place and no-ops in another. Combined with the last-segment tree walk (LC-06), a `.child` target can also resolve to an unrelated branch that happens to share a leaf name.

**CandleViewer trading OMS.** Our order machine models an order as a compound state `order` with children `submitting`, `partially_filled`, `filled`, `cancelled`. Re-entering the fill-accounting sub-state on each partial fill is naturally written `on: { PARTIAL_FILL: { target: ".partially_filled" } }`. Under this bug that transition is a no-op: the machine stays in `submitting` while the exchange continues filling. The position exists on the exchange, the fill quantity is never accumulated into context, and the machine believes the order is still pending — so the reconciliation loop sees a position with no corresponding machine-side fill record and the risk gate computes exposure from stale quantities. Because nothing raises, our `on_transition` telemetry records no anomaly and the divergence is only discovered at end-of-day reconciliation. This is precisely the failure mode our house rule A5 (absolute targets only, plus a build-time validator) exists to work around — a workaround we would not need if the resolution failed loudly.

## Proposed fix

**Part 1 — conform to XState (`resolver.py:199-207`).** Base the relative lookup on the source state itself:

```python
if target.startswith("."):
    segments = target[1:].split(".")
    _validate_segments(segments, target, reference_state.id)
    try:
        return _find_descendant(reference_state, segments)
    except StateNotFoundError:
        # Backwards compatibility: 0.x resolved `.x` parent-relative.
        base = reference_state.parent
        if base is None:
            raise
        node = _find_descendant(base, segments)   # may raise
        warnings.warn(
            f"Relative target {target!r} on {reference_state.id!r} resolved "
            f"parent-relative to {node.id!r}. XState resolves a leading dot "
            f"against the source's children; this fallback is deprecated and "
            f"will be removed in 1.0. Use an absolute '#id.path' target.",
            DeprecationWarning, stacklevel=2,
        )
        return node
```

Child-first with a deprecating parent-relative fallback keeps every currently-working config working, emits a warning for the ambiguous ones, and fixes the broken ones. The docstring at `:126-136` must be updated to match. In 1.0 the fallback is removed and `.x` is child-relative only.

**Part 2 — never swallow a `None` resolution.** This is shared with LC-08. Validate all transition targets at `create_machine()` (see LC-08's proposed `_validate_targets` pass), so an unresolvable dot target is a load-time error rather than a runtime one. For failures that still escape at runtime, the async loop at `interpreter.py:479-487` should additionally notify plugins via a new `on_transition_failed` / `on_unhandled_event` hook (LC-48) rather than only writing to the logger, so the failure is observable in production telemetry.

**Backwards compatibility.** Part 1 is source-compatible for sibling targets (warning only). Configs that today silently no-op will start transitioning — that is the fix, but it should be called out prominently in the changelog as a behavioural change, since a machine could be inadvertently depending on the no-op. Part 2 turns previously-silent configs into load-time errors; gate it behind `create_machine(..., strict_targets=True)` for one minor release, defaulting to `True` in 1.0.

## Acceptance criteria

- [ ] `resolve_target_state(".A2", node_A)` returns the child `m.A.A2` when `A` has a child `A2`.
- [ ] `resolve_target_state(".B", node_A)` still returns sibling `m.B` when `A` has no child `B`, and emits a `DeprecationWarning`.
- [ ] A dot target that resolves to neither a child nor a sibling raises `StateNotFoundError` (and, once LC-08 lands, is rejected at `create_machine()`).
- [ ] `Interpreter` and `SyncInterpreter` agree: the same unresolvable-target config produces the same error contract on both.
- [ ] `repro/LC-07_relative-dot-target-silent-noop.py` exits 0.
- [ ] Tests added under `tests/`:
  - `tests/test_resolver.py::test_relative_dot_target_resolves_to_child`
  - `tests/test_resolver.py::test_relative_dot_target_sibling_fallback_warns`
  - `tests/test_resolver.py::test_relative_dot_target_unresolvable_raises`
  - `tests/test_interpreter.py::test_relative_child_target_runs_exit_and_entry_actions`
  - `tests/test_interpreter.py::test_async_and_sync_agree_on_unresolvable_target`

## Related

- **LC-08** — unknown targets unvalidated (shares Part 2 of the fix; these two should land together).
- **LC-06** — over-forgiving target resolution; the last-segment tree walk at `base_interpreter.py:1238-1250` is the other half of the resolution-correctness story.
- **LC-36** — built-in action params silently ignored when misspelled; same silent-no-op class.
- **LC-48** — no error-observability hooks; the reason this failure is invisible even to plugins.

## Verification

Independently re-verified on **2026-09-15**.

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, editable install
- Python: 3.13.7 (CPython, MSC v.1944 64-bit), Windows 11
- `repro/LC-07_relative-dot-target-silent-noop.py` run in a fresh process → **exit code 1**, output matches the Observed section verbatim.
- Corroborating checks re-run: sibling `.B` → `['m.B']`; plain `A2` → `['m.A.A2']`; absolute `#m.A.A2` → `['m.A.A2']`; `.zzz` → `['m.A.A1']`, `running=True`; `SyncInterpreter` on the dot config raises `StateNotFoundError`.
- Root-cause citations confirmed against source: `resolver.py:199-207` (`base = reference_state.parent or reference_state`), docstring `resolver.py:131-132`, `base_interpreter.py:1184-1189` / `:1261` / `:1763-1765`, `interpreter.py:479-487`.
- Expected behaviour confirmed empirically against **XState 5.33.0** (Node 20.14.0): `target: '.A2'` on state `A` logs `xA1`, `eA2` and yields value `{"A":"A2"}`.
