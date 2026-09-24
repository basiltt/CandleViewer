"""LC-37 verification on xstate-statemachine 0.8.0.

Acceptance: the existing @action/@guard/@service decorators (which set
`_xsm_type`) are now honoured by MachineLogic._register_subclass_methods
and take precedence over arity; undecorated ambiguous-arity methods now
warn instead of silently misfiling/dropping. This is default behaviour,
no opt-in flag.
"""

from __future__ import annotations

import sys
import warnings

from xstate_statemachine import MachineLogic, action, guard, service


class OrderLogic(MachineLogic):
    """Undecorated: arity historically decided (and decided wrong)."""

    def record_fill(self, interpreter, context, event):  # noqa: ANN001
        context["fills"] = context.get("fills", 0) + 1

    def is_filled(self, *args):  # noqa: ANN001
        return True

    def submit_order(self, context, event):  # noqa: ANN001
        return {"ok": True}


class DecoratedOrderLogic(MachineLogic):
    """Decorated: explicit _xsm_type marker should now win."""

    @action
    def record_fill(self, interpreter, context, event):  # noqa: ANN001
        context["fills"] = context.get("fills", 0) + 1

    @guard
    def is_filled(self, interpreter, context, event):  # noqa: ANN001
        return True

    @service
    def submit_order(self, context, event):  # noqa: ANN001
        return {"ok": True}


def registries_of(logic: MachineLogic, names):
    return {
        n: [k for k in ("actions", "guards", "services") if n in getattr(logic, k)]
        for n in names
    }


NAMES = ("record_fill", "is_filled", "submit_order")
EXPECTED = {
    "record_fill": ["actions"],
    "is_filled": ["guards"],
    "submit_order": ["services"],
}


def main() -> int:
    ok = True

    # Part 1: decorated form must now win over arity (the acceptance criterion).
    decorated = registries_of(DecoratedOrderLogic(), NAMES)
    print(f"OBSERVED registries (decorated): {decorated}")
    print(f"EXPECTED registries: {EXPECTED}")
    if decorated != EXPECTED:
        print("OBSERVED: decorator marker NOT honoured")
        ok = False
    else:
        print("OBSERVED: decorator marker honoured, precedence over arity confirmed")

    # Part 2: undecorated ambiguous arity warns (documented as still
    # arity-based fallback but now loud instead of silent).
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        undecorated = registries_of(OrderLogic(), NAMES)
    print(f"OBSERVED registries (undecorated, default fallback): {undecorated}")
    warned = any(issubclass(w.category, UserWarning) for w in caught)
    print(f"OBSERVED: UserWarning emitted for ambiguous undecorated methods = {warned}")
    print("EXPECTED: True (silent misfiling is now at least loud)")
    if not warned:
        ok = False

    print("RESULT:", "FIXED-DEFAULT" if ok else "NOT FIXED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
