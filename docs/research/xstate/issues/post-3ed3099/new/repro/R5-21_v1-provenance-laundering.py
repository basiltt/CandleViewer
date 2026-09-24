"""R5-21 repro: restore_event() re-derives provenance from the event NAME for
a v1 (no "kind") record, laundering an engine-shaped user event name (e.g.
"after.hours" or "xstate.custom") into Event(system=True) on restore, even
though it was originally ordinary user traffic.

Exits 1 while the defect is present, 0 once fixed.
Stdlib + xstate_statemachine only.
"""
import sys

from xstate_statemachine.events import restore_event

V1_RECORDS = [
    # A user chose this event name; it happens to start with an engine
    # prefix ("after."). No `kind` key exists in a v1 record.
    {"type": "after.hours", "payload": {"note": "user event, not a timer"}},
    {"type": "xstate.custom", "payload": {"note": "user event, not a system event"}},
    # Control: a genuine done event name, still correctly classed "event".
    {"type": "done.review", "payload": {"note": "user event named like a done event"}},
]


def main() -> int:
    print("OBSERVED:")
    laundered = []
    for rec in V1_RECORDS:
        restored = restore_event(rec)
        system = getattr(restored, "system", None)
        print(f"  v1 record type={rec['type']!r:20s} -> Event(system={system})")
        if system is True:
            laundered.append(rec["type"])

    print("EXPECTED:")
    print("  a v1 record for a genuine USER event must never restore with")
    print("  system=True purely because its name happens to share an engine")
    print("  prefix -- provenance should default to 'event' for v1 records")
    print("  whose origin cannot be proven, not 'system' by name-sniffing")

    if laundered:
        print(f"RESULT: FAIL - laundered to system=True: {laundered}")
        return 1
    print("RESULT: PASS")
    return 0


sys.exit(main())
