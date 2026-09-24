"""R4-38: a self-referential (aliased-cycle) config dict causes a
RecursionError instead of a typed InvalidConfigError.

StateNode.__init__ recurses into config["states"] with no cycle detection.
A hand-built Python dict that contains itself as one of its own child
state configs (impossible to express in JSON, but easy to construct in
Python) blows the interpreter stack instead of raising a typed,
catchable XStateMachineError.

Exits 1 (defect present) if a RecursionError escapes create_machine().
Exits 0 once a typed InvalidConfigError is raised instead.
"""
import sys

from xstate_statemachine import MachineLogic, XStateMachineError, create_machine


def main() -> int:
    a: dict = {"initial": "x", "states": {}}
    a["states"]["x"] = a  # aliased cycle: "x"'s config IS "a" itself

    cfg = {"id": "m", "initial": "a", "states": {"a": a}}

    try:
        create_machine(cfg, logic=MachineLogic())
        print("OBSERVED: create_machine() returned normally (unexpected)")
        return 1
    except XStateMachineError as exc:
        print(f"OBSERVED: typed {type(exc).__name__}: {exc}")
        print("\nEXPECTED: a typed InvalidConfigError naming the cyclic state")
        print("RESULT: typed error raised -- fixed")
        return 0
    except RecursionError as exc:
        print(f"OBSERVED: RecursionError: {exc}")
        print("\nEXPECTED: a typed InvalidConfigError naming the cyclic state, "
              "not a bare RecursionError")
        print("RESULT: untyped RecursionError -- defect present")
        return 1


if __name__ == "__main__":
    sys.exit(main())
