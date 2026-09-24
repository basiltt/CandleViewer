"""R4-26: create_machine() still mutates a duck-typed logic object even
after #92's fix.

factory.py's `_alias_logic_names` (factory.py:252-279) makes a defensive
shallow copy of each registry (`actions`, `guards`, `services`) before
aliasing -- but only when `final_logic` is an actual `MachineLogic`
instance (factory.py:216-220): `owned_logic = copy.copy(final_logic) if
isinstance(final_logic, MachineLogic) else final_logic`. A duck-typed logic
object (any object exposing the three registry dicts, which the library's
own comments call "supported... by contract") takes the `else` branch and
is used AS-IS, so `_alias_logic_names`'s `setattr(logic, attr, owned)`
(factory.py:279) writes straight back onto the CALLER's object.

EXPECTED (per #92 / the library's own stated invariant, "create_machine is
a pure function of its inputs again"): neither supported input shape is
mutated by create_machine().
OBSERVED: the MachineLogic path is fixed, but the duck-typed path still
replaces the caller's `.actions` dict object and mutates its keys.

Exits 1 while the defect is present, 0 once fixed.
"""
from __future__ import annotations

from xstate_statemachine import MachineLogic, create_machine

CFG = {"id": "m", "initial": "a", "states": {"a": {"entry": ["storeUser"]}}}


class DuckLogic:
    """Documented as supported: "duck-typed by contract"."""

    def __init__(self):
        self.actions = {"store_user": lambda i, c, e, a: None}
        self.guards = {}
        self.services = {}


def main() -> int:
    d = DuckLogic()
    before_keys = sorted(d.actions)
    before_obj = d.actions

    create_machine(CFG, logic=d)

    replaced = d.actions is not before_obj
    mutated_keys = sorted(d.actions) != before_keys

    # Control case: the MachineLogic path should be unaffected (per #92).
    ml = MachineLogic(actions={"store_user": lambda i, c, e, a: None})
    ml_keys_before = sorted(ml.actions)
    create_machine(CFG, logic=ml)
    ml_unchanged = sorted(ml.actions) == ml_keys_before

    print(f"duck-typed caller's .actions object REPLACED: {replaced}")
    print(f"duck-typed caller's keys mutated: {mutated_keys} -> {sorted(d.actions)}")
    print(f"MachineLogic caller keys unchanged (control): {ml_unchanged}")

    defect_present = replaced or mutated_keys
    print(
        "\nOBSERVED:",
        "create_machine() mutated the duck-typed caller's object in place"
        if defect_present
        else "duck-typed object was left untouched",
    )
    print(
        "EXPECTED: create_machine() must not mutate either supported input "
        "shape (MachineLogic instance or duck-typed object)"
    )
    print("RESULT:", "FAIL - defect present" if defect_present else "PASS")
    return 1 if defect_present else 0


if __name__ == "__main__":
    raise SystemExit(main())
