"""P5 (#222): chain-trip latch semantics.

Checks: sticky across benign events; chain_trips monotonic; one trip counted
once; clear_chain_error(); survives stop(); persisted in the snapshot?;
restored by from_snapshot?; both engines.

STANDALONE: stdlib + xstate_statemachine only.
"""
import asyncio
import json
import sys

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

# A zero-delay raise loop: self-fed work inside ONE step -> maxIterations.
LOOP = {"type": "raise", "params": {"event": "SPIN"}}
CFG = {
    "id": "t",
    "initial": "idle",
    "maxIterations": 20,
    "states": {
        "idle": {"on": {"BOOM": "spin", "BENIGN": "idle"}},
        "spin": {"entry": [LOOP], "on": {"SPIN": {"target": "spin", "actions": [LOOP]}, "CALM": "idle"}},
    },
}


class Spy(PluginBase):
    def __init__(self):
        self.hits = []

    def on_chain_budget_exceeded(self, i, error, event):
        self.hits.append((type(error).__name__, getattr(event, "type", "")))


def _mk():
    return create_machine(CFG, logic=MachineLogic())


def _snap_has(blob):
    d = json.loads(blob)
    return [k for k in d if "chain" in k.lower()]


async def _async():
    spy = Spy()
    i = await Interpreter(_mk()).use(spy).start()
    print("  initial trips/latch :", i.chain_trips, i.last_chain_error)
    await i.send("BOOM")
    await asyncio.sleep(0.1)
    t1, l1 = i.chain_trips, type(i.last_chain_error).__name__
    print("  after BOOM          :", t1, l1, "plugin hits:", len(spy.hits))
    await i.send("CALM")
    await i.send("BENIGN")
    await asyncio.sleep(0.05)
    print("  after benign events :", i.chain_trips, type(i.last_chain_error).__name__,
          "| last_error:", type(i.last_error).__name__)
    blob = json.dumps(i.get_persisted_snapshot())
    print("  snapshot chain keys :", _snap_has(blob))
    i.clear_chain_error()
    print("  after clear()       :", i.chain_trips, i.last_chain_error)
    # second trip increments
    await i.send("BOOM")
    await asyncio.sleep(0.1)
    print("  after 2nd BOOM      :", i.chain_trips, type(i.last_chain_error).__name__,
          "| plugin hits:", len(spy.hits))
    trips_before_stop = i.chain_trips
    await i.stop()
    print("  after stop()        :", i.chain_trips, type(i.last_chain_error).__name__)
    j = Interpreter.from_snapshot(blob, _mk())
    print("  restored interpreter:", j.chain_trips, j.last_chain_error)
    return trips_before_stop


def _sync():
    spy = Spy()
    s = SyncInterpreter(_mk()).use(spy).start()
    s.send("BOOM")
    print("  after BOOM          :", s.chain_trips, type(s.last_chain_error).__name__,
          "plugin hits:", len(spy.hits))
    s.send("CALM")
    s.send("BENIGN")
    print("  after benign events :", s.chain_trips, type(s.last_chain_error).__name__,
          "| last_error:", type(s.last_error).__name__)
    blob = json.dumps(s.get_persisted_snapshot())
    print("  snapshot chain keys :", _snap_has(blob))
    s.send("BOOM")
    print("  after 2nd BOOM      :", s.chain_trips, "plugin hits:", len(spy.hits))
    n = s.chain_trips
    s.stop()
    print("  after stop()        :", s.chain_trips, type(s.last_chain_error).__name__)
    j = SyncInterpreter.from_snapshot(blob, _mk())
    print("  restored interpreter:", j.chain_trips, j.last_chain_error)
    return n


def main():
    print("ASYNC")
    a = asyncio.run(_async())
    print("SYNC")
    s = _sync()
    print(f"VERDICT: async trips={a} sync trips={s} (2 each = one per BOOM)")


if __name__ == "__main__":
    sys.exit(main())
