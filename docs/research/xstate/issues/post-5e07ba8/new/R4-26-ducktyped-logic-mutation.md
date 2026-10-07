---
r4: R4-26
title: "Bug: create_machine() still mutates a duck-typed logic object's registries in place"
labels: [bug, severity/medium, area/interpreter]
severity: Medium
repro_script: repro/R4-26_ducktyped_logic_mutation.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

Issue `#92` fixed `create_machine()` mutating a caller's `MachineLogic`
instance by giving the machine a shallow copy before aliasing runs. That
fix is conditional on `isinstance(final_logic, MachineLogic)`
(`factory.py:216-220`); a duck-typed logic object — any object exposing
`.actions`/`.guards`/`.services` dicts, which the library's own code
comments describe as supported "by contract" — takes the `else` branch and
is used as-is. `_alias_logic_names` then unconditionally calls
`setattr(logic, attr, owned)` (`factory.py:279`) on whatever `logic` it was
given, so for the duck-typed path this writes a brand-new dict object back
onto the *caller's* instance, replacing and mutating it in place. `#92`'s
stated invariant — "`create_machine` is a pure function of its inputs
again" — holds for only one of the two documented input shapes.

## Environment

- Commit: `5e07ba8` (post-0.8.0, pre-0.8.1 tag; `__version__` reports `0.8.0`)
- Python: 3.13.7
- Install: editable (`pip install -e .`) against
  `<workspace>/_ref/xstate-statemachine`

## Minimal reproduction

```python
"""R4-26: create_machine() still mutates a duck-typed logic object even
after #92's fix.

factory.py's `_alias_logic_names` (factory.py:252-279) makes a defensive
shallow copy of each registry (`actions`, `guards`, `services`) before
aliasing -- but only when `final_logic` is an actual `MachineLogic`
instance (factory.py:216-220): `owned_logic = copy.copy(final_logic) if
isinstance(final_logic, MachineLogic) else final_logic`. A duck-typed logic
object (any object exposing the three registry dicts, which the library's
own comments call "supported... by contract") takes the `else` branch and
is used AS-IS, so `_alias_logic_names`'s `setattr(logic, attr, owned)`
(factory.py:279) writes straight back onto the CALLER's object.

EXPECTED (per #92 / the library's own stated invariant, "create_machine is
a pure function of its inputs again"): neither supported input shape is
mutated by create_machine().
OBSERVED: the MachineLogic path is fixed, but the duck-typed path still
replaces the caller's `.actions` dict object and mutates its keys.

Exits 1 while the defect is present, 0 once fixed.
"""
from __future__ import annotations

from xstate_statemachine import MachineLogic, create_machine

CFG = {"id": "m", "initial": "a", "states": {"a": {"entry": ["storeUser"]}}}


class DuckLogic:
    """Documented as supported: "duck-typed by contract"."""

    def __init__(self):
        self.actions = {"store_user": lambda i, c, e, a: None}
        self.guards = {}
        self.services = {}


def main() -> int:
    d = DuckLogic()
    before_keys = sorted(d.actions)
    before_obj = d.actions

    create_machine(CFG, logic=d)

    replaced = d.actions is not before_obj
    mutated_keys = sorted(d.actions) != before_keys

    # Control case: the MachineLogic path should be unaffected (per #92).
    ml = MachineLogic(actions={"store_user": lambda i, c, e, a: None})
    ml_keys_before = sorted(ml.actions)
    create_machine(CFG, logic=ml)
    ml_unchanged = sorted(ml.actions) == ml_keys_before

    print(f"duck-typed caller's .actions object REPLACED: {replaced}")
    print(f"duck-typed caller's keys mutated: {mutated_keys} -> {sorted(d.actions)}")
    print(f"MachineLogic caller keys unchanged (control): {ml_unchanged}")

    defect_present = replaced or mutated_keys
    print(
        "\nOBSERVED:",
        "create_machine() mutated the duck-typed caller's object in place"
        if defect_present
        else "duck-typed object was left untouched",
    )
    print(
        "EXPECTED: create_machine() must not mutate either supported input "
        "shape (MachineLogic instance or duck-typed object)"
    )
    print("RESULT:", "FAIL - defect present" if defect_present else "PASS")
    return 1 if defect_present else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## Observed behaviour

```
duck-typed caller's .actions object REPLACED: True
duck-typed caller's keys mutated: True -> ['storeUser', 'store_user']
MachineLogic caller keys unchanged (control): True

OBSERVED: create_machine() mutated the duck-typed caller's object in place
EXPECTED: create_machine() must not mutate either supported input shape (MachineLogic instance or duck-typed object)
RESULT: FAIL - defect present
```

(exit code 1)

## Expected behaviour

`factory.py`'s own comment at the fix site states the intended contract
directly: "`create_machine()` must not modify the object it was handed" and
"`create_machine` is a pure function of its inputs again" (`factory.py:259-266`).
That statement makes no distinction between a `MachineLogic` instance and a
duck-typed object — both are explicitly supported call shapes
(`factory.py:219`'s comment: "duck-typed: leave as-is", and
`_alias_logic_names`'s own comment: "`logic` is duck-typed by contract").
The documented invariant should hold for both.

## Root cause analysis

`factory.py:216-220`:
```python
owned_logic = (
    copy.copy(final_logic)
    if isinstance(final_logic, MachineLogic)
    else final_logic  # duck-typed: leave as-is
)
```
only defensively copies when `final_logic` is a `MachineLogic` instance.
The resulting `owned_logic` (== the caller's original duck-typed object,
unchanged) is stored as `machine.logic` and passed to `_alias_logic_names`
(`factory.py:225`, `252-279`):
```python
for attr, required in (
    ("actions", actions), ("guards", guards), ("services", services),
):
    registry = getattr(logic, attr, None)
    if isinstance(registry, dict):
        owned = dict(registry)
        resolve_aliases(owned, required)
        setattr(logic, attr, owned)
```
`logic` here is the machine's `.logic`, which — for the duck-typed path —
*is* the caller's original object (no copy was interposed). `setattr(logic,
attr, owned)` therefore replaces `d.actions` on the caller's `DuckLogic`
instance with a new, alias-resolved dict, exactly the mutation `#92` set
out to eliminate.

## Impact

**General users:** any application using the documented duck-typed logic
shape (not a `MachineLogic` instance — e.g. a lightweight namespace/dataclass
exposing `.actions`/`.guards`/`.services`) and reusing that object across
multiple `create_machine()` calls (a plausible pattern: a shared logic
registry object handed to several machine variants, e.g. per-tenant state
machines built from one strategy registry) will see later machines'
aliasing pollute earlier ones' view of the object, or vice versa —
resurrecting exactly the cross-contamination bug `#92` was filed to fix,
just for the other input shape.

**Order-management scenario:** a service building multiple order-state
machines (e.g. one per order type: standard, express, backorder) from one
shared duck-typed logic registry would have the `_alias_logic_names` call
for the first machine mutate the shared object, so the second and third
machines' construction sees already-aliased keys (silently suppressing the
ambiguity/aliasing guard `#92` was designed to protect) and the *original*
caller-held registry no longer reflects what any one machine actually
uses — a correctness/audit hazard for a shared object presumed immutable
input.

## Proposed fix

Copy the duck-typed object's registries the same way the `MachineLogic`
path already does, rather than aliasing into the caller's object in place.
Options, in order of minimal surface area:

1. In `_alias_logic_names`, instead of `setattr(logic, attr, owned)`
   directly on the (possibly caller-owned) `logic`, always operate on a
   copy: build a small internal wrapper/namespace that holds the three
   alias-resolved registries and store *that* as `machine.logic`'s
   effective view (e.g. give `MachineNode` its own `_actions`/`_guards`/`_services`
   dict attributes populated here, decoupled from whatever `logic` object
   was supplied, and have interpreter action/guard/service lookup resolve
   from `machine`'s owned copies rather than `machine.logic`'s attributes
   directly).
2. Simpler, more local fix: in `factory.py:216-220`, for a duck-typed
   `final_logic`, construct a shallow proxy object (e.g.
   `types.SimpleNamespace(actions=dict(getattr(final_logic, "actions", {})),
   guards=dict(getattr(final_logic, "guards", {})), services=dict(getattr(final_logic, "services", {})))`)
   as `owned_logic`, mirroring exactly what `copy.copy` + the registry-copy
   loop already achieves for `MachineLogic`, so the same "the machine owns
   independent registry dicts" contract applies uniformly regardless of
   input shape.

Compatibility: additive; the only observable change is that a duck-typed
logic object's registries are no longer mutated by `create_machine()` —
this is the exact end state `#92`'s own commentary already claims is true.

Ride-along documented but not required to fix here: `copy.copy` is
shallow, so a `MachineLogic` **subclass** with extra instance state beyond
the three registries still shares that other state across machines built
from the same instance — worth a docstring sentence noting the copy is
registry-scoped, not a full deep copy.

## Acceptance criteria

- [ ] `repro/R4-26_ducktyped_logic_mutation.py` exits 0
- [ ] New test `tests/test_factory.py::test_create_machine_does_not_mutate_ducktyped_logic`
      builds two machines from one shared duck-typed logic object and
      asserts the object's `.actions`/`.guards`/`.services` dict identities
      and keys are unchanged after both calls
- [ ] Existing `MachineLogic`-path non-mutation test (from `#92`) continues
      to pass unmodified

## Related

- Follow-up to `#92` ("`create_machine` is a pure function of its inputs
  again") — this issue narrows that claim to the `MachineLogic` input shape
  only and extends the same fix to the duck-typed shape
- Register source ids: `probes/main-5e07ba8/r22_ducktyped_mutation.py`,
  `probes/main-5e07ba8/r23_machinelogic_subclass.py`

## Verification

- Date: 2026-09-19
- Python: 3.13.7
- Commit: `5e07ba8`
- Ran `repro/R4-26_ducktyped_logic_mutation.py` in a fresh process: output
  matched the Observed behaviour section verbatim; exit code 1.
- Confirmed `factory.py`'s `owned_logic = copy.copy(final_logic) if
  isinstance(final_logic, MachineLogic) else final_logic` (duck-typed path
  left as-is) and `_alias_logic_names`'s `setattr(logic, attr, owned)`
  writing back onto whatever `logic` object was supplied — matches the
  cited root cause.
- No duplicate open/closed GitHub issue found; `#92` (referenced as the
  original fix this issue narrows) and issue `#60` (engine-duplication
  umbrella) are related but not overlapping.
