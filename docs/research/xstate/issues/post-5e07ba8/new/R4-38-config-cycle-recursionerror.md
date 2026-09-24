---
r4: R4-38
title: "Bug: self-referential (aliased-cycle) machine config raises RecursionError instead of InvalidConfigError"
labels: [bug, severity/low, area/validation]
severity: Low
repro_script: repro/R4-38_config_cycle_recursionerror.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

`StateNode.__init__` recurses into `config["states"]` with no cycle
detection. A hand-built Python config dict that contains itself as one of
its own descendant state configs (an aliased cycle — impossible to express
in JSON, but trivial to construct programmatically, e.g. when generating
config from a shared template object) blows the Python call stack with a
bare `RecursionError` instead of raising the library's typed
`InvalidConfigError`, breaking the "all malformed-config failures are typed
and catchable" contract the rest of `create_machine`'s validation follows.

## Environment

- Commit: 5e07ba8 (unreleased 0.8.1; `__version__` reports 0.8.0)
- Python: 3.13.7
- OS: Windows 11
- Editable install via `.venv-main`

## Minimal reproduction

```python
"""R4-38: a self-referential (aliased-cycle) config dict causes a
RecursionError instead of a typed InvalidConfigError.

StateNode.__init__ recurses into config["states"] with no cycle detection.
A hand-built Python dict that contains itself as one of its own child
state configs (impossible to express in JSON, but easy to construct in
Python) blows the interpreter stack instead of raising a typed,
catchable XStateMachineError.

Exits 1 (defect present) if a RecursionError escapes create_machine().
Exits 0 once a typed InvalidConfigError is raised instead.
"""
import sys

from xstate_statemachine import MachineLogic, XStateMachineError, create_machine


def main() -> int:
    a: dict = {"initial": "x", "states": {}}
    a["states"]["x"] = a  # aliased cycle: "x"'s config IS "a" itself

    cfg = {"id": "m", "initial": "a", "states": {"a": a}}

    try:
        create_machine(cfg, logic=MachineLogic())
        print("OBSERVED: create_machine() returned normally (unexpected)")
        return 1
    except XStateMachineError as exc:
        print(f"OBSERVED: typed {type(exc).__name__}: {exc}")
        print("\nEXPECTED: a typed InvalidConfigError naming the cyclic state")
        print("RESULT: typed error raised -- fixed")
        return 0
    except RecursionError as exc:
        print(f"OBSERVED: RecursionError: {exc}")
        print("\nEXPECTED: a typed InvalidConfigError naming the cyclic state, "
              "not a bare RecursionError")
        print("RESULT: untyped RecursionError -- defect present")
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

## Observed behaviour

```
OBSERVED: RecursionError: maximum recursion depth exceeded

EXPECTED: a typed InvalidConfigError naming the cyclic state, not a bare RecursionError
RESULT: untyped RecursionError -- defect present
```

## Expected behaviour

Every other malformed-config path in `create_machine` raises a typed
`XStateMachineError` subclass (e.g. `InvalidConfigError`) rather than
letting a Python built-in exception escape — this is the library's own
documented contract for build-time validation. A cyclic config should be
no exception to that contract; it should raise `InvalidConfigError` naming
the cyclic state, not surface as an untyped `RecursionError` with a stack
trace that gives the caller no indication of what is actually wrong with
their config.

## Root cause analysis

`StateNode.__init__` (in `src/xstate_statemachine/models.py` per the
constructor call chain exercised by `create_machine`) recursively
constructs a child `StateNode` for every entry in `config["states"]`
with no tracking of already-visited config-dict identities. When a config
dict is built by hand (not from JSON) such that one of its nested
`states` entries is the same object as an ancestor's config dict — e.g.
`a["states"]["x"] = a` — the recursive descent never terminates and the
Python interpreter raises `RecursionError` once the call stack is
exhausted, well before any of the library's own validation code gets a
chance to detect the cycle.

## Impact

For general users, this converts a config-authoring mistake into a bare
interpreter crash with a deep, unhelpful traceback instead of a clear,
typed error naming the offending state — a much worse debugging experience
than every other config-validation failure in the library. For the
adopting project's order-management scenario, config is normally
JSON-sourced and cannot express an aliased cycle, so this specific trigger
does not apply directly; it becomes reachable only if config is
constructed by hand from shared Python objects/templates (e.g. programmatic
config generation that accidentally reuses a mutable dict across nesting
levels). Severity is genuinely Low for that reason, but the fix is cheap
and brings this path in line with the "always typed, never a bare
built-in exception" contract that already covers the other unimplemented
config edge cases (R4-02, R4-14).

## Proposed fix

During `StateNode` construction, track visited config-dict `id()`s on the
recursion stack (a `set` passed down through the recursive constructor
calls, or an instance-level "currently under construction" marker). When a
nested `states` entry's `id()` is already in that set, raise
`InvalidConfigError` naming the state id/path where the cycle was
detected, instead of recursing further. This mirrors the existing
`InvalidConfigError` used for other structurally invalid configs
elsewhere in the same constructor, so no new exception type is needed.

## Acceptance criteria

- [ ] `StateNode.__init__` (or its call site in `create_machine`) detects a cyclic config via visited-id tracking and raises `InvalidConfigError`.
- [ ] `InvalidConfigError` message names the state id/path where the cycle was detected.
- [ ] `tests/test_validation.py::test_self_referential_config_raises_invalid_config_error` (new) builds an aliased-cycle dict and asserts `InvalidConfigError` (not `RecursionError`) is raised.
- [ ] `repro/R4-38_config_cycle_recursionerror.py` exits 0.

## Related

- Register source: `battle-5e07ba8/fuzz/repros.py`, function `d9` (labelled `D-fuzz-9` in output, cross-referenced as `D-fuzz-8` in the register's source-id mapping).
- Register row: R4-38 in `30-r4-findings-register.md`.
- Similar "escapes XStateMachineError" precedent: R4-02, R4-14.

## Verification

- Date: 2026-09-19
- Python: 3.13.7 (`.venv-main`)
- Commit: 5e07ba8 (unreleased 0.8.1; `__version__` reports 0.8.0)
- Ran `repro/R4-38_config_cycle_recursionerror.py` in a fresh process: exit code 1, output matches the Observed section (`RecursionError: maximum recursion depth exceeded`, not a typed `XStateMachineError`).
- Confirmed root cause: `src/xstate_statemachine/models.py` defines `class StateNode` (line 722) which recursively constructs child `StateNode`s from `config["states"]` with no visited-id tracking; `InvalidConfigError` is imported and raised at multiple other validation points in the same file (lines 117, 261, 293, 390, 416, 434, 443, etc.) for other malformed-config cases, confirming the "always typed" contract the finding describes, but none of those checks guard against an aliased-cycle config dict.
- No external XState/SCXML claim to check (this is an internal robustness/typed-exception argument, not an XState semantics parity claim).
- Checked for duplicates: `gh issue list -R basiltt/xstate-statemachine --state all --search "RecursionError cycle config"` returns no results. No duplicate found.
- No project name/label leakage found in the file.
- Status: reproducible, defect confirmed present.
