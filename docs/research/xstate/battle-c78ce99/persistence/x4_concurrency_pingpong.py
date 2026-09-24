# -*- coding: utf-8 -*-
"""X4 -- #212 concurrency: 200 machines x 1 ms `raise(delay=)` ping-pong.

STANDALONE (stdlib + xstate_statemachine + psutil-free CPU via os.times).
Neutral cwd.

  A  200 machines, 1 ms delayed self-raise ping-pong, REAL clock, N s.
     Under #212 this is a periodic process: it must run indefinitely, no
     `RunawayChainError`, every machine still beating at the end, and CPU
     bounded by the clock (not a spin).
  B  MIXED chain: a zero-delay `raise` cycle in the same chart MUST still
     trip `maxIterations`.
  C  Snapshot at quiescence during the ping-pong: scheduled_sends present,
     restore keeps beating.
"""
from __future__ import annotations

import asyncio
import json
import os
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import RunawayChainError
from xstate_statemachine.plugins import PluginBase

KIND = os.environ.get("XS_SVC", "async")
NM = int(os.environ.get("XS_NM", "200"))
SECS = float(os.environ.get("XS_SECS", "10"))


class Err(PluginBase):
    def __init__(self):
        self.errs = []
        self.dropped = []

    def on_event_dropped(self, i, e, reason):  # noqa: ANN001
        self.dropped.append(reason)


PING = {
    "id": "pp",
    "maxIterations": 12,
    "initial": "a",
    "context": {"beats": 0},
    "states": {
        "a": {"entry": [{"type": "raise", "params": {"event": "T", "delay": 1}},
                        "beat"],
              "on": {"T": "b"}},
        "b": {"entry": [{"type": "raise", "params": {"event": "T", "delay": 1}},
                        "beat"],
              "on": {"T": "a"}},
    },
}

MIXED = {
    "id": "mx",
    "maxIterations": 12,
    "initial": "a",
    "context": {"beats": 0},
    "states": {
        # zero-delay raise cycle -- pure within-step work, must trip
        "a": {"entry": [{"type": "raise", "params": {"event": "Z"}}, "beat"],
              "on": {"Z": "b"}},
        "b": {"entry": [{"type": "raise", "params": {"event": "Z"}}, "beat"],
              "on": {"Z": "a"}},
    },
}

MIXED2 = {
    "id": "mx2",
    "maxIterations": 12,
    "initial": "a",
    "context": {"beats": 0},
    "states": {
        # a 1 ms timer arms the state, and the state ALSO runs a zero-delay
        # cycle inside the step: the zero-delay half must still trip.
        "a": {"entry": [{"type": "raise", "params": {"event": "T", "delay": 1}},
                        {"type": "raise", "params": {"event": "Z"}}, "beat"],
              "on": {"Z": "b", "T": "a"}},
        "b": {"entry": [{"type": "raise", "params": {"event": "Z"}}, "beat"],
              "on": {"Z": "a"}},
    },
}


def build(spec):
    def beat(i, c, e, a):  # noqa: ANN001
        c["beats"] += 1

    async def s_async(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return 1

    def s_def(i, c, e):  # noqa: ANN001
        return 1

    return create_machine(
        json.loads(json.dumps(spec)),
        logic=MachineLogic(
            actions={"beat": beat},
            services={"s": s_async if KIND == "async" else s_def},
        ),
    )


def cpu() -> float:
    t = os.times()
    return t.user + t.system


async def part_a():
    print(f"=== A. {NM} machines x 1 ms ping-pong for {SECS}s (#212) ===")
    plugs = [Err() for _ in range(NM)]
    interps = []
    for k in range(NM):
        i = Interpreter(build(PING))
        i.use(plugs[k])
        interps.append(i)
    c0, w0 = cpu(), time.monotonic()
    await asyncio.gather(*(i.start() for i in interps))
    await asyncio.sleep(SECS / 2)
    mid = [i.context["beats"] for i in interps]
    await asyncio.sleep(SECS / 2)
    c1, w1 = cpu(), time.monotonic()
    end = [i.context["beats"] for i in interps]
    runaway = sum(
        1 for i in interps if isinstance(i.error, RunawayChainError)
    )
    statuses = {}
    for i in interps:
        statuses[i.status] = statuses.get(i.status, 0) + 1
    still = sum(1 for a, b in zip(mid, end) if b > a)
    budget = sum(p.dropped.count("chain_budget") for p in plugs)
    await asyncio.gather(*(i.stop() for i in interps if i.status == "running"))
    wall = w1 - w0
    print(f"   wall={wall:.1f}s cpu={c1 - c0:.1f}s  cpu/wall={(c1 - c0) / wall:.2f}")
    print(f"   beats: min={min(end)} med={sorted(end)[NM // 2]} max={max(end)}")
    print(f"   statuses={statuses} runaway={runaway} chain_budget_drops={budget}")
    print(f"   still beating in 2nd half: {still}/{NM}")
    ok = runaway == 0 and still == NM and statuses.get("running", 0) == NM
    print(f"   VERDICT #212 periodic-process = {'PASS' if ok else 'FAIL'}")


async def _trip(spec, label, secs=3.0):
    plug = Err()
    i = Interpreter(build(spec))
    i.use(plug)
    try:
        await i.start()
    except RunawayChainError:
        pass
    t0 = time.monotonic()
    while time.monotonic() - t0 < secs:
        await asyncio.sleep(0.05)
        if isinstance(i.error, RunawayChainError) or plug.dropped:
            break
    tripped = isinstance(i.error, RunawayChainError) or (
        "chain_budget" in plug.dropped
    )
    print(f"   {label}: beats={i.context['beats']} status={i.status} "
          f"error={type(i.error).__name__ if i.error else None} "
          f"drops={sorted(set(plug.dropped))} -> TRIPPED={tripped}")
    if i.status == "running":
        await i.stop()
    return tripped


async def part_b():
    print("\n=== B. zero-delay cycles must STILL trip ===")
    z = await _trip(MIXED, "pure zero-delay cycle   ")
    mx = await _trip(MIXED2, "mixed 1 ms + zero-delay ")
    print(f"   VERDICT zero-delay still bounded = {'PASS' if z and mx else 'FAIL'}")


async def part_c():
    print("\n=== C. snapshot/restore a live ping-pong ===")
    i = Interpreter(build(PING))
    await i.start()
    await asyncio.sleep(0.3)
    blob = None
    for _ in range(200):
        try:
            blob = i.get_snapshot()
            break
        except Exception:  # noqa: BLE001
            await asyncio.sleep(0.005)
    b1 = i.context["beats"]
    await i.stop()
    if blob is None:
        print("   could not snapshot at quiescence in 200 tries")
        return
    snap = json.loads(blob)
    ss = snap.get("scheduled_sends") or []
    print(f"   beats@snapshot={b1} scheduled_sends={[(r['type'], round(r['remaining_ms'], 2)) for r in ss]}")
    m2 = build(PING)
    i2 = Interpreter.from_snapshot(blob, m2)
    await i2.start()
    await asyncio.sleep(0.5)
    b2 = i2.context["beats"]
    st = i2.status
    if i2.status == "running":
        await i2.stop()
    print(f"   after restore + 0.5 s: beats={b2} (was {b1}) status={st}")
    print(f"   VERDICT heartbeat survives restore = "
          f"{'PASS' if b2 > b1 else 'FAIL'}")


async def main():
    print(f"X4 kind={KIND} NM={NM} SECS={SECS}")
    await part_a()
    await part_b()
    await part_c()


asyncio.run(main())
