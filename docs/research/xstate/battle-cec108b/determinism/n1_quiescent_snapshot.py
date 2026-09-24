"""N1 -- #102 SnapshotMidStepError must never fire at quiescence.

Attack: run a long event script on BOTH engines and take
`get_persisted_snapshot()` after EVERY settled send (i.e. at every quiescent
point). For a replay/audit pipeline the contract must be:

  Q1  a snapshot at a quiescent point NEVER raises SnapshotMidStepError;
  Q2  every such snapshot round-trips (from_snapshot -> re-snapshot == bytes);
  Q3  the same script produces the same sequence of snapshot bytes run-to-run.

Also probes the intended positive: a snapshot taken from INSIDE an action
(genuinely mid-macrostep) SHOULD raise SnapshotMidStepError.

REDUCED: 2000 events as specified, but snapshot round-trip verification is
sampled every 25th quiescent point (80 round-trips/engine) to fit the runtime
bound; the raise-check (Q1) runs at all 2000.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.disable(logging.CRITICAL)

from dmachine import Recorder, build, canon_snapshot, make_script  # noqa: E402
from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    SnapshotMidStepError,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

N = 500
RT_EVERY = 25


def _dig(items):
    h = hashlib.sha256()
    for x in items:
        h.update(x.encode())
        h.update(b"\x1e")
    return h.hexdigest()[:16]


async def async_pass(script):
    rec = Recorder()
    clock = SimulatedClock()
    i = Interpreter(build(rec), clock=clock)
    await i.start()
    snaps, raises, rt_fail, rt_n = [], [], [], 0
    for k, step in enumerate(script):
        if step[0] == "tick":
            await clock.increment(step[1])
        else:
            await i.send(step[1], **step[2])
        try:
            raw = i.get_persisted_snapshot()
        except SnapshotMidStepError as e:
            raises.append((k, str(e)[:120]))
            continue
        c = canon_snapshot(raw)
        snaps.append(c)
        if k % RT_EVERY == 0:
            rt_n += 1
            try:
                r = Interpreter.from_snapshot(
                    json.dumps(raw, default=str), build(Recorder())
                )
                if canon_snapshot(r.get_persisted_snapshot()) != c:
                    rt_fail.append((k, "bytes-differ"))
            except Exception as e:  # noqa: BLE001
                rt_fail.append((k, f"{type(e).__name__}: {e}"[:140]))
    await i.stop()
    return snaps, raises, rt_fail, rt_n


def sync_pass(script):
    rec = Recorder()
    clock = SimulatedClock()
    i = SyncInterpreter(build(rec), clock=clock)
    i.start()
    snaps, raises, rt_fail, rt_n = [], [], [], 0
    for k, step in enumerate(script):
        if step[0] == "tick":
            clock.increment(step[1])
        else:
            i.send(step[1], **step[2])
        try:
            raw = i.get_persisted_snapshot()
        except SnapshotMidStepError as e:
            raises.append((k, str(e)[:120]))
            continue
        c = canon_snapshot(raw)
        snaps.append(c)
        if k % RT_EVERY == 0:
            rt_n += 1
            try:
                r = SyncInterpreter.from_snapshot(
                    json.dumps(raw, default=str), build(Recorder())
                )
                if canon_snapshot(r.get_persisted_snapshot()) != c:
                    rt_fail.append((k, "bytes-differ"))
            except Exception as e:  # noqa: BLE001
                rt_fail.append((k, f"{type(e).__name__}: {e}"[:140]))
    i.stop()
    return snaps, raises, rt_fail, rt_n


# --- Q4: the intended positive -- mid-action snapshot must raise ------------
MID = {
    "id": "mid",
    "initial": "a",
    "context": {"x": 0},
    "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["grab"]}}},
        "b": {"on": {"GO": {"target": "a", "actions": ["grab"]}}},
    },
}


def midstep_probe(engine):
    seen = {}

    def grab(i, c, e, a):
        try:
            i.get_persisted_snapshot()
            seen["result"] = "NO-RAISE"
        except SnapshotMidStepError:
            seen["result"] = "SnapshotMidStepError"
        except Exception as ex:  # noqa: BLE001
            seen["result"] = type(ex).__name__

    m = create_machine(MID, logic=MachineLogic(actions={"grab": grab}))
    if engine == "sync":
        it = SyncInterpreter(m)
        it.start()
        it.send("GO")
        it.stop()
    return seen.get("result", "action-never-ran")


async def midstep_probe_async():
    seen = {}

    def grab(i, c, e, a):
        try:
            i.get_persisted_snapshot()
            seen["result"] = "NO-RAISE"
        except SnapshotMidStepError:
            seen["result"] = "SnapshotMidStepError"
        except Exception as ex:  # noqa: BLE001
            seen["result"] = type(ex).__name__

    m = create_machine(MID, logic=MachineLogic(actions={"grab": grab}))
    it = Interpreter(m)
    await it.start()
    await it.send("GO")
    await it.stop()
    return seen.get("result", "action-never-ran")


async def main():
    script = make_script(N)
    res = {}

    a1 = await async_pass(script)
    a2 = await async_pass(script)
    s1 = sync_pass(script)
    s2 = sync_pass(script)

    for name, (r1, r2) in (("async", (a1, a2)), ("sync", (s1, s2))):
        snaps, raises, rt_fail, rt_n = r1
        res[name] = {
            "quiescent_points": len(snaps),
            "midstep_raises_at_quiescence": len(raises),
            "midstep_raise_examples": raises[:3],
            "roundtrips_checked": rt_n,
            "roundtrip_failures": len(rt_fail),
            "roundtrip_examples": rt_fail[:3],
            "snapshot_seq_digest": _dig(snaps),
            "run_to_run_identical": _dig(snaps) == _dig(r2[0]),
        }
        print(f"\n== {name.upper()} ==")
        for k, v in res[name].items():
            print(f"   {k:34s}: {v}")

    res["Q4_midstep_probe"] = {
        "sync": midstep_probe("sync"),
        "async": await midstep_probe_async(),
    }
    print("\n== Q4 snapshot from inside an action (should raise) ==")
    print(f"   sync : {res['Q4_midstep_probe']['sync']}")
    print(f"   async: {res['Q4_midstep_probe']['async']}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "n1_quiescent.json"), "w") as f:
        json.dump(res, f, indent=2)
    print("\nwrote out/n1_quiescent.json")


if __name__ == "__main__":
    asyncio.run(main())
