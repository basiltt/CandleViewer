"""Verify #162 on cec108b: v1 (no ``kind``) persisted event records must
default to USER provenance (system=False) unless the type is the genuine
engine init sentinel ("___xstate_statemachine_init___" / "___xstate..."
prefix), not merely name-shaped like an engine event (e.g. "after.hours",
"xstate.custom").

Exercises:
  - CHANGELOG claim: "v1 pending events are user events" (#162) -- only the
    init sentinel keeps system provenance.
  - Acceptance criterion 1: repro exits 0 (re-run original repro directly).
  - Acceptance criterion 2 (equivalent inline): v1 record w/ engine-shaped
    type restores system=False.
  - Control: a genuine "___xstate_statemachine_init___" v1 record still
    restores system=True (engine's own sentinel not de-classified).

Exit 0 only if all checks pass.
"""
import sys

from xstate_statemachine.events import restore_event

FAILURES = []


def check(label, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        FAILURES.append(label)


def main() -> int:
    print("=== #162 v1 provenance laundering verification ===")

    cases = [
        ("after.hours", False),
        ("xstate.custom", False),
        ("done.review", False),
        ("___xstate_statemachine_init___", True),
    ]
    for etype, expected_system in cases:
        rec = {"type": etype, "payload": {"note": "v1 record, no kind"}}
        restored = restore_event(rec)
        system = getattr(restored, "system", None)
        print(f"  v1 record type={etype!r:32s} -> Event(system={system})")
        check(
            f"type={etype!r} restores system={expected_system}",
            system is expected_system,
        )

    return 0 if not FAILURES else 1


if __name__ == "__main__":
    sys.exit(main())
