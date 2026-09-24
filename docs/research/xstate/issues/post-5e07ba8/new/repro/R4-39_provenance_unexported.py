"""R4-39: the event-provenance mechanism (is_system_event / system_event) is
documented only in the changelog, and both symbols are unexported from the
package's public API.

is_system_event is the single predicate behind `strict`, `onUnhandled` and
`"*"` wildcard semantics -- yet it is absent from __all__ (and so not
importable from the package root, only from the internal `events` submodule),
and has no guide page. system_event, described in the changelog as "the ONLY
way to produce" an engine event, is likewise unexported.

Exits 1 (defect present) while either symbol is missing from
xstate_statemachine.__all__ / cannot be imported from the package root.
Exits 0 once both are exported.
"""
import sys


def main() -> int:
    import xstate_statemachine as xsm

    all_list = getattr(xsm, "__all__", [])
    is_system_event_exported = "is_system_event" in all_list
    system_event_exported = "system_event" in all_list

    is_system_event_importable = hasattr(xsm, "is_system_event")
    system_event_importable = hasattr(xsm, "system_event")

    print("OBSERVED:")
    print(f"  'is_system_event' in xstate_statemachine.__all__ = {is_system_event_exported}")
    print(f"  'system_event' in xstate_statemachine.__all__    = {system_event_exported}")
    print(f"  hasattr(xsm, 'is_system_event')                  = {is_system_event_importable}")
    print(f"  hasattr(xsm, 'system_event')                     = {system_event_importable}")

    print(
        "\nEXPECTED: both 'is_system_event' and 'system_event' are part of "
        "the public API (__all__) and importable from the package root, "
        "with a guide page covering provenance / persist_event / "
        "restore_event"
    )

    defect_present = not (
        is_system_event_exported
        and system_event_exported
        and is_system_event_importable
        and system_event_importable
    )
    if defect_present:
        print("\nRESULT: undocumented/unexported provenance symbols -- defect present")
        return 1
    else:
        print("\nRESULT: symbols exported and importable -- fixed")
        return 0


if __name__ == "__main__":
    sys.exit(main())
