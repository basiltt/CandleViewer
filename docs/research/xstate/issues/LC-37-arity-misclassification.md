---
lc: LC-37
title: "Bug: `MachineLogic` subclass auto-registration classifies callables by arity and silently misclassifies them"
labels: [bug, severity/medium, area/validation, candleviewer]
severity: Medium
blocks_adoption: false
repro_script: repro/LC-37_arity-misclassification.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

`MachineLogic.__init__` calls `_register_subclass_methods()`, which walks every public method on a `MachineLogic` subclass and files it into `self.guards`, `self.services` or `self.actions` based purely on the method's **parameter count** (2 → guard, 3 → service, 4 → action). Nothing about the method's name, a decorator, or its actual use in the machine config is consulted. A callable whose signature does not happen to match the arity of its intended contract is silently registered in the wrong registry, and one whose signature cannot be counted (`*args`, `**kwargs`) is silently dropped altogether.

No warning, no error, no log above `DEBUG`. The mistake surfaces much later as an `ImplementationMissingError` naming the *action*, which points the reader at the machine config rather than at the real cause — an off-by-one in a method signature. For a trading OMS this means an action that is supposed to record a fill is instead registered as an invokable service and never runs.

Critically, **the library already has the mechanism to prevent this and does not use it**: `@action`, `@guard` and `@service` decorators exist in `pythonic.py`, are exported from the package, and attach an explicit `fn._xsm_type` role marker. `_register_subclass_methods` never consults that marker, so a user who states the role explicitly — including in the `@service` style the guides themselves show — is still silently misfiled by arity. The fix is therefore much smaller than "design a decorator API": it is "read the marker that is already there".

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, installed with `pip install -e .`
- Python: 3.13.7 (also confirmed on 3.12.3)
- OS: Windows 11 (x64)

## Minimal reproduction

```python
"""LC-37 repro: `MachineLogic` subclass auto-registration classifies callables
by ARITY, so a callable whose parameter count does not match its intended
contract is silently filed in the wrong registry.

`machine_logic.py:_register_subclass_methods` maps 2 params -> guards,
3 -> services, 4 -> actions. Nothing about the *name*, a decorator, or the
call site is consulted, so:

  * an action written with a default argument (`(i, c, e, a=None)`) still has
    arity 4 and is fine, but an action that omits the unused `action_def`
    parameter -- `(interpreter, context, event)` -- becomes a SERVICE;
  * a guard that takes `*args` is un-classifiable and is dropped entirely;
  * a service written as `(context, event)` becomes a GUARD.

The failure is silent at construction time. The machine only blows up later
with `ImplementationMissingError` -- pointing at the action name, not at the
real cause.

Part 2 shows the sharper half of the bug: the library ALREADY ships
`@action` / `@guard` / `@service` decorators (`pythonic.py`, exported from
`xstate_statemachine.__init__`), which set an explicit `fn._xsm_type` role
marker. `_register_subclass_methods` never reads that marker, so decorating a
`MachineLogic` subclass method -- the obvious way to state the role
explicitly, and the form used by the guides' `@service` examples -- does not
help: arity still wins and the callable is still misfiled.

Exit code 1 if any callable lands in the wrong registry.
"""

from __future__ import annotations

import logging
import sys

from xstate_statemachine import MachineLogic, action, guard, service

logging.disable(logging.CRITICAL)


class OrderLogic(MachineLogic):
    """Trading-OMS logic written in the documented subclass style."""

    # Intended: ACTION. Author omitted the unused `action_def` 4th param.
    def record_fill(self, interpreter, context, event):  # noqa: ANN001
        context["fills"] = context.get("fills", 0) + 1

    # Intended: GUARD, written with *args for forwarding convenience.
    def is_filled(self, *args):  # noqa: ANN001
        return True

    # Intended: SERVICE. Author wrote the 2-arg (context, event) form used by
    # several examples in the guides.
    def submit_order(self, context, event):  # noqa: ANN001
        return {"ok": True}


class DecoratedOrderLogic(MachineLogic):
    """Same logic, but the role is stated EXPLICITLY with the library's own
    already-exported decorators. Arity still overrides the marker."""

    @action
    def record_fill(self, interpreter, context, event):  # noqa: ANN001
        context["fills"] = context.get("fills", 0) + 1

    @guard
    def is_filled(self, interpreter, context, event):  # noqa: ANN001
        return True

    @service
    def submit_order(self, context, event):  # noqa: ANN001
        return {"ok": True}


def registries_of(logic: MachineLogic, names: tuple[str, ...]) -> dict:
    """Map each method name to the registries it actually landed in."""
    return {
        n: [
            k
            for k in ("actions", "guards", "services")
            if n in getattr(logic, k)
        ]
        for n in names
    }


NAMES = ("record_fill", "is_filled", "submit_order")
EXPECTED = {
    "record_fill": ["actions"],
    "is_filled": ["guards"],
    "submit_order": ["services"],
}


def main() -> int:
    # --- 1. undecorated: arity decides, and decides wrong ------------------
    observed = registries_of(OrderLogic(), NAMES)

    print(f"OBSERVED registries (undecorated): {observed}")
    print(f"EXPECTED registries: {EXPECTED}")
    print("OBSERVED: no warning or error was raised at construction time.")
    print(
        "EXPECTED: misclassification is impossible (explicit decorators) or "
        "at minimum warns."
    )
    misfiled = observed != EXPECTED

    # --- 2. decorated: the explicit role marker is ignored -----------------
    decorated = registries_of(DecoratedOrderLogic(), NAMES)
    markers = {
        n: getattr(getattr(DecoratedOrderLogic, n), "_xsm_type", None)
        for n in NAMES
    }

    print()
    print(f"OBSERVED role markers set by @action/@guard/@service: {markers}")
    print(f"OBSERVED registries (decorated): {decorated}")
    print(f"EXPECTED registries: {EXPECTED}")
    print(
        "EXPECTED: an explicit `_xsm_type` marker takes precedence over "
        "arity, so decorating fixes the misclassification."
    )
    decorator_ignored = decorated != EXPECTED

    return 0 if not (misfiled or decorator_ignored) else 1


if __name__ == "__main__":
    sys.exit(main())
```

## Observed behaviour

```
OBSERVED registries (undecorated): {'record_fill': ['services'], 'is_filled': [], 'submit_order': ['guards']}
EXPECTED registries: {'record_fill': ['actions'], 'is_filled': ['guards'], 'submit_order': ['services']}
OBSERVED: no warning or error was raised at construction time.
EXPECTED: misclassification is impossible (explicit decorators) or at minimum warns.

OBSERVED role markers set by @action/@guard/@service: {'record_fill': 'action', 'is_filled': 'guard', 'submit_order': 'service'}
OBSERVED registries (decorated): {'record_fill': ['services'], 'is_filled': ['services'], 'submit_order': ['guards']}
EXPECTED registries: {'record_fill': ['actions'], 'is_filled': ['guards'], 'submit_order': ['services']}
EXPECTED: an explicit `_xsm_type` marker takes precedence over arity, so decorating fixes the misclassification.
```

Exit code `1`. In part 1 all three callables are wrong: the action became a service, the service became a guard, and the guard vanished.

Part 2 is the sharper result. The library **already ships** `@action`, `@guard` and `@service` decorators — defined in `pythonic.py` and exported from `xstate_statemachine` — and they do attach an unambiguous role marker (`_xsm_type` is `'action'`, `'guard'`, `'service'` respectively, as the output shows). `_register_subclass_methods` simply never reads it. Decorating the methods therefore does not fix the misclassification; it does not even change it in the right direction (`is_filled` moves from "dropped" to `services`, because the decorated form has arity 3). Stating the role explicitly, using the library's own documented decorators, is currently a no-op for `MachineLogic` subclasses.

## Expected behaviour

XState v5 never infers a callable's role from its shape. Implementations are supplied in named buckets — `createMachine(config).provide({ actions, actors, guards, delays })` — so `actions` are actions and `guards` are guards by *construction*, and an unknown or missing key is an error, not a silent reclassification. See https://stately.ai/docs/machines#providing-implementations ("Provide implementations to the machine using the `provide()` method … `actions`, `actors`, `guards`, `delays`") and https://stately.ai/docs/guards ("Guards are defined in the `guards` property of the machine implementations").

The equivalent Python-idiomatic guarantee is: a role is declared, not guessed. Where a role *is* inferred, an ambiguous or unmatched signature must be a loud error rather than a `logger.debug` line.

## Root cause analysis

`src/xstate_statemachine/machine_logic.py`:

- `:174` — `MachineLogic.__init__` unconditionally calls `self._register_subclass_methods()`.
- `:220-223` — the whole classification policy is one dict literal:
  ```python
  registries: Dict[int, Dict[str, Any]] = {
      2: self.guards,
      3: self.services,
      4: self.actions,
  }
  ```
- `:236-240` — `arity = len(inspect.signature(bound).parameters)`. For `def is_filled(self, *args)` the bound signature has exactly one parameter (`*args`), arity `1`.
- `:241-248` — `registry = registries.get(arity)`; when arity matches nothing the method is skipped with a `logger.debug` call only. `logging.disable(CRITICAL)` is not even needed to hide it: `DEBUG` is off by default, so the drop is invisible in any normal application.
- `:254` — `registry[name] = bound` files the callable with no further checks.

The arity table is a valid *description* of the three contracts, but it is not a *discriminator*: arity 3 is legitimately reachable by an action that ignores `action_def`, and arity 2 is the form used throughout the guides for guards (22 occurrences of `def <name>(self, context, event)`, all of them guards), so the three buckets overlap in practice.

`src/xstate_statemachine/pythonic.py`:

- `:443-476` (`action`), `:487-532` (`guard`), `:543-` (`service`) set the role marker: `fn._xsm_type = "action" | "guard" | "service"` plus `fn._xsm_name`.
- `:984` `_compile_logic_from_instance`, at `:1007-1016`, reads `fn._xsm_type` and dispatches into `action_dict` / `guard_dict` / `service_dict`. This is exactly the correct discriminator, but it is reachable only via the `StateMachine` / `pythonic` path (`:1477`), never from `MachineLogic.__init__`.

So the library contains two registration paths with contradictory policies: the `pythonic` one keys on an explicit marker, and the `MachineLogic` one keys on arity and ignores the marker entirely.

## Impact

**General users.** Anyone following the subclass authoring style documented in the guides can lose an action, a guard or a service to a one-character signature difference, with no diagnostic. Debugging starts from an `ImplementationMissingError` that names the right symbol but the wrong problem. Refactors are especially dangerous: adding or removing an unused parameter — a change every linter will encourage — silently relocates the callable to a different registry.

**CandleViewer trading OMS.** The order machine's `record_fill` action is written as `(interpreter, context, event)` because it never inspects `action_def`. It is registered as a *service*, so `record_fill` is missing from `logic.actions`; the `FILLED` transition's action never executes and `context["fills"]` is never incremented. The machine still transitions `submitting → filled`, so nothing looks broken from the outside — but the position exists on the exchange while the machine's context reports zero fills, and downstream P&L and risk checks read from that context. A guard written with `*args` fails the same way from the other direction: it disappears from `logic.guards`, and the transition it protects raises at runtime on the first real fill.

## Proposed fix

**Design.** Make the role explicit; keep arity inference only as an opt-in, warning fallback. The decorators already exist, so step 1 is to *honour* them, not to build them.

1. In `_register_subclass_methods` (`machine_logic.py:220-255`), check `getattr(member, "_xsm_role", None)` — i.e. the existing `_xsm_type` marker set by `pythonic.action` / `guard` / `service` — **first**, and register directly into the named registry, ignoring arity entirely. Note the name used for registration should stay the Python method name here (`MachineLogic` registries are keyed by the name the config references), whereas `pythonic` re-keys to `_xsm_name`'s camelCase; keep those two behaviours distinct or the camelCase mapping of issue #17 regresses.
2. Re-export the decorators from `machine_logic`'s documented surface (they are already in `xstate_statemachine.__all__`) and show them in the `MachineLogic` subclass examples in the guides, which currently demonstrate the undecorated form.
3. For an undecorated public method, keep the arity table but make every ambiguous outcome loud:
   - arity matches no contract (`*args`, `**kwargs`, arity 0/1/5+) → `warnings.warn(...)` (currently `logger.debug`);
   - arity 3 or 2 with no decorator → `warnings.warn` naming both plausible roles and pointing at the decorators.
4. Add a `MachineLogic(strict=True)` / module-level opt-in that upgrades those warnings to `ImplementationMissingError` at construction time.

**Backwards compatibility.** Existing subclasses whose arities happen to be right keep working unchanged; they only gain warnings when genuinely ambiguous. Honouring `_xsm_type` is a behaviour change *only* for code that decorates a `MachineLogic` subclass method today — which is code that is currently broken, since the decorator is ignored. Deprecate bare-arity inference in the docs for 0.8, keep it (warning) through 0.9, and consider `strict=True` as the default in 1.0.

**Alternative, lower-effort mitigation.** Cross-check the registration against the machine config once the logic is bound in `create_machine`: any name referenced as an `actions:` entry but found only in `logic.services` is a certain misclassification and can be reported precisely.

## Acceptance criteria

- [ ] The existing `@action` / `@guard` / `@service` decorators (`pythonic.py`) are honoured by `MachineLogic._register_subclass_methods` and take precedence over arity.
- [ ] A decorated `MachineLogic` subclass method is registered under its Python method name, without disturbing the camelCase re-keying the `pythonic` path performs.
- [ ] A public subclass method with an un-classifiable signature (`*args`) emits a `UserWarning` instead of a `logger.debug` line.
- [ ] A public subclass method of arity 2 or 3 with no decorator emits a `UserWarning` naming the ambiguity.
- [ ] Explicitly supplied dictionaries continue to win over subclass methods (existing behaviour, `machine_logic.py:250-252`).
- [ ] `repro/LC-37_arity-misclassification.py` exits `0`.
- [ ] Tests added under `tests/test_machine_logic_registration.py`:
  - `test_decorated_action_with_three_params_registers_as_action`
  - `test_decorated_service_with_two_params_registers_as_service`
  - `test_var_args_method_warns_and_is_not_dropped_silently`
  - `test_undecorated_ambiguous_arity_warns`
  - `test_explicit_dict_still_overrides_subclass_method`
  - `test_strict_mode_raises_on_ambiguous_signature`

## Related

- `LC-36` — built-in action params silently ignored when misspelled (same family: silent misconfiguration with no diagnostic).
- `LC-34` — no strict mode / no payload validation; the `strict=True` proposed here is the natural home for this check.
- `LC-08` — unknown targets unvalidated (config-side counterpart of the same missing validation pass).
- Found during an independent evaluation of the library for a trading application; the reproduction above is self-contained and needs nothing from that study.

## Verification

Independently verified on 2026-09-15.

- Environment: `xstate-statemachine` 0.7.0, commit `42612cf`, editable install; CPython 3.13.7; Windows 11 x64.
- `repro/LC-37_arity-misclassification.py` run in a fresh process: **exit code 1** (reproduces).
- Root-cause references re-checked against the source: `machine_logic.py:174` (`_register_subclass_methods()` call), `:220-223` (arity→registry table), `:236` (`arity = len(...)`), `:241-248` (`registries.get` + `logger.debug` skip), `:250-252` (explicit dict wins), `:254` (registration). All confirmed.
- Expected-behaviour claim re-checked against XState v5 docs: https://stately.ai/docs/machines confirms implementations are provided in named buckets (`actions`, `actors`, `guards`, `delays`) via `setup()` / `provide()`, and https://stately.ai/docs/guards confirms guards are supplied under a `guards` key. The claim that XState never infers a callable's role from its shape is accurate.
- Corrections applied during verification:
  - The issue originally proposed *adding* `@action` / `@guard` / `@service` decorators. They **already exist** in `pythonic.py`, are exported from `xstate_statemachine`, and set an explicit `_xsm_type` role marker — which `_register_subclass_methods` ignores. The summary, root-cause, proposed fix and acceptance criteria were rewritten around "honour the existing marker", and the repro gained a part 2 proving the decorators are ignored.
  - Corrected the claim that arity 2 is "the form used for services in several guide examples": all 22 two-argument `(self, context, event)` examples in `docs/` are guards. The guides' `@service` examples use the three-argument form.
  - Added the cross-path reference: `pythonic.py:984` `_compile_logic_from_instance` already dispatches correctly on `_xsm_type`.
- Duplicate check: `gh issue list --state all` returns one issue (#17, closed) about camelCase→snake_case auto-discovery in `logic_providers`. Different mechanism and different failure; **not a duplicate**.
