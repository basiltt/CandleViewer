"""R5-09 repro: the settle budget is reset per DRAIN, not per macrostep.

`SyncInterpreter._process_event_queue` zeroes `_settle_iterations` once, at
the start of the drain (`sync_interpreter.py:622-625`). Two independent
events delivered in one `send_events([...])` batch therefore share a single
`maxIterations` allowance: the second event inherits the first's spend and
trips `RunawayChainError` even though each, alone, settles well within
budget.

Control: the SAME two events sent one at a time both complete.

Exits 1 while the defect is present, 0 once fixed.
Stdlib + xstate_statemachine only.
"""

import logging
import sys

from xstate_statemachine import SyncInterpreter, create_machine

N = 40  # hops per chain; each event needs 40 of a 50 budget
LIMIT = 50


def cfg():
    states = {"idle": {"on": {"GO": "s0", "GO2": "u0"}}}
    for k in range(N):
        states[f"s{k}"] = {"always": f"s{k + 1}"}
    states[f"s{N}"] = {"on": {"GO2": "u0"}}
    for k in range(N):
        states[f"u{k}"] = {"always": f"u{k + 1}"}
    states[f"u{N}"] = {}
    return {
        "id": "L",
        "initial": "idle",
        "maxIterations": LIMIT,
        "states": states,
    }


def drive(batched: bool):
    i = SyncInterpreter(create_machine(cfg())).start()
    if batched:
        i.send_events(["GO", "GO2"])
    else:
        i.send("GO")
        i.send("GO2")
    out = (
        i.value,
        i.last_transition_ok,
        type(i.last_error).__name__ if i.last_error else None,
    )
    i.stop()
    return out


def main() -> int:
    seq_value, seq_ok, seq_err = drive(batched=False)
    bat_value, bat_ok, bat_err = drive(batched=True)

    print("OBSERVED:")
    print("  maxIterations                :", LIMIT, "| hops per event:", N)
    print("  sequential send(GO); send(GO2):")
    print("     value                     :", seq_value)
    print("     last_transition_ok        :", seq_ok, "| last_error:", seq_err)
    print("  batched send_events([GO,GO2]):")
    print("     value                     :", bat_value)
    print("     last_transition_ok        :", bat_ok, "| last_error:", bat_err)
    print("EXPECTED:")
    print("  the settle budget is per macrostep, so both routes reach")
    print("  'u%d' with last_transition_ok=True and last_error=None" % N)

    broken = bat_value != seq_value or not bat_ok or bat_err is not None
    if broken:
        print(
            "RESULT: FAIL - the second event in the batch inherited the "
            "first event's settle spend"
        )
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    sys.exit(main())
