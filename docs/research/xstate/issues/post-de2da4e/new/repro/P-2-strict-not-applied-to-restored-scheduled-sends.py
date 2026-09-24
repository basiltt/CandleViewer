"""STANDALONE repro -- P-2: `strict` is NOT applied to restored
`scheduled_sends`, because `_rearm_restored_self_sends` bypasses
`_admit_restored`.

`from_snapshot` checks every restored `pending_events` record against
`strict` (#214, `base_interpreter.py:1935` -> `_admit_restored`). The
sibling list `scheduled_sends` is re-armed by
`_rearm_restored_self_sends` (`base_interpreter.py:1269`) with no such
check, so an undeclared event type parked in a snapshot is admitted on a
`strict: True` machine and delivered to the run loop.

Library @ de2da4e (unreleased 0.8.1; __version__ still reports 0.8.0).
stdlib + xstate_statemachine only. Every helper inlined. Run from ANY cwd.

Exit 1 == DEFECT REPRODUCED (the two restore lanes disagree).
"""

import asyncio
import copy
import json
import sys

from xstate_statemachine import create_machine, Interpreter, SyncInterpreter
from xstate_statemachine.machine_logic import MachineLogic

# `strict: True` -- the declaration rule this probe is about.
CONFIG = {
    "id": "p2",
    "initial": "a",
    "strict": True,
    "states": {
        "a": {"on": {"KNOWN": "b"}},
        "b": {},
    },
}

# A type the chart never declares. `strict` must refuse it from EVERY door.
UNDECLARED = {"type": "UNDECLARED_TYPO", "payload": {}, "kind": "event"}


def _machine():
    return create_machine(copy.deepcopy(CONFIG), logic=MachineLogic())


def _base_blob(machine):
    """A real, self-minted v3 snapshot -- no hand-forged envelope."""
    interp = SyncInterpreter(machine).start()
    blob = json.loads(interp.get_snapshot())
    interp.stop()
    return blob


def _sanity_send_is_refused(machine):
    """Control: the SAME type via send() is refused, so strict is really on."""
    interp = SyncInterpreter(machine).start()
    try:
        interp.send(UNDECLARED["type"])
        return False
    except Exception:  # noqa: BLE001 -- UnknownEventError
        return True
    finally:
        interp.stop()


def _lane_pending(machine, blob):
    """Lane A -- the record rides `pending_events` (goes via _admit_restored)."""
    b = copy.deepcopy(blob)
    b["pending_events"] = [dict(UNDECLARED)]
    b["scheduled_sends"] = []
    interp = SyncInterpreter.from_snapshot(json.dumps(b), machine)
    return len(list(interp.pending_events)), interp.last_error


def _lane_scheduled(machine, blob):
    """Lane B -- the SAME record rides `scheduled_sends`."""
    b = copy.deepcopy(blob)
    b["pending_events"] = []
    rec = dict(UNDECLARED)
    rec["remaining_ms"] = 1.0
    rec["send_id"] = "p2-probe"
    b["scheduled_sends"] = [rec]
    interp = SyncInterpreter.from_snapshot(json.dumps(b), machine)
    parked = len(interp._restored_self_sends)
    armed = interp._rearm_restored_self_sends()
    return parked, armed, interp.last_error


async def _lane_scheduled_async(machine, blob):
    """Lane B on the async engine, end to end: does the event reach the loop?"""
    b = copy.deepcopy(blob)
    b["pending_events"] = []
    rec = dict(UNDECLARED)
    rec["remaining_ms"] = 1.0
    rec["send_id"] = "p2-probe"
    b["scheduled_sends"] = [rec]
    interp = Interpreter.from_snapshot(json.dumps(b), machine)

    seen = []
    original = interp._process_event

    async def spy(event, *a, **k):  # observation only; library untouched
        seen.append(getattr(event, "type", event))
        return await original(event, *a, **k)

    interp._process_event = spy
    await asyncio.wait_for(interp.start(), timeout=10.0)
    await asyncio.sleep(0.20)
    await interp.stop()
    return UNDECLARED["type"] in seen


async def main():
    print("P-2 -- `strict: True`, the same undeclared record on the two restore lanes\n")

    machine = _machine()
    blob = _base_blob(machine)

    control = _sanity_send_is_refused(machine)
    print(f"  control  send()         -> refused: {control}")

    n_pending, err_a = _lane_pending(machine, blob)
    name_a = type(err_a).__name__ if err_a is not None else None
    print(f"  lane A   pending_events -> enqueued={n_pending}  last_error={name_a}")

    parked, armed, err_b = _lane_scheduled(machine, blob)
    name_b = type(err_b).__name__ if err_b is not None else None
    print(f"  lane B   scheduled_sends-> parked={parked} armed={armed}  last_error={name_b}")

    reached = await _lane_scheduled_async(machine, blob)
    print(f"  lane B   async engine   -> undeclared event reached the run loop: {reached}")

    print()
    a_refused = n_pending == 0 and err_a is not None
    b_admitted = armed == 1 and err_b is None
    print(f"strict is genuinely on (send refused)              : {control}")
    print(f"lane A refuses the undeclared type (#214, correct) : {a_refused}")
    print(f"lane B admits the SAME type under strict           : {b_admitted}")
    print(f"async engine delivers it to the run loop           : {reached}")

    reproduced = control and a_refused and b_admitted
    print(f"\nREPRODUCED: {reproduced}")
    return 1 if reproduced else 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(asyncio.wait_for(main(), timeout=60.0)))
    except asyncio.TimeoutError:
        print("WATCHDOG: hung")
        sys.exit(2)
