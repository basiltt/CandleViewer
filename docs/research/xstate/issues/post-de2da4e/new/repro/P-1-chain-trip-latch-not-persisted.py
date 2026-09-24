"""STANDALONE repro -- P-1: the #222 chain-trip latch is process-local.

`chain_trips` and `last_chain_error` are NOT snapshot fields, so a
restart-from-snapshot comes back reporting `chain_trips == 0` and
`last_chain_error is None` on a machine that provably discarded work in
the previous process. The evidence that a runaway chain was cut exists
only for the lifetime of the object that cut it.

Library @ de2da4e (unreleased 0.8.1; __version__ still reports 0.8.0).
stdlib + xstate_statemachine only. Every helper inlined. Run from ANY cwd.

Exit 1 == DEFECT REPRODUCED (latch present live, erased across restore).
"""

import asyncio
import json
import sys

from xstate_statemachine import create_machine, Interpreter, SyncInterpreter
from xstate_statemachine.actions import raise_ as raise_action
from xstate_statemachine.exceptions import RunawayChainError
from xstate_statemachine.machine_logic import MachineLogic

# A self-raising spin state with a small chain budget: sending GO trips
# the runaway-chain guard, which is exactly the #222 supervisor signal.
CONFIG = {
    "id": "p1",
    "initial": "a",
    "maxIterations": 3,
    "states": {
        "a": {
            "entry": [raise_action({"type": "GO"})],
            "on": {
                "GO": {"target": "a", "reenter": True},
                "CALM": "b",
            },
        },
        "b": {},
    },
}

SNAPSHOT_KEYS = ("chain_trips", "last_chain_error")


def _machine():
    return create_machine(dict(CONFIG), logic=MachineLogic())


def _trip_sync(machine):
    """Drive a real chain trip on the sync engine and snapshot afterwards."""
    interp = SyncInterpreter(machine)
    try:
        interp.start()
    except RunawayChainError:
        pass  # the entry raise_ can trip during start()
    try:
        interp.send("GO")
    except RunawayChainError:
        pass
    live = (interp.chain_trips, type(interp.last_chain_error).__name__
            if interp.last_chain_error is not None else None)
    blob = json.loads(interp.get_snapshot())
    interp.stop()
    return live, blob


async def _trip_async(machine):
    """Same trip on the async engine -- the latch is reported via the API."""
    interp = Interpreter(machine)
    try:
        await asyncio.wait_for(interp.start(), timeout=10.0)
    except RunawayChainError:
        pass
    await interp.send("GO")
    await asyncio.sleep(0.15)
    live = (interp.chain_trips, type(interp.last_chain_error).__name__
            if interp.last_chain_error is not None else None)
    blob = json.loads(interp.get_snapshot())
    await interp.stop()
    return live, blob


def _restored_view(cls, machine, blob):
    interp = cls.from_snapshot(json.dumps(blob), machine)
    return (
        interp.chain_trips,
        type(interp.last_chain_error).__name__
        if interp.last_chain_error is not None
        else None,
    )


async def main():
    print("P-1 -- the #222 chain-trip latch across a snapshot round-trip\n")

    m_sync = _machine()
    live_sync, blob_sync = _trip_sync(m_sync)
    keys_sync = [k for k in SNAPSHOT_KEYS if k in blob_sync]
    rest_sync = _restored_view(SyncInterpreter, m_sync, blob_sync)

    m_async = _machine()
    live_async, blob_async = await _trip_async(m_async)
    keys_async = [k for k in SNAPSHOT_KEYS if k in blob_async]
    rest_async = _restored_view(Interpreter, m_async, blob_async)

    print(f"  sync   live (trips, latch)     : {live_sync}")
    print(f"  sync   snapshot keys present   : {keys_sync}")
    print(f"  sync   restored (trips, latch) : {rest_sync}")
    print()
    print(f"  async  live (trips, latch)     : {live_async}")
    print(f"  async  snapshot keys present   : {keys_async}")
    print(f"  async  restored (trips, latch) : {rest_async}")

    print()
    tripped = live_sync[0] >= 1 and live_sync[1] is not None and live_async[0] >= 1
    no_keys = keys_sync == [] and keys_async == []
    erased = rest_sync == (0, None) and rest_async == (0, None)
    print(f"a real chain trip happened, both engines           : {tripped}")
    print(f"neither key appears in the v3 envelope             : {no_keys}")
    print(f"restore reports a clean machine (0, None)          : {erased}")

    reproduced = tripped and no_keys and erased
    print(f"\nREPRODUCED: {reproduced}")
    return 1 if reproduced else 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(asyncio.wait_for(main(), timeout=60.0)))
    except asyncio.TimeoutError:
        print("WATCHDOG: hung")
        sys.exit(2)
