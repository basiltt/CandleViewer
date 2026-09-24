# -*- coding: utf-8 -*-
"""Verify #113 on 3ed3099: malformed events raise a typed InvalidEventError
(subclass of both XStateMachineError and TypeError) instead of a bare
AttributeError/TypeError escaping the documented catch-all.

Criteria:
  1. dict with non-str `type` (None, 123) -> InvalidEventError, for both
     strict=False and strict=True.
  2. dict missing `type` key -> InvalidEventError.
  3. Non-event objects (None, int, bytes, list, object()) -> InvalidEventError,
     not a bare TypeError.
  4. InvalidEventError IS a subclass of XStateMachineError (documented
     catch-all still works).
  5. InvalidEventError IS ALSO a subclass of TypeError (0.8.0 compat: an
     existing `except TypeError` around send() still works).

Exits 0 iff all pass.
"""
from __future__ import annotations

from xstate_statemachine import (
    InvalidEventError,
    MachineLogic,
    SyncInterpreter,
    XStateMachineError,
    create_machine,
)

CFG = {
    "id": "m",
    "initial": "a",
    "states": {"a": {"on": {"GO": "#m.b"}}, "b": {}},
}


def main() -> int:
    results = []

    # 1 & 2: dict shapes, both strict modes
    for strict in (False, True):
        i = SyncInterpreter(create_machine(CFG, logic=MachineLogic()), strict=strict)
        i.start()
        for ev in ({"type": None}, {"type": 123}, {"no_type": 1}):
            try:
                i.send(ev)  # type: ignore[arg-type]
                print(f"[strict={strict} ev={ev}] FAIL: accepted")
                results.append(False)
            except InvalidEventError as exc:
                print(f"[strict={strict} ev={ev}] OK: {type(exc).__name__}: {exc}")
                results.append(True)
            except Exception as exc:  # noqa: BLE001
                print(f"[strict={strict} ev={ev}] FAIL: untyped {type(exc).__name__}: {exc}")
                results.append(False)
        i.stop()

    # 3: non-event objects
    i2 = SyncInterpreter(create_machine(CFG, logic=MachineLogic()))
    i2.start()
    for ev in (None, 123, b"B", ["GO"], object()):
        try:
            i2.send(ev)  # type: ignore[arg-type]
            print(f"[non-event {type(ev).__name__}] FAIL: accepted")
            results.append(False)
        except InvalidEventError as exc:
            print(f"[non-event {type(ev).__name__}] OK: {type(exc).__name__}: {exc}")
            results.append(True)
        except Exception as exc:  # noqa: BLE001
            print(f"[non-event {type(ev).__name__}] FAIL: untyped {type(exc).__name__}: {exc}")
            results.append(False)
    i2.stop()

    # 4 & 5: class hierarchy
    ok_xstate = issubclass(InvalidEventError, XStateMachineError)
    ok_typeerror = issubclass(InvalidEventError, TypeError)
    print(f"[hierarchy] subclass of XStateMachineError={ok_xstate}, of TypeError={ok_typeerror}")
    results.append(ok_xstate)
    results.append(ok_typeerror)

    n_ok = sum(results)
    print(f"\n{n_ok}/{len(results)} criteria passed")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
