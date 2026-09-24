"""R4-07 false-positive half: stale id() set + CPython address recycling.

Populate `_deferred_this_step` with ids of events the caller no longer holds,
then issue genuinely-handled sends and look for `deferred=True and changed=True`.
Public API only.
"""
import json
import logging

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

logging.disable(logging.CRITICAL)

CFG = {
    "id": "m",
    "initial": "a",
    "onUnhandled": "defer",
    "states": {"a": {"on": {"GO": "b"}}, "b": {"on": {"BACK": "a"}}},
}


def run(prefill, rounds):
    s = SyncInterpreter(create_machine(CFG, logic=MachineLogic())).start()
    # Phase 1 — fire-and-forget unhandled events: ids retained, objects freed.
    for _ in range(prefill):
        s.send("NOPE")
    stale = len(getattr(s, "_deferred_this_step", ()))

    # Phase 2 — genuinely handled sends; watch for a recycled-address collision.
    false_pos = 0
    checked = 0
    samples = []
    for _ in range(rounds):
        r = s.send("GO", wait=True)
        if r is not None:
            checked += 1
            if getattr(r, "deferred", False) and r.changed:
                false_pos += 1
                if len(samples) < 3:
                    samples.append(
                        {
                            "state_ids": sorted(r.state_ids)
                            if hasattr(r, "state_ids")
                            else None,
                            "changed": r.changed,
                            "deferred": r.deferred,
                            "error": repr(r.error),
                        }
                    )
        r2 = s.send("BACK", wait=True)
        if r2 is not None:
            checked += 1
            if getattr(r2, "deferred", False) and r2.changed:
                false_pos += 1
    return {
        "prefill_unhandled": prefill,
        "stale_ids_after_prefill": stale,
        "receipts_checked": checked,
        "false_positives_deferred_and_changed": false_pos,
        "samples": samples,
        "stale_ids_at_end": len(getattr(s, "_deferred_this_step", ())),
        "REPRO_false_positive": false_pos > 0,
    }


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "prefill_5000": run(5000, 3000),
                "prefill_0_control": run(0, 3000),
            },
            indent=1,
            default=str,
        )
    )
