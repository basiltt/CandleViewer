"""R4-14: a dict event with a non-str `type` (or a non-event object) raises
an UNTYPED AttributeError/TypeError instead of a documented
XStateMachineError subclass -- escaping `except XStateMachineError`.

`_prepare_event` (base_interpreter.py ~1616-1619) pops `type` from a dict
event with no `isinstance(str)` check and forwards it straight to
`_check_strict` -> `UnknownEventError.__init__`, which calls
`difflib.get_close_matches(event_type, known, ...)` -- that crashes with a
bare AttributeError/TypeError when `event_type` is not a `str` (e.g. `None`
or `123`). Separately, `_prepare_event`'s final `else` branch (case 5, "any
non-event object") raises a bare builtin `TypeError`, not a library
exception, even though the docstring documents this as the "unsupported
format" path.

EXPECTED: any malformed event given to send() raises a typed
XStateMachineError subclass, catchable via `except XStateMachineError`.
OBSERVED: dict events with a non-str `type` raise untyped
AttributeError/TypeError, and non-event objects raise a bare TypeError that
`except XStateMachineError` does not catch.

Exits 1 while the defect is present, 0 once fixed.
"""
from __future__ import annotations

from xstate_statemachine import MachineLogic, SyncInterpreter, XStateMachineError, create_machine

CFG = {
    "id": "m",
    "initial": "a",
    "states": {"a": {"on": {"GO": "#m.b"}}, "b": {}},
}


def main() -> int:
    untyped_dict_cases = []
    for strict in (False, True):
        i = SyncInterpreter(create_machine(CFG, logic=MachineLogic()), strict=strict)
        i.start()
        for ev in ({"type": None}, {"type": 123}):
            try:
                i.send(ev)
                untyped_dict_cases.append((strict, ev, "accepted"))
            except XStateMachineError as exc:
                untyped_dict_cases.append((strict, ev, f"typed {type(exc).__name__}"))
            except Exception as exc:  # noqa: BLE001
                untyped_dict_cases.append((strict, ev, f"UNTYPED {type(exc).__name__}: {exc}"))

    i2 = SyncInterpreter(create_machine(CFG, logic=MachineLogic()))
    i2.start()
    bare_type_error_cases = []
    for ev in (None, 123, b"B", ["GO"], object()):
        try:
            i2.send(ev)
            bare_type_error_cases.append((type(ev).__name__, "accepted"))
        except XStateMachineError as exc:
            bare_type_error_cases.append((type(ev).__name__, f"typed {type(exc).__name__}"))
        except TypeError as exc:
            bare_type_error_cases.append((type(ev).__name__, f"bare TypeError: {exc}"))

    print("dict-with-non-str-type cases:")
    for row in untyped_dict_cases:
        print(" ", row)
    print("\nnon-event-object cases:")
    for row in bare_type_error_cases:
        print(" ", row)

    n_untyped = sum(1 for r in untyped_dict_cases if "UNTYPED" in r[2])
    n_bare = sum(1 for r in bare_type_error_cases if "bare TypeError" in r[1])

    defect_present = n_untyped > 0 or n_bare > 0
    print(
        f"\nOBSERVED: {n_untyped}/4 dict-with-non-str-type cases raised an "
        f"untyped error, {n_bare}/5 non-event objects raised a bare TypeError"
    )
    print(
        "EXPECTED: 0/4 and 0/5 -- every malformed event raises a typed "
        "XStateMachineError subclass"
    )
    print("RESULT:", "FAIL - defect present" if defect_present else "PASS")
    return 1 if defect_present else 0


if __name__ == "__main__":
    raise SystemExit(main())
