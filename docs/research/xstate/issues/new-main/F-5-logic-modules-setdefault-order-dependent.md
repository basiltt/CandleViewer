---
lc: F-5
title: "Bug: the `logic_modules` normalised index uses `setdefault`, so duplicate snake/camel implementations resolve by module iteration order with no error"
labels: [bug, severity/medium, area/logic-loader, candleviewer]
severity: Medium
blocks_adoption: false
verified: true
status: still-present
retested_on: main@3c527b0 (2026-09-18, after PR #83)
repro_script: new-main/repro/f_loader_dup.py
library_version: main@3c527b0
python: 3.13.7
found_by: main @ 5327ba6 diff review (19-verify-main-diff-review.md F-5)
related_issue: "snake_case/camelCase alias feature, [Unreleased] Added/Changed"
---

## Summary

The CHANGELOG states that *"ambiguous logic registrations are rejected … raises
`InvalidConfigError` at build time instead of silently picking one."* That
describes `resolve_aliases` only. The **auto-discovery** path — the one most
users hit — still silently picks one, by module iteration order.

## Environment

- Library: `xstate-statemachine`, local clone, `main` @ commit
  `5327ba69fb735cfe24c7b3772050dac0a71a7b3d`, `pip install -e .`
- Python: 3.13.7 (CPython) · Windows 11 x64 (10.0.26200)

## Location

`src/xstate_statemachine/logic_loader.py:404-409`:

```python
for key, impl in logic_map.items():
    normalized_map.setdefault(normalize_logic_name(key), impl)
```

`setdefault` means **first wins by module iteration order**.

## Minimal reproduction

A module defining both `fetch_data` (returns `"SNAKE"`) and `fetchData`
(returns `"CAMEL"`), with the config naming `FETCH_DATA`. Full script:
`repro/f_loader_dup.py`.

## Observed

```
bound to: fetch_data
```

No error, no warning. Which one binds depends on definition order in the
module. Both are genuinely different callables — exactly the case
`resolve_aliases` was written to reject.

`_alias_logic_names` does run afterwards in `create_machine`, but by then the
loader has already placed an exact-name entry, so the guard is bypassed.

`repro/f_loader_twoname.py` shows the companion shape on this path: one
implementation silently satisfying two distinct config names.

## Expected

The documented ambiguity rejection applies to the `logic_modules` /
`logic_providers` discovery path too: two different callables in a module whose
names normalise equal, for a name the machine requires, is an
`InvalidConfigError` at build time naming both spellings and their module —
the same message shape `resolve_aliases` already produces.

At minimum, if silent selection is retained for backwards compatibility, it
must emit a `UserWarning` naming both candidates and which one won, because
"first wins by module iteration order" is not a contract a user can reason
about.

## Proposed fix

Replace `setdefault` with an explicit collision check that collects candidates
and defers the decision to the same `resolve_aliases` ambiguity logic, so the
two paths share one implementation and one error message.

## Acceptance criteria

1. `repro/f_loader_dup.py` exits 0 — a module with both `fetch_data` and
   `fetchData` as different callables, required as `FETCH_DATA`, raises
   `InvalidConfigError` (or warns, per the chosen contract) rather than binding
   silently.
2. The error/warning names both spellings and the defining module.
3. A module with only one spelling is unaffected; exact-name matches still win.
4. Discovery order does not change the outcome (test with both definition
   orders).
5. Tests: `test_logic_modules_duplicate_normalized_names_rejected`,
   `test_logic_modules_binding_is_order_independent`.


---

## Re-test on `main@3c527b0` (2026-09-18, after PR #83)

**Status: STILL-PRESENT.** PR #83 (`2459c82`: ErrorEvent #80, provenance
system events #79, one-task-per-child #43) does not touch this code path.
Repro re-run on `3c527b0` with the same interpreter and environment.

```
$ python repro/f_loader_dup.py
bound to: fetch_data          # silently; no ambiguity error
```

See `../../23-verify-3c527b0-findings.md` for the full re-test table.
