# Unknown top-level config keys are accepted silently, so a misspelled safety policy downgrades to its permissive default

**Severity:** Medium
**Build:** `main` @ `19cb1f1` (PR #211, commit `4dbf86e`; unreleased 0.8.1). `__version__` still reports `0.8.0` — **key on the commit.**
**Environment:** CPython 3.13.7, Windows 11, fresh venv, neutral working directory.
**Carry-forward:** unchanged from `6db65d8` and `f28719c`. Re-verified on this commit.

---

## Summary

There is no whitelist validation of the **top-level key set** passed to `create_machine`. A misspelled key is accepted, the build is clean, and the value is dropped — so the policy silently reverts to its default.

Bad *values* for *known* keys **are** still correctly refused with `InvalidConfigError`. The control in the repro below confirms that, and it is why this is a narrow gap rather than a broad one.

## Observed — every safety-relevant key, one character off

| typo'd key | builds? | attribute | value seen | value with the correct key |
|---|---|---|---|---|
| `spawnBlockingTimeoutMs` | ✅ | `spawn_blocking_timeout_ms` | `None` | `1234.0` |
| `actionErrorPolicyy` | ✅ | `action_error_policy` | **`continue`** | `rollback` |
| `guardErrorPolicies` | ✅ | `guard_error_policy` | **`false`** | *(refused — correct)* |
| `maxIteration` | ✅ | `max_iterations` | **`1000`** | `42` |
| `onUnhandledEvent` | ✅ | `on_unhandled` | **`ignore`** | `error` |
| `Strict` | ✅ | `strict` | **`False`** | `True` |

6/6 silently dropped. Control: `{"actionErrorPolicy": "not-a-policy"}` → refused with `InvalidConfigError`.

## Why this is Medium rather than a nit

Look at what the defaults are, in the rows above. A single-character typo turns:

- `actionErrorPolicy: "rollback"` into **`continue`** — a failed action no longer unwinds its transition;
- `onUnhandled: "error"` into **`ignore`** — an unhandled event stops being fatal and starts being invisible;
- `strict: true` into **`false`** — the provenance and name checks `#190`/`#195`/`#203` added stop applying;
- `maxIterations: 42` into **`1000`** — the runaway budget is ~24× larger than intended.

Every one of those is a **safety policy degrading in the permissive direction, at build time, with a green build and no diagnostic**. The failure is silent at exactly the moment a diagnostic would be cheapest, and the resulting machine looks correct in every way until the policy is needed.

Casing is a particularly easy trap given the config is camelCase JSON while the attributes are snake_case Python — `Strict` vs `strict` above is one shift key.

## Suggested direction

`src/xstate_statemachine/validation.py` already does per-key value validation (`validate_machine`, config-node whitelist checks in `resolve_strict`/`_collect_findings`) but there is no top-level key-set whitelist call anywhere in the `create_machine` path — the top-level config dict is walked for known keys (`initial`, `states`, `strict`, `maxIterations`, `onUnhandled`, `actionErrorPolicy`, `guardErrorPolicy`, `spawnBlockingTimeout`, …) and each known key's *value* is validated, but an *unrecognised* key is simply never looked up, so it is silently ignored rather than raising.

Validate the top-level key set against a known whitelist in `create_machine` (or in `validation.py` alongside the existing `validate_machine`), and raise `InvalidConfigError` on an unrecognised key — the same treatment a bad value for a known key already gets. Since a hard error could be too strict for existing callers who legitimately attach custom metadata at the top level, make it opt-in via a new boolean, e.g. `strict_config: True` (default `False` for backward compatibility, flippable to `True` in a future major as the safer default) — mirroring the existing `strict` flag's opt-in-then-tighten precedent in this same codebase. Under `strict_config: True`, an unrecognised top-level key raises `InvalidConfigError`; under the default, it at minimum emits a WARNING naming the key. A reserved namespace (`x-` prefix, or a `meta` sub-object) would give custom keys a legitimate home that survives even `strict_config: True`.

A "did you mean?" suggestion against the whitelist would be a nice extra given how many of these are near-misses — the module already has a `_suggest`/`_suggest_event` fuzzy-match helper (`validation.py:119`, `:262`) that could be reused for a top-level-key suggestion — but plain refusal is enough.

We currently whitelist top-level keys in our own wrapper before calling `create_machine`. That works, but it means every consumer has to rebuild the library's own key list and keep it in sync across releases.

### XState v5 (JS/TS) behaviour, for comparison

XState v5's `createMachine(config)` does not perform a *runtime* whitelist check either — there is no equivalent of `InvalidConfigError` for an unrecognised top-level key at the JS level. Instead, XState v5 relies on its TypeScript types (the config argument is typed against `MachineConfig<TContext, TEvent, ...>`) to reject unrecognised properties **at compile time** for TypeScript consumers; a plain-JavaScript caller (or a JSON config built at runtime, which is this library's primary use case) gets no such protection and an unknown key is silently ignored the same way. That is a materially weaker guarantee than it sounds for our case: this library's config is JSON-first, so the TypeScript escape hatch XState leans on does not apply, and a runtime whitelist is the only mechanism that would actually catch a typo here. In other words, XState v5 does not set a precedent this library can appeal to for leaving the runtime gap open.

## Standalone repro

Stdlib + `xstate_statemachine` only. Runs from any working directory. Build-time only. Exit 1 = defect present.

```python
"""R10-07 (STANDALONE): unknown TOP-LEVEL config keys are accepted silently, so
a misspelled SAFETY POLICY downgrades to its permissive default with no
diagnostic.

Exit 0 = misspelled keys are diagnosed (fixed).
Exit 1 = any misspelled key builds clean while its value is dropped (defect).
"""
from __future__ import annotations

import json
import sys

from xstate_statemachine import create_machine, MachineLogic

BASE = {"id": "m", "initial": "a", "states": {"a": {}}}

# (typo'd key, correct key, attribute the correct key sets, declared value)
TYPOS = [
    ("spawnBlockingTimeoutMs", "spawnBlockingTimeout", "spawn_blocking_timeout_ms", 1234),
    ("actionErrorPolicyy", "actionErrorPolicy", "action_error_policy", "rollback"),
    ("guardErrorPolicies", "guardErrorPolicy", "guard_error_policy", "deny"),
    ("maxIteration", "maxIterations", "max_iterations", 42),
    ("onUnhandledEvent", "onUnhandled", "on_unhandled", "error"),
    ("Strict", "strict", "strict", True),
]


def _build(cfg: dict):
    return create_machine(json.loads(json.dumps(cfg)), logic=MachineLogic())


def main() -> int:
    bad = 0
    print(f"{'typo key':<26}{'built?':<9}{'attr':<26}{'value seen':<14}verdict")

    for typo, correct, attr, value in TYPOS:
        cfg = dict(BASE)
        cfg[typo] = value
        try:
            m = _build(cfg)
            built, seen = True, getattr(m, attr, "<no attr>")
        except Exception as exc:  # noqa: BLE001 - any refusal is the good case
            built, seen = False, type(exc).__name__

        # Reference: what the CORRECT key produces, so "value seen" is comparable.
        cfg2 = dict(BASE)
        cfg2[correct] = value
        try:
            ref = getattr(_build(cfg2), attr, "<no attr>")
        except Exception as exc:  # noqa: BLE001
            ref = f"<{type(exc).__name__}>"

        silent = built and seen != ref
        bad += 1 if silent else 0
        print(f"{typo:<26}{str(built):<9}{attr:<26}{str(seen):<14}"
              f"{'SILENT DOWNGRADE (ref=' + str(ref) + ')' if silent else 'ok'}")

    # Control: a bad VALUE for a KNOWN key must still be refused.
    try:
        _build({**BASE, "actionErrorPolicy": "not-a-policy"})
        print("\ncontrol: bad value for a known key -> ACCEPTED  <-- would be worse")
        bad += 1
    except Exception as exc:  # noqa: BLE001
        print(f"\ncontrol: bad value for a known key -> refused with "
              f"{type(exc).__name__} (correct)")

    print()
    print("VERDICT:", "DEFECT PRESENT" if bad else "ok",
          f"({bad}/{len(TYPOS)} keys silently dropped)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
```

### Actual output at `19cb1f1`

```
typo key                  built?   attr                      value seen    verdict
spawnBlockingTimeoutMs    True     spawn_blocking_timeout_ms None          SILENT DOWNGRADE (ref=1234.0)
actionErrorPolicyy        True     action_error_policy       continue      SILENT DOWNGRADE (ref=rollback)
guardErrorPolicies        True     guard_error_policy        false         SILENT DOWNGRADE (ref=<InvalidConfigError>)
maxIteration              True     max_iterations            1000          SILENT DOWNGRADE (ref=42)
onUnhandledEvent          True     on_unhandled              ignore        SILENT DOWNGRADE (ref=error)
Strict                    True     strict                    False         SILENT DOWNGRADE (ref=True)

control: bad value for a known key -> refused with InvalidConfigError (correct)

VERDICT: DEFECT PRESENT (6/6 keys silently dropped)
```
