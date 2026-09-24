"""R5-20 repro: send() accepts a mapping like {"type": "GO"} without routing
any keys beyond "type" through InvalidEventError validation -- every other
hostile shape (None, 123, bytes, list, object(), bool, nan) raises correctly,
but a dict is accepted and transitions the machine.

Exits 1 while the defect is present (as far as documenting the gap), 0 once
InvalidEventError validates dict-shaped events beyond the "type" key too.
Stdlib + xstate_statemachine only.
"""
import sys

from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
from xstate_statemachine.exceptions import InvalidEventError

CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}


def main() -> int:
    m = create_machine(CFG, logic=MachineLogic())

    hostile = [None, 123, 1.5, b"GO", ["GO"], object(), True, float("nan")]
    results = []
    for h in hostile:
        interp = SyncInterpreter(m).start()
        try:
            interp.send(h)
            results.append((repr(h), "NO ERROR RAISED"))
        except InvalidEventError:
            results.append((repr(h), "InvalidEventError OK"))
        except Exception as e:  # noqa: BLE001
            results.append((repr(h), f"UNCONTROLLED {type(e).__name__}"))

    # The mapping form: only "type" is validated; everything else passes.
    dict_interp = SyncInterpreter(m).start()
    dict_transitioned = False
    dict_raised = None
    try:
        dict_interp.send({"type": "GO"})
        dict_transitioned = "m.b" in dict_interp.current_state_ids
    except Exception as e:  # noqa: BLE001
        dict_raised = type(e).__name__

    print("OBSERVED (non-dict hostile shapes):")
    for h, r in results:
        print(f"  {h:20s} -> {r}")
    bad = [r for _, r in results if r != "InvalidEventError OK"]
    print(f"  BAD_COUNT (non-dict): {len(bad)}")
    print()
    print("OBSERVED (dict-shaped event):")
    print(f"  send({{'type': 'GO'}}) raised : {dict_raised}")
    print(f"  transitioned to m.b           : {dict_transitioned}")

    print("EXPECTED:")
    print("  every hostile shape either raises InvalidEventError, or (for the")
    print("  documented mapping form) the mapping's non-'type' keys are also")
    print("  validated as a payload dict -- the sweep should not have a single")
    print("  unvalidated input class")

    fail = len(bad) > 0 or (dict_raised is None and dict_transitioned)
    if fail:
        print("RESULT: FAIL - dict-shaped event bypasses InvalidEventError beyond 'type'")
        return 1
    print("RESULT: PASS")
    return 0


sys.exit(main())
