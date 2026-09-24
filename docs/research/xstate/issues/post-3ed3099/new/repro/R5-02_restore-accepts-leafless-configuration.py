"""R5-02 repro: `from_snapshot()` performs no configuration-legality check.
A snapshot whose `configuration` list has been truncated to the machine root
(ancestors only, no leaf) is accepted, restores with `status="running"` and
zero active leaves, and is permanently inert — while the still-correct
`state_ids` field sitting in the same blob is never consulted.

Stdlib + xstate_statemachine only. Exits 1 while present, 0 once fixed.
"""

import json
import sys

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine
from xstate_statemachine.exceptions import XStateMachineError

CFG = {
    "id": "ord",
    "initial": "working",
    "context": {"filled": 0},
    "states": {
        "working": {"on": {"FILL": "filled"}},
        "filled": {},
    },
}


def build():
    return create_machine(CFG, logic=MachineLogic())


def main() -> int:
    live = SyncInterpreter(build()).start()
    snap = live.get_persisted_snapshot()
    good_cfg = list(snap["configuration"])
    good_ids = list(snap["state_ids"])

    # Simulate a partial/truncated durable write: list elements lost, JSON
    # still well-formed, `machine_hash` intact, `state_ids` untouched.
    snap["configuration"] = [x for x in good_cfg if x == "ord"]
    blob = json.dumps(snap)

    print("OBSERVED:")
    print("  good configuration        :", good_cfg)
    print("  good state_ids            :", good_ids)
    print("  tampered configuration    :", snap["configuration"])
    print("  intact state_ids in blob  :", snap["state_ids"])

    try:
        restored = SyncInterpreter.from_snapshot(blob, build()).start()
    except XStateMachineError as exc:
        print("  from_snapshot             : refused with", type(exc).__name__)
        print("RESULT: PASS")
        return 0

    ids = sorted(restored.current_state_ids)
    status = restored.status
    receipt = restored.send("FILL")
    ids_after = sorted(restored.current_state_ids)

    print("  from_snapshot             : ACCEPTED")
    print("  restored current_state_ids:", ids)
    print("  restored status           :", status)
    print("  restored error            :", restored.error)
    print("  FILL receipt              :", receipt)
    print("  state ids after FILL      :", ids_after)

    print("EXPECTED:")
    print("  from_snapshot() raises SnapshotCorruptError (an XStateMachineError):")
    print("  a 'running' configuration with zero atomic states is not a legal")
    print("  SCXML configuration; alternatively fall back to the intact")
    print("  state_ids ['ord.working'].")

    if not ids and status == "running":
        print("RESULT: FAIL - restored into a running machine with no active leaf")
        return 1
    print("RESULT: PASS")
    return 0


sys.exit(main())
