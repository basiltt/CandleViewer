"""LC-37 (GH #52) verification on xstate-statemachine main @ 5327ba6.

Acceptance criteria under test (per issue #52 + task "need"):

  1. `MachineLogic(strict=True)` raises `InvalidConfigError` at construction
     for an UNDECORATED public method (arity gives no unambiguous answer,
     and the whole point of strict is to refuse to guess).
  2. A method decorated with `@action` / `@guard` / `@service` is registered
     correctly regardless of `strict`, and regardless of its arity.
  3. A `_private` (leading-underscore) helper is never registered and never
     triggers the strict error, decorated or not.
  4. Default `strict=False` is unchanged: undecorated methods still fall
     back to arity-based classification with a `UserWarning` (not an
     error).
  5. Ambiguous case/separator-variant registrations (e.g. `fetch_data` and
     `fetchData` both registered for a name the machine requires) are
     rejected at BUILD time (`create_machine`) with `InvalidConfigError`,
     independent of the `MachineLogic.strict` flag.

Exits 0 only if every criterion passes.
"""

from __future__ import annotations

import sys
import warnings
from typing import Any, List, Tuple

from xstate_statemachine import (
    InvalidConfigError,
    MachineLogic,
    action,
    create_machine,
    guard,
    service,
)

RESULTS: List[Tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


# ---------------------------------------------------------------------------
# 1. strict=True raises for an undecorated public method.
# ---------------------------------------------------------------------------
def check_strict_raises_on_undecorated() -> None:
    class UndecoratedLogic(MachineLogic):
        def record_fill(self, interpreter, context, event):  # noqa: ANN001
            context["fills"] = context.get("fills", 0) + 1

    err: Any = None
    try:
        UndecoratedLogic(strict=True)
    except InvalidConfigError as exc:
        err = exc
    except Exception as exc:  # noqa: BLE001
        err = exc

    record(
        "1a. MachineLogic(strict=True) raises InvalidConfigError for an "
        "undecorated public subclass method",
        isinstance(err, InvalidConfigError),
        f"raised = {err!r}",
    )
    record(
        "1b. the error names the offending method",
        isinstance(err, InvalidConfigError) and "record_fill" in str(err),
        f"message = {str(err)!r}",
    )


# ---------------------------------------------------------------------------
# 2. Decorated methods register correctly under strict=True regardless of
#    arity (arity would normally misclassify these).
# ---------------------------------------------------------------------------
def check_strict_allows_decorated_methods() -> None:
    class DecoratedLogic(MachineLogic):
        @action
        def record_fill(self, interpreter, context, event):  # noqa: ANN001
            context["fills"] = context.get("fills", 0) + 1

        @guard
        def is_filled(self, *args):  # noqa: ANN001
            return True

        @service
        def submit_order(self, context, event):  # noqa: ANN001
            return {"ok": True}

    err: Any = None
    logic: Any = None
    try:
        logic = DecoratedLogic(strict=True)
    except Exception as exc:  # noqa: BLE001
        err = exc

    record(
        "2a. strict=True does NOT raise when every public method is "
        "decorated, regardless of arity",
        err is None,
        f"raised = {err!r}",
    )
    if logic is not None:
        registries = {
            n: [
                k
                for k in ("actions", "guards", "services")
                if n in getattr(logic, k)
            ]
            for n in ("record_fill", "is_filled", "submit_order")
        }
        expected = {
            "record_fill": ["actions"],
            "is_filled": ["guards"],
            "submit_order": ["services"],
        }
        record(
            "2b. decorated methods land in the registry their decorator "
            "names, not the one arity would have picked",
            registries == expected,
            f"registries = {registries!r}, expected = {expected!r}",
        )


# ---------------------------------------------------------------------------
# 3. `_private` helpers are exempt from strict, decorated or not.
# ---------------------------------------------------------------------------
def check_private_helpers_exempt() -> None:
    class WithPrivateHelper(MachineLogic):
        @action
        def record_fill(self, interpreter, context, event):  # noqa: ANN001
            self._helper()

        def _helper(self) -> None:
            pass

    err: Any = None
    try:
        WithPrivateHelper(strict=True)
    except Exception as exc:  # noqa: BLE001
        err = exc

    record(
        "3. a leading-underscore helper never triggers the strict error",
        err is None,
        f"raised = {err!r}",
    )


# ---------------------------------------------------------------------------
# 4. Default strict=False is unchanged: arity fallback + UserWarning, not an
#    error.
# ---------------------------------------------------------------------------
def check_default_is_unchanged_warn_not_raise() -> None:
    class UndecoratedLogic(MachineLogic):
        def record_fill(self, interpreter, context, event):  # noqa: ANN001
            context["fills"] = context.get("fills", 0) + 1

        def is_filled(self, *args):  # noqa: ANN001
            return True

    err: Any = None
    caught_warnings: list = []
    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            logic = UndecoratedLogic()  # strict defaults to False
            caught_warnings = list(w)
    except Exception as exc:  # noqa: BLE001
        err = exc
        logic = None

    record(
        "4a. default strict=False never raises for undecorated methods "
        "(backwards compatible)",
        err is None,
        f"raised = {err!r}",
    )
    if logic is not None:
        record(
            "4b. an arity-ambiguous undecorated method (record_fill, 3-arg) "
            "still lands somewhere via the arity fallback",
            "record_fill" in logic.services or "record_fill" in logic.actions,
            f"actions = {list(logic.actions)}, services = {list(logic.services)}",
        )
        record(
            "4c. an un-classifiable arity (is_filled, *args) emits a "
            "UserWarning rather than silently dropping",
            any(
                issubclass(rec.category, UserWarning)
                and "is_filled" in str(rec.message)
                for rec in caught_warnings
            ),
            f"warnings = {[str(r.message) for r in caught_warnings]!r}",
        )


# ---------------------------------------------------------------------------
# 5. Ambiguous case/separator-variant registrations rejected at BUILD time.
# ---------------------------------------------------------------------------
def check_ambiguous_variant_registration_rejected() -> None:
    def fetch_data_snake(context, event):  # noqa: ANN001
        return "snake"

    def fetch_data_camel(context, event):  # noqa: ANN001
        return "camel"

    logic = MachineLogic(
        guards={
            "fetch_data": fetch_data_snake,
            "fetch-data": fetch_data_camel,
        }
    )
    cfg = {
        "id": "amb",
        "initial": "a",
        "states": {
            "a": {
                "on": {
                    "GO": {
                        "target": "b",
                        "guard": "fetchData",
                    }
                }
            },
            "b": {},
        },
    }
    err: Any = None
    try:
        create_machine(cfg, logic=logic)
    except InvalidConfigError as exc:
        err = exc
    except Exception as exc:  # noqa: BLE001
        err = exc

    record(
        "5a. two case/separator-variant callables registered for a name "
        "the machine requires raise InvalidConfigError at build time",
        isinstance(err, InvalidConfigError),
        f"raised = {err!r}",
    )
    record(
        "5b. the error names both colliding variants",
        isinstance(err, InvalidConfigError)
        and "fetch_data" in str(err)
        and "fetch-data" in str(err),
        f"message = {str(err)!r}",
    )


def main() -> int:
    check_strict_raises_on_undecorated()
    check_strict_allows_decorated_methods()
    check_private_helpers_exempt()
    check_default_is_unchanged_warn_not_raise()
    check_ambiguous_variant_registration_rejected()

    print()
    all_ok = all(ok for _, ok, _ in RESULTS)
    for name, ok, detail in RESULTS:
        print(f"{'OK ' if ok else 'XX '} {name}")
    print(f"\nRESULT: {'ALL PASS' if all_ok else 'FAILURES PRESENT'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
