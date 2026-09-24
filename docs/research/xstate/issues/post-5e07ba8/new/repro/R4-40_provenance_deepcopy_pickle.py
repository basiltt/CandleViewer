"""R4-40: engine provenance does not survive deepcopy or pickle.

system_event() marks an Event as engine-originated via an identity
sentinel (`_ENGINE_MARK = object()`, compared with `is`). copy.copy()
preserves this (shallow copy keeps the same sentinel object by
reference), but copy.deepcopy() and pickle both reconstruct a new
sentinel object, so identity comparison fails and provenance is silently
lost -- even though the codebase deep-copies event payloads in several
places, and a multiprocessing hand-off of an engine event relies on
pickle.

Exits 1 (defect present) while deepcopy or pickle loses provenance.
Exits 0 once provenance survives both (e.g. via __deepcopy__ / __reduce__).
"""
import copy
import pickle
import sys

from xstate_statemachine.events import Event, is_system_event, system_event


def main() -> int:
    ev = system_event("xstate.init")

    original_ok = is_system_event(ev)
    copy_ok = is_system_event(copy.copy(ev))
    deepcopy_ok = is_system_event(copy.deepcopy(ev))
    try:
        pickle_ok = is_system_event(pickle.loads(pickle.dumps(ev)))
        pickle_error = None
    except Exception as exc:  # noqa: BLE001
        pickle_ok = False
        pickle_error = f"{type(exc).__name__}: {exc}"

    print("OBSERVED:")
    print(f"  is_system_event(original)      = {original_ok}")
    print(f"  is_system_event(copy.copy)     = {copy_ok}")
    print(f"  is_system_event(copy.deepcopy) = {deepcopy_ok}")
    if pickle_error:
        print(f"  is_system_event(pickle roundtrip) = FAILED: {pickle_error}")
    else:
        print(f"  is_system_event(pickle roundtrip) = {pickle_ok}")

    print(
        "\nEXPECTED: provenance (is_system_event) survives copy.copy, "
        "copy.deepcopy, and a pickle round-trip -- an engine event should "
        "still read as engine-originated after crossing a process boundary "
        "or being deep-copied"
    )

    defect_present = not (original_ok and copy_ok and deepcopy_ok and pickle_ok)
    if defect_present:
        print("\nRESULT: provenance lost across deepcopy/pickle -- defect present")
        return 1
    else:
        print("\nRESULT: provenance preserved -- fixed")
        return 0


if __name__ == "__main__":
    sys.exit(main())
