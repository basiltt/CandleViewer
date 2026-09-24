---
lc: LC-49
title: "Feature: no hierarchical `state.value` — active states are only a flat `Set[str]` of ids"
labels: [enhancement, severity/medium, area/interpreter, candleviewer]
severity: Medium
blocks_adoption: false
repro_script: repro/LC-49_no-hierarchical-state-value.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

The only way to read a machine's configuration is `interpreter.current_state_ids` (alias `active_state_ids`), a flat `Set[str]` of fully-qualified **leaf** ids such as `{'order.life.booking', 'order.protection.risk.armed'}`. XState's canonical representation — `state.value` — is a nested structure, `{"life": "booking", "protection": {"risk": "armed"}}`, and that nested form is what `@xstate/react`, the Stately inspector/visualiser and every XState-shaped consumer consume.

The nested value is a **pure function of data the library already holds** (the active-node set plus the machine tree), so this is purely a missing accessor, not a missing capability. Today every consumer has to reimplement it by string-splitting ids outside the library — duplicated, untested, and wrong in the corner cases (a state id containing a dot, a parallel region whose child is itself parallel, a final leaf).

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, installed with `pip install -e .`
- Python: 3.13.7 (CPython)
- OS: Windows 11 (x64)
- Install method: `pip install -e .` into a dedicated venv

## Current workaround and why it is insufficient

The repro below first demonstrates the gap, then shows the workaround every consumer is forced into.

```python
"""LC-49 repro: no hierarchical `state.value` -- only a flat `Set[str]` of ids.

XState exposes `state.value` as a nested structure, e.g.

    {"life": "booking", "protection": {"risk": "armed"}}

which is what `@xstate/react`, the Stately inspector and every XState-shaped
consumer expect. This library exposes only `current_state_ids` (alias
`active_state_ids`), a flat set of fully-qualified *leaf* ids, so the parent /
region structure has to be reconstructed by string-splitting outside the
library.

Exits 1 when no hierarchical `value` is available.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from xstate_statemachine import Interpreter, create_machine

logging.disable(logging.CRITICAL)

CFG = {
    "id": "order",
    "type": "parallel",
    "context": {},
    "states": {
        "life": {
            "initial": "booking",
            "states": {"booking": {}, "filled": {}},
        },
        "protection": {
            "initial": "risk",
            "states": {
                "risk": {
                    "initial": "armed",
                    "states": {"armed": {}, "tripped": {}},
                }
            },
        },
    },
}

EXPECTED_VALUE = {"life": "booking", "protection": {"risk": "armed"}}


async def main() -> int:
    interp = Interpreter(create_machine(CFG))
    await interp.start()

    ids = sorted(interp.current_state_ids)
    value = getattr(interp, "value", None)
    snap = interp.get_snapshot() if hasattr(interp, "get_snapshot") else None
    snap_keys = sorted(snap.keys()) if isinstance(snap, dict) else type(snap).__name__
    await interp.stop()

    print("OBSERVED  current_state_ids:", ids)
    print("OBSERVED  interpreter.value:", value)
    print("OBSERVED  snapshot keys:", snap_keys)
    print("EXPECTED  interpreter.value ==", EXPECTED_VALUE)

    ok = value == EXPECTED_VALUE
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

The workaround is a projector that re-derives the tree from the id strings:

```python
def value_from_ids(machine_id: str, ids: set[str]) -> dict | str:
    root: dict = {}
    for full in ids:
        parts = full.split(".")            # ← breaks on any id containing a dot
        assert parts[0] == machine_id
        node = root
        for p in parts[1:-1]:
            node = node.setdefault(p, {})
        # a leaf under a compound parent must collapse dict -> str, but only
        # if that parent has exactly one active child, which the id string
        # does not tell us -- we have to consult the machine tree anyway.
        ...
```

Why it is insufficient:

1. **It cannot be written correctly from the id strings alone.** Collapsing `{"risk": {"armed": {}}}` to `{"risk": "armed"}` requires knowing that `risk` is a *compound* (not parallel) node with exactly one active child. That fact lives in the machine tree, not in the id. Any projector must therefore walk `machine.states` — i.e. reimplement a piece of the library.
2. **Ids are not safely splittable.** The library permits state keys containing `.`; splitting on `.` silently mis-nests those machines.
3. **It is duplicated per consumer.** Our WS projection, our test assertions and any future `@xstate/react` overlay each need the same function, and there is no canonical implementation to point at, so they drift.
4. **It is not covered by the library's tests**, so a future change to id construction breaks every downstream projector silently.
5. **`get_snapshot()` does not help** — it returns a JSON *string* whose payload carries `state_ids` and `configuration` as flat sorted lists, the same flat representation in a different wrapper.

## Observed behaviour

```
OBSERVED  current_state_ids: ['order.life.booking', 'order.protection.risk.armed']
OBSERVED  interpreter.value: None
OBSERVED  snapshot keys: str
EXPECTED  interpreter.value == {'life': 'booking', 'protection': {'risk': 'armed'}}
RESULT: FAIL
```

`interpreter.value` does not exist (`getattr` returns `None`), and `get_snapshot()` is a `str`, not a mapping.

## Expected behaviour

XState v5 defines `snapshot.value` as the hierarchical representation:

- <https://stately.ai/docs/states> — the state object's `value` is *"the current state value, which is either: a string representing a simple state like `'playing'`, or: an object representing nested states like `{ paused: 'buffering' }`"*, and *"For state machines with [parallel state nodes], the state value contains object(s) with multiple keys for each state node region"*. An atomic state's value is the string key; a compound state's is `{ parent: child }`; a parallel state's is an object with one entry per region, recursively. (The same page notes that a machine with no state nodes other than the root has `state.value === null` — an edge case worth matching.)
- <https://stately.ai/docs/parallel-states> gives the canonical shape for exactly the machine in the repro: *"The state value of a parallel state is an object with the state values of each of its regions"*, illustrated as `{ track: 'paused', volume: 'normal' }`.
- <https://stately.ai/docs/inspection> — the Stately inspector consumes `@xstate.snapshot` events, whose payload is *"the most recent snapshot of the actor"* (and therefore carries its `value`); the `@xstate.microstep` event carries `value` explicitly. Without a hierarchical value, a live visualiser overlay cannot highlight the active nodes.

So for the repro machine XState produces `{"life": "booking", "protection": {"risk": "armed"}}`, and `state.matches(...)` is defined in terms of that structure: *"The `state.matches(stateValue)` method determines whether the current `state.value` matches the given `stateValue`."* Note XState's `matches` uses the **key path**, e.g. `state.matches({ form: 'invalid' })` or `state.matches('form')`, not a machine-id-prefixed dotted id.

## Root cause analysis

- `src/xstate_statemachine/base_interpreter.py:375-389` — `current_state_ids` is the sole configuration accessor:
  ```python
  @property
  def current_state_ids(self) -> Set[str]:
      return {
          s.id for s in self._active_state_nodes if s.is_atomic or s.is_final
      }
  ```
  It deliberately *filters down to leaves* (`is_atomic or is_final`), discarding exactly the ancestor information a nested value needs — even though `self._active_state_nodes` (the unfiltered set) contains every active ancestor.
- `src/xstate_statemachine/base_interpreter.py:392-407` — `active_state_ids` is a pure alias of the same flat property, added so the docs' spelling resolves; it does not add structure.
- `src/xstate_statemachine/base_interpreter.py:669-745` — `get_snapshot()` serialises `"state_ids": sorted(self.current_state_ids)` and `"configuration": sorted(node.id for node in self._active_state_nodes)`. The `configuration` key *does* carry the ancestors, which confirms the data is available — it is simply never assembled into a tree.
- `src/xstate_statemachine/models.py:547-548, 720, 1074-1083` — `StateNode` already carries `key`, `parent`, `states`, `type` (`"atomic"` / `"compound"` / `"parallel"` / `"final"`), `is_atomic` and `is_final`, which is everything a correct `value` builder needs. (Note there is no `is_parallel` property today — a builder must test `node.type == "parallel"`, the same spelling the interpreter itself uses at `base_interpreter.py:1973`, `:2178` and `:2636`. Adding `is_parallel` alongside the existing predicates would be a tidy companion change.) No new bookkeeping is required.

In short: the information is present in `_active_state_nodes` + the `StateNode` tree at every point where `current_state_ids` is computed; the library just never exposes the assembled form.

## Impact

**General users.** The library advertises XState-compatible semantics, but its state representation is not XState-shaped, so none of the XState ecosystem tooling can consume it without a hand-written adapter. That blocks the Stately visualiser, `@xstate/react`-style live overlays, and any cross-language contract where a TypeScript front end and a Python back end are meant to agree on "what state is this actor in". It also makes assertions in user tests verbose and brittle (`assert interp.current_state_ids == {"m.a.b.c"}` instead of `assert interp.value == {"a": {"b": "c"}}`).

**CandleViewer trading OMS.** Our WebSocket projection publishes order-machine state to the browser, where the UI is XState-shaped and expects `value`. Because the library emits a flat set, we carry a bespoke projector in the gateway that re-derives the tree from id strings, plus its own test suite — code that exists solely to compensate for a missing one-line property, and that we must keep in sync with the library's id-construction rules by hand. A parallel order machine (`life` × `protection` regions, which is our actual topology) is where this hurts most: the flat set `{'o.life.b','o.prot.p'}` gives the UI no way to tell which region a change belongs to without re-parsing, so a region-scoped UI update degrades into a full re-render.

## Proposed API

Add a read-only `value` property to `BaseInterpreter` (so both `Interpreter` and `SyncInterpreter` gain it), plus the `matches()` helper that is defined in terms of it.

```python
# src/xstate_statemachine/base_interpreter.py, next to current_state_ids

@property
def value(self) -> Union[str, Dict[str, Any]]:
    """The active configuration in XState's hierarchical form.

    - atomic state            -> its key, e.g. ``"booking"``
    - compound state          -> ``{"life": "booking"}``
    - parallel state          -> one key per region, recursively
    """
    return self._value_of(self.machine)

def _value_of(self, node: "StateNode") -> Union[str, Dict[str, Any]]:
    active = self._active_state_nodes
    if node.is_atomic or node.is_final:
        return node.key
    if node.type == "parallel":
        return {
            key: self._value_of(child)
            for key, child in node.states.items()
            if child in active
        }
    # compound: exactly one active child
    child = next(c for c in node.states.values() if c in active)
    return child.key if (child.is_atomic or child.is_final) else {child.key: self._value_of(child)}
```

Usage:

```python
interp = Interpreter(create_machine(CFG))
await interp.start()

interp.value
# {'life': 'booking', 'protection': {'risk': 'armed'}}

interp.matches("protection.risk.armed")   # True
interp.matches({"life": "booking"})       # True

await interp.send("FILL")
interp.value
# {'life': 'filled', 'protection': {'risk': 'armed'}}
```

Also surface it in persistence so downstream consumers get it for free:

```python
json.loads(interp.get_snapshot())["value"]
# {'life': 'booking', 'protection': {'risk': 'armed'}}
```

**Backwards compatibility.** Purely additive. `current_state_ids` and `active_state_ids` keep their current flat semantics and remain the canonical internal spelling — no deprecation. Adding a `"value"` key to the snapshot dict is additive too; `from_snapshot` must ignore unknown keys (it should already, but add a test), and `value` is *derived*, so restore continues to use `configuration`/`state_ids` as the source of truth and never trusts a persisted `value`.

**Edge cases to pin down in the implementation:**

- A compound node whose active child is `final` still collapses to the string key (matching XState, where a final child is a normal state value).
- A parallel node with a region that has been exited (shouldn't happen, but is constructible via a malformed restore) must raise a clear error rather than produce a half-tree.
- `value` on an `uninitialized` interpreter should raise or return `{}` consistently — recommend returning `{}` and documenting it, so a metrics scrape before `start()` cannot crash a process.
- State keys containing `.` must round-trip correctly, which they do under this implementation because it walks the tree rather than splitting ids.

## Acceptance criteria

- [ ] `BaseInterpreter.value` exists and is inherited by both `Interpreter` and `SyncInterpreter`.
- [ ] Atomic root machine → `value` is the leaf key string.
- [ ] Compound nesting → `{"parent": "child"}`, collapsing the innermost level to a string.
- [ ] Parallel root → one key per region, recursively, matching the repro's `{"life": "booking", "protection": {"risk": "armed"}}`.
- [ ] Nested parallel inside a compound region produces the correct nested object.
- [ ] A final leaf renders as its key, not as an empty dict.
- [ ] State keys containing `.` round-trip correctly (proves the implementation is tree-based, not string-split).
- [ ] `value` on an uninitialized interpreter returns `{}` and is documented.
- [ ] `json.loads(get_snapshot())` contains a `"value"` key; `from_snapshot` ignores it and rebuilds from `configuration`.
- [ ] `matches(...)` accepts both dotted-string and nested-dict forms and is defined against `value`.
- [ ] `repro/LC-49_no-hierarchical-state-value.py` exits 0.
- [ ] Tests added:
  - `tests/test_interpreter.py::test_value_atomic_root`
  - `tests/test_interpreter.py::test_value_compound_nesting`
  - `tests/test_interpreter.py::test_value_parallel_regions`
  - `tests/test_interpreter.py::test_value_nested_parallel_in_compound`
  - `tests/test_interpreter.py::test_value_final_leaf_is_key_string`
  - `tests/test_interpreter.py::test_value_with_dotted_state_key`
  - `tests/test_interpreter.py::test_value_uninitialized_is_empty`
  - `tests/test_sync_interpreter.py::test_sync_interpreter_value_matches_async`
  - `tests/test_persistence.py::test_snapshot_includes_hierarchical_value`
- [ ] `docs/_guide/hierarchical.md` and `docs/_guide/parallel.md` show `value` alongside `current_state_ids`; `docs/_guide/snapshots.md` documents the new key.

## Related

Companion findings from the same review (filed separately):

- Context is assigned wholesale on restore — same area: the snapshot/restore representation is lossy relative to XState's.
- Snapshots carry no schema version — adding a `value` key is a good forcing function for versioning the snapshot payload.
- `matches()` accepting XState's key-path form (rather than only fully-qualified ids) depends on this property existing.

## Verification

Independently verified on **2026-09-15**.

- Repro `repro/LC-49_no-hierarchical-state-value.py` run in a fresh process against the local clone at commit `42612cf`: **exit code 1**, output matches the Observed section verbatim (`interpreter.value` is `None`, `get_snapshot()` returns a `str`).
- Python 3.13.7 (CPython), Windows 11 x64, `pip install -e .` into `.venv-cv`.
- Root-cause citations checked against the source: `current_state_ids` at `base_interpreter.py:374-390` filters to `is_atomic or is_final` as quoted; `active_state_ids` at `:392-407` is a pure alias; `get_persisted_snapshot()` at `:690-745` emits `"state_ids"` and `"configuration"` as flat sorted lists.
- The dotted-key claim was **empirically confirmed**, not just asserted: a machine with the state key `a.b` yields the id `m.a.b.c`, which any `split(".")`-based projector mis-nests.
- The proposed implementation was **corrected**: `StateNode` has `is_atomic` and `is_final` (`models.py:1074-1083`) but **no** `is_parallel` property, so the snippet's `node.is_parallel` would have raised `AttributeError`. It now tests `node.type == "parallel"`, matching the interpreter's own spelling at `base_interpreter.py:1973`, `:2178`, `:2636`.
- XState citations re-checked against the live pages and tightened to published wording; added the `state.value === null` root-only edge case and the note that XState's `matches()` takes a key path, not a machine-id-prefixed id.
- Not a duplicate: the only issue on `basiltt/xstate-statemachine` is #17 (closed, unrelated).
