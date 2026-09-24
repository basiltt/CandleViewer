"""P4 (#221): parked scheduled_sends re-emitted until start() consumes them.

Checks: (a) restore -> re-persist without start() keeps the deadline;
(b) restore -> start() -> persist does NOT emit it twice (parked + armed);
(c) remaining_ms is verbatim (no time charged) across N re-persists;
(d) sync engine parity.

STANDALONE: stdlib + xstate_statemachine only.
"""
import asyncio
import json
import sys

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock

ARM = {"type": "raise", "params": {"event": "LATE", "delay": 60000, "id": "d"}}
CFG = {
    "id": "p",
    "initial": "a",
    "states": {"a": {"entry": [ARM], "on": {"LATE": "b"}}, "b": {}},
}


def _mk():
    return create_machine(CFG, logic=MachineLogic())


def _sends(snap):
    return snap.get("scheduled_sends") or []


def _fmt(recs):
    return [(r.get("type"), round(float(r.get("remaining_ms", -1)), 1)) for r in recs]


async def _async():
    clock = SimulatedClock()
    i = await Interpreter(_mk(), clock=clock).start()
    await clock.increment(1000)
    snap = json.dumps(i.get_persisted_snapshot())
    await i.stop()
    print("  live armed          :", _fmt(_sends(json.loads(snap))))

    # (a) restore -> re-persist WITHOUT start(), repeatedly
    blob = snap
    for n in range(3):
        j = Interpreter.from_snapshot(blob, _mk(), clock=SimulatedClock())
        blob = json.dumps(j.get_persisted_snapshot())
        print(f"  re-persist #{n + 1} (no start):", _fmt(_sends(json.loads(blob))))

    # (b) restore -> start() -> persist: parked + armed double-count?
    c2 = SimulatedClock()
    k = Interpreter.from_snapshot(blob, _mk(), clock=c2)
    await k.start()
    after = _fmt(_sends(k.get_persisted_snapshot()))
    print("  after start()       :", after, "<-- one entry expected")
    # does it fire exactly once?
    fired = []
    k.subscribe(lambda s: fired.append(s.value))
    await c2.increment(60000)
    await asyncio.sleep(0)
    print("  value after deadline:", k.value, "transitions:", len(fired))
    await k.stop()
    return len(after)


def _sync():
    clock = SimulatedClock()
    s = SyncInterpreter(_mk(), clock=clock).start()
    clock.increment(1000)
    blob = json.dumps(s.get_persisted_snapshot())
    s.stop()
    print("  live armed          :", _fmt(_sends(json.loads(blob))))
    for n in range(3):
        j = SyncInterpreter.from_snapshot(blob, _mk(), clock=SimulatedClock())
        blob = json.dumps(j.get_persisted_snapshot())
        print(f"  re-persist #{n + 1} (no start):", _fmt(_sends(json.loads(blob))))
    c2 = SimulatedClock()
    k = SyncInterpreter.from_snapshot(blob, _mk(), clock=c2).start()
    after = _fmt(_sends(k.get_persisted_snapshot()))
    print("  after start()       :", after)
    c2.increment(60000)
    k.tick()
    print("  value after deadline:", k.value)
    k.stop()
    return len(after)


def main():
    print("ASYNC")
    a = asyncio.run(_async())
    print("SYNC")
    s = _sync()
    print("VERDICT:", "NO DOUBLE-EMIT" if a == 1 and s == 1 else f"DOUBLE-EMIT a={a} s={s}")


if __name__ == "__main__":
    sys.exit(main())
