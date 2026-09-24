"""u5 (@c78ce99) -- STANDALONE. Concurrency load under the #212 rule.

L1  200 machines x a 1 ms `raise(delay=)` ping-pong for 10 s: under the
    new rule none may trip; CPU must be bounded by the CLOCK (beats per
    machine ~= elapsed/period, not a spin), and process CPU time must
    stay well under (wall x cores).
L2  100 concurrent `start()`s on a chart whose initial descent has
    `always` cycles + a descent-time `raise` (#215): must all settle,
    bounded, no watchdog trip.
L3  200 v3 snapshots with armed `scheduled_sends` restored CONCURRENTLY:
    every timer must re-arm and fire exactly once.

Reductions are recorded in the JSON. Watchdogs: a timeout IS the result.

Run: python u5_concurrency_load.py   (exit 1 == defect)
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
import time
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)

N_PINGPONG = 200
PINGPONG_S = 10.0
PERIOD_MS = 1
N_STARTS = 100
N_RESTORES = 200


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


class Drops(PluginBase):
    def __init__(self):
        self.chain = 0

    def on_event_dropped(self, interpreter, event, reason):  # noqa: ANN001
        if reason == "chain_budget":
            self.chain += 1


def logic(kind):
    if kind == "def":

        def tick(i, ctx, e, ad):  # noqa: ANN001
            ctx["n"] = ctx.get("n", 0) + 1

        return MachineLogic(actions={"tick": tick})

    async def atick(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    return MachineLogic(actions={"tick": atick})


PING = {
    "id": "u5", "initial": "a", "maxIterations": 8, "context": {"n": 0},
    "states": {
        "a": {"entry": [{"type": "raise",
                         "params": {"event": "PING", "delay": PERIOD_MS}}],
              "on": {"PING": "b"}, "exit": ["tick"]},
        "b": {"entry": [{"type": "raise",
                         "params": {"event": "PING", "delay": PERIOD_MS}}],
              "on": {"PING": "a"}, "exit": ["tick"]},
    },
}

DESCENT = {
    "id": "u5d", "initial": "s0", "maxIterations": 25, "context": {"n": 0},
    "states": {
        "s0": {"entry": [{"type": "raise", "params": {"event": "GO"}},
                         "tick"],
               "always": [{"target": "s1"}], "on": {"GO": "s2"}},
        "s1": {"always": [{"target": "s2"}]},
        "s2": {"entry": ["tick"]},
    },
}

ARMED = {
    "id": "u5r", "initial": "arm", "context": {"n": 0},
    "states": {
        "arm": {"entry": [{"type": "raise",
                           "params": {"event": "PING", "delay": 120}}],
                "on": {"PING": "fired"}},
        "fired": {"entry": ["tick"], "type": "final"},
    },
}


async def l1_pingpong() -> Dict[str, Any]:
    import psutil

    proc = psutil.Process()
    interps: List[Any] = []
    drops: List[Drops] = []
    for k in range(N_PINGPONG):
        kind = "def" if k % 2 == 0 else "async def"
        m = create_machine(copy.deepcopy(PING), logic=logic(kind))
        i = Interpreter(m)
        d = Drops()
        i.use(d)
        drops.append(d)
        interps.append(i)
    c0 = proc.cpu_times()
    t0 = time.perf_counter()
    await asyncio.gather(*(i.start() for i in interps))
    await asyncio.sleep(PINGPONG_S)
    wall = time.perf_counter() - t0
    c1 = proc.cpu_times()
    cpu = (c1.user - c0.user) + (c1.system - c0.system)
    beats = [i.context.get("n", 0) for i in interps]
    errs = [str(i.last_error) for i in interps if i.last_error is not None]
    await asyncio.gather(*(i.stop() for i in interps),
                         return_exceptions=True)
    ideal = PINGPONG_S * 1000.0 / PERIOD_MS
    out = {
        "machines": N_PINGPONG, "period_ms": PERIOD_MS, "run_s": PINGPONG_S,
        "wall_s": round(wall, 2), "cpu_s": round(cpu, 2),
        "cpu_over_wall": round(cpu / wall, 2),
        "cores": os.cpu_count(),
        "chain_trips": sum(d.chain for d in drops),
        "beats_min": min(beats), "beats_max": max(beats),
        "beats_mean": round(sum(beats) / len(beats), 1),
        "clock_ideal_beats": ideal,
        "last_errors": errs[:3], "n_last_errors": len(errs),
    }
    if out["chain_trips"]:
        out["fail"] = ("a delayed ping-pong tripped the chain budget -- "
                       "#212 says it is a periodic process")
    elif out["beats_min"] == 0:
        out["fail"] = "at least one heartbeat never beat"
    elif out["beats_max"] > ideal * 3:
        out["fail"] = (f"beats {out['beats_max']} far exceed the clock's "
                       f"{ideal} -- work is not paced by the period")
    return out


async def l2_descent_starts() -> Dict[str, Any]:
    interps = []
    for k in range(N_STARTS):
        kind = "def" if k % 2 == 0 else "async def"
        m = create_machine(copy.deepcopy(DESCENT), logic=logic(kind))
        interps.append(Interpreter(m))
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(
            asyncio.gather(*(i.start() for i in interps)), timeout=25.0)
        timed_out = False
    except asyncio.TimeoutError:
        timed_out = True
    wall = time.perf_counter() - t0
    states = sorted({tuple(sorted(i.current_state_ids)) for i in interps})
    ns = sorted({i.context.get("n", 0) for i in interps})
    await asyncio.gather(*(i.stop() for i in interps), return_exceptions=True)
    out = {"starts": N_STARTS, "wall_s": round(wall, 2),
           "watchdog_s": 25.0, "timed_out": timed_out,
           "distinct_configurations": [list(s) for s in states],
           "distinct_n": ns}
    if timed_out:
        out["fail"] = "start() descent-settle did not converge under 100 concurrent starts"
    elif len(states) != 1 or len(ns) != 1:
        out["fail"] = f"non-deterministic descent across starts: {states} / {ns}"
    return out


async def l3_restore_200() -> Dict[str, Any]:
    blobs: List[str] = []
    kinds: List[str] = []
    for k in range(N_RESTORES):
        kind = "def" if k % 2 == 0 else "async def"
        m = create_machine(copy.deepcopy(ARMED), logic=logic(kind))
        i = Interpreter(m)
        await i.start()
        snap = i.get_persisted_snapshot()
        blob = snap if isinstance(snap, str) else json.dumps(snap, default=str)
        await i.stop()
        blobs.append(blob)
        kinds.append(kind)
    armed = sum(1 for b in blobs
                if json.loads(b).get("scheduled_sends"))
    restored = []
    for blob, kind in zip(blobs, kinds):
        m = create_machine(copy.deepcopy(ARMED), logic=logic(kind))
        restored.append(Interpreter.from_snapshot(blob, m))
    t0 = time.perf_counter()
    await asyncio.gather(*(r.start() for r in restored))
    await asyncio.sleep(0.6)
    fired = sum(1 for r in restored if "u5r.fired" in r.current_state_ids)
    ns = [r.context.get("n", 0) for r in restored]
    await asyncio.gather(*(r.stop() for r in restored),
                         return_exceptions=True)
    out = {"restores": N_RESTORES, "blobs_with_armed_record": armed,
           "fired": fired, "wall_s": round(time.perf_counter() - t0, 2),
           "n_values": sorted(set(ns))}
    if armed != N_RESTORES:
        out["fail"] = f"only {armed}/{N_RESTORES} blobs carried the armed record"
    elif fired != N_RESTORES:
        out["fail"] = f"only {fired}/{N_RESTORES} restored timers fired"
    elif set(ns) != {1}:
        out["fail"] = f"restored timer did not fire exactly once: {sorted(set(ns))}"
    return out


async def main() -> int:
    res: Dict[str, Any] = {
        "L1_pingpong_200x10s": await l1_pingpong(),
        "L2_descent_100_starts": await l2_descent_starts(),
        "L3_restore_200_v3": await l3_restore_200(),
    }
    bad = [k for k, v in res.items() if "fail" in v]
    res["failing_cells"] = bad
    res["verdict"] = "DEFECT" if bad else "CLEAN"
    emit("u5_concurrency_load", res)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
