---
lc: M-3
title: "Bug: the alias-ambiguity guard does not fire for its own documented example (`fetchData` required, `fetch_data` + `fetchData` registered)"
labels: [bug, severity/medium, area/machine-logic, docs, candleviewer]
severity: Medium
blocks_adoption: false
verified: true
status: still-present
retested_on: main@3c527b0 (2026-09-18, after PR #83)
repro_script: new-main/repro/g1b_alias_ambiguity_and_leak.py
library_version: main@3c527b0
python: 3.13.7
found_by: main @ 5327ba6 adversarial verification (21-verify-main-adversarial.md M-3; diff review F-4)
related_issue: "snake_case/camelCase alias feature, [Unreleased] Changed"
---

## Summary

CHANGELOG, *Changed*:

> Registering two *different* callables whose names differ only by case or
> separators (`fetch_data` and `fetchData`) for a name the machine requires now
> raises `InvalidConfigError` at build time instead of silently picking one.

`resolve_aliases` skips any required name already present in the registry
(`if name in registry: continue`), so the guard only runs when the config name
matches **neither** registered spelling exactly. The documented example is
precisely the case it does not catch.

Separately (diff-review F-4), the guard checks only the **registry** side —
`distinct = {id(registry[c]) for c in candidates}` — and never the converse:
two *different config names* that normalise equal both bind silently to one
callable.

## Environment

- Library: `xstate-statemachine`, local clone, `main` @ commit
  `5327ba69fb735cfe24c7b3772050dac0a71a7b3d`, `pip install -e .`
- Python: 3.13.7 (CPython) · Windows 11 x64 (10.0.26200)

## Location

`src/xstate_statemachine/machine_logic.py:158-186` (`resolve_aliases`).

## Minimal reproduction

Both `fetch_data` and `fetchData` registered as **different** callables; vary
the name the config requires. Full script:
`repro/g1b_alias_ambiguity_and_leak.py`.

## Observed

```
both 'fetch_data' and 'fetchData' registered (DIFFERENT callables):
  config requires 'fetchData'   -> BUILT            <- the documented example
  config requires 'fetch_data'  -> BUILT
  config requires 'fetch-data'  -> InvalidConfigError
  config requires 'FetchData'   -> InvalidConfigError
```

The guard catches only the spellings a config is *least* likely to use. The
realistic shape — camelCase JSON from Stately naming `fetchData`, against a
Python module that grew both a `fetch_data` and a `fetchData`, one of them
stale — is resolved silently to the exact key.

Config-side collapse (`repro/f_stately.py`, `repro/f_collide.py`):

```
both bound: {'fetchData': 'a1', 'fetch-data': 'a1', 'fetch.data': 'a1'}
```

A config declaring `fetch-data` and `fetch.data` as two entry actions runs the
same `a1` twice, with no warning. This is a plausible Stately export shape: the
CHANGELOG explicitly advertises `inline:m.a#entry[0]`-style non-identifier
names as aliasable, and those are *generated* — the author never chose them and
cannot reason about their normalised collisions.

## Expected

Either behaviour is defensible; the two must agree with each other and with the
documentation:

- **(a)** exact-match precedence is intended (probe G5 confirms it works and is
  desirable) — then the *ambiguity* claim is overstated and the CHANGELOG
  should say the guard fires only when no exact key exists; **and** a
  `UserWarning` should fire when a shadowed near-duplicate is present, because
  silently preferring one of two different callables is the exact failure the
  feature was added to prevent; or
- **(b)** the guard runs regardless of exact-match, raising for the documented
  example as written.

Independently, the config side should be checked: two required names that
normalise equal and resolve to one callable should at least warn.

## Acceptance criteria

1. The CHANGELOG's own example behaves as the CHANGELOG describes, or the
   CHANGELOG is corrected — and a test pins whichever is chosen.
2. `repro/g1b_alias_ambiguity_and_leak.py` (part 1) produces a consistent
   outcome across all four required-name spellings: either all raise or all
   build-with-warning.
3. Two distinct config names normalising to one registered callable produce at
   least a `UserWarning` naming both (`repro/f_stately.py`,
   `repro/f_collide.py`).
4. Tests: `test_ambiguous_alias_fires_for_exact_match_name`,
   `test_two_config_names_collapsing_to_one_impl_warns`.


---

## Re-test on `main@3c527b0` (2026-09-18, after PR #83)

**Status: STILL-PRESENT.** PR #83 (`2459c82`: ErrorEvent #80, provenance
system events #79, one-task-per-child #43) does not touch this code path.
Repro re-run on `3c527b0` with the same interpreter and environment.

```
$ python repro/g1b_alias_ambiguity_and_leak.py
  config requires 'fetchData'      -> BUILT     # both spellings registered, DIFFERENT fns
  config requires 'fetch_data'     -> BUILT
  config requires 'fetch-data'     -> InvalidConfigError
  config requires 'FetchData'      -> InvalidConfigError

$ python repro/f_loader_twoname.py
both bound to one impl: {'fetchData': 'fetch_data', 'fetch-data': 'fetch_data'}
```

See `../../23-verify-3c527b0-findings.md` for the full re-test table.
