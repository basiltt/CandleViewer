"""Verify #161 on cec108b: dict-event validation beyond 'type'.

Acceptance criteria (issue #161 + CHANGELOG "#161" bullet):
  A) send({"type": "GO"}) with only 'type' still transitions normally
     (not a regression -- the minimal valid form must still work).
  B) A dict event with a non-str key raises InvalidEventError (documented
     "mapping form requires ... str keys").
  C) send({"type": 123}) (non-str type in dict form) raises
     InvalidEventError.
  D) send({"type": ""}) (empty-str type in dict form) raises
     InvalidEventError.
  E) send({}) (dict without 'type' key) raises InvalidEventError.
  F) The full original hostile-shape sweep (non-dict shapes) still all
     raise InvalidEventError (no regression from the #161 dict-path change).
"""
from __future__ import annotations

import sys

from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
from xstate_statemachine.exceptions import InvalidEventError

CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}


def fresh():
    m = create_machine(CFG, logic=MachineLogic())
    return SyncInterpreter(m).start()


def criterion_A_minimal_dict_still_works() -> bool:
    interp = fresh()
    interp.send({"type": "GO"})
    ok = "m.b" in interp.current_state_ids
    print(f"  [A] send({{'type': 'GO'}}) still transitions: {ok}")
    return ok


def criterion_B_non_str_key() -> bool:
    interp = fresh()
    try:
        interp.send({"type": "GO", 1: "x"})
        print("  [B] FAIL: non-str key accepted")
        return False
    except InvalidEventError:
        print("  [B] PASS: non-str key raises InvalidEventError")
        return True


def criterion_C_non_str_type_in_dict() -> bool:
    interp = fresh()
    try:
        interp.send({"type": 123})
        print("  [C] FAIL: non-str type in dict accepted")
        return False
    except InvalidEventError:
        print("  [C] PASS: non-str type in dict raises InvalidEventError")
        return True


def criterion_D_empty_type_in_dict() -> bool:
    interp = fresh()
    try:
        interp.send({"type": ""})
        print("  [D] FAIL: empty-str type in dict accepted")
        return False
    except InvalidEventError:
        print("  [D] PASS: empty-str type raises InvalidEventError")
        return True


def criterion_E_missing_type_key() -> bool:
    interp = fresh()
    try:
        interp.send({})
        print("  [E] FAIL: dict without 'type' accepted")
        return False
    except InvalidEventError:
        print("  [E] PASS: dict without 'type' raises InvalidEventError")
        return True


def criterion_F_hostile_sweep_no_regression() -> bool:
    hostile = [None, 123, 1.5, b"GO", ["GO"], object(), True, float("nan")]
    all_ok = True
    for h in hostile:
        interp = fresh()
        try:
            interp.send(h)
            all_ok = False
            print(f"  [F] FAIL: {h!r} did not raise")
        except InvalidEventError:
            pass
        except Exception as e:  # noqa: BLE001
            all_ok = False
            print(f"  [F] FAIL: {h!r} raised uncontrolled {type(e).__name__}")
    print(f"  [F] hostile-shape sweep (non-dict) still all raise: {all_ok}")
    return all_ok


def main() -> int:
    results = [
        criterion_A_minimal_dict_still_works(),
        criterion_B_non_str_key(),
        criterion_C_non_str_type_in_dict(),
        criterion_D_empty_type_in_dict(),
        criterion_E_missing_type_key(),
        criterion_F_hostile_sweep_no_regression(),
    ]
    ok = all(results)
    print("OVERALL:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


sys.exit(main())
