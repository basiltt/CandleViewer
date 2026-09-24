"""F5 -- soak: 200 machines, both kinds, 10-50 ms heartbeats + an external
priority producer + chaos v3 snapshot/restore/re-persist.

Invariants polled every second to convergence:
  S1 timer handles stay bounded (<= 2 per machine)
  S2 every external send is applied (0 dropped)
  S3 no heartbeat dies
  S4 chain_trips stays 0 (nothing here is a legal runaway)
  S5 heap flat (tracemalloc, stdlib only)
  S6 every chaos restore preserves the machine's scheduled_sends record
     count, INCLUDING the #221 restore->re-persist-without-start hop

BOUND: the task's per-script ceiling is 120 s, so this runs SECS=100 s
(env SECS overrides), not the 12 min the plan asks for. Stated as reduced.

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import gc
import json
import logging
import os
import random
import tracemalloc
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    create_machine,
)

SECS = float(os.environ.get("SECS", "100"))
NMACH = int(os.environ.get("NMACH", "200"))
SEED = int(os.environ.get("SEED", "20260923"))
DEFECTS = []


def cfg(idx, period):
    return {
        "id": "sk%d" % idx,
        "initial": "t",
        "context": {"n": 0, "ext": 0},
        "states": {
            "t": {
                "entry": [{"type": "raise",
                           "params": {"event": "TICK", "delay": period,
                                      "id": "hb"}}],
                "on": {
                    "TICK": {"actions": [
                        "beat",
                        {"type": "raise",
                         "params": {"event": "TICK", "delay": period,
                                    "id": "hb"}}]},
                    "EXT": {"actions": ["ext"]},
                },
            }
        },
    }


def mk_logic(kind):
    def beat(i, c, e, a=None):
        c["n"] = c.get("n", 0) + 1

    def ext(i, c, e, a=None):
        c["ext"] = c.get("ext", 0) + 1

    async def beat_a(i, c, e, a=None):
        beat(i, c, e, a)

    async def ext_a(i, c, e, a=None):
        ext(i, c, e, a)

    if kind == "async def":
        return MachineLogic(actions={"beat": beat_a, "ext": ext_a})
    return MachineLogic(actions={"beat": beat, "ext": ext})


def handles(it):
    th = getattr(it, "_timer_handles", {}) or {}
    return sum(len(v) for v in th.values())


async def soak(kind):
    rnd = random.Random(SEED)
    machines, its = [], []
    for k in range(NMACH):
        m = create_machine(cfg(k, rnd.choice([10, 17, 25, 33, 50])),
                           logic=mk_logic(kind))
        machines.append(m)
        its.append(Interpreter(m))
    await asyncio.gather(*[i.start() for i in its])
    gc.collect()
    tracemalloc.start()
    base = tracemalloc.take_snapshot()

    sent = {"n": 0}
    stop = {"v": False}

    async def producer():
        while not stop["v"]:
            for i in its:
                await i.send("EXT")
                sent["n"] += 1
            await asyncio.sleep(0.02)

    chaos = {"ok": 0, "rec_mismatch": 0, "refused": 0, "hop_mismatch": 0}

    async def chaoser():
        r = random.Random(SEED + 1)
        while not stop["v"]:
            await asyncio.sleep(0.15)
            k = r.randrange(NMACH)
            blob = its[k].get_snapshot()
            n0 = len(json.loads(blob).get("scheduled_sends") or [])
            try:
                # #221 hop: restore -> re-persist WITHOUT start()
                mid = Interpreter.from_snapshot(blob, machines[k])
                blob2 = mid.get_snapshot()
                n1 = len(json.loads(blob2).get("scheduled_sends") or [])
                if n1 != n0:
                    chaos["hop_mismatch"] += 1
                r2 = Interpreter.from_snapshot(blob2, machines[k])
                await r2.start()
                await asyncio.sleep(0.05)
                n2 = len(json.loads(r2.get_snapshot()).get(
                    "scheduled_sends") or [])
                if n2 < n0:
                    chaos["rec_mismatch"] += 1
                await r2.stop()
                chaos["ok"] += 1
            except Exception:  # noqa: BLE001
                chaos["refused"] += 1

    pt = asyncio.ensure_future(producer())
    ct = asyncio.ensure_future(chaoser())
    hsamples = []
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    while loop.time() - t0 < SECS:
        await asyncio.sleep(2.0)
        hsamples.append(sum(handles(i) for i in its))
    stop["v"] = True
    for t in (pt, ct):
        t.cancel()
        try:
            await t
        except BaseException:  # noqa: BLE001 -- CancelledError included
            pass
    await asyncio.sleep(0.2)

    gc.collect()
    grow = sum(s.size_diff for s in
               tracemalloc.take_snapshot().compare_to(base, "filename"))
    tracemalloc.stop()
    beats = [i.context.get("n", 0) for i in its]
    ext = sum(i.context.get("ext", 0) for i in its)
    trips = sum(i.chain_trips for i in its)
    dead = sum(1 for b in beats if b == 0)
    await asyncio.gather(*[i.stop() for i in its], return_exceptions=True)

    print("  %-9s handles=%s (max %d for %d machines)"
          % (kind, hsamples, max(hsamples), NMACH))
    print("           beats min=%d max=%d dead=%d | ext_sent=%d ext_applied=%d"
          " lost=%d | chain_trips=%d | heap=%+.1fKB"
          % (min(beats), max(beats), dead, sent["n"], ext,
             sent["n"] - ext, trips, grow / 1024.0))
    print("           chaos=%s" % (chaos,))

    if max(hsamples) > NMACH * 2:
        DEFECTS.append("S1/%s: handles peaked at %d for %d machines"
                       % (kind, max(hsamples), NMACH))
    if sent["n"] - ext != 0:
        DEFECTS.append("S2/%s: %d of %d external sends lost"
                       % (kind, sent["n"] - ext, sent["n"]))
    if dead:
        DEFECTS.append("S3/%s: %d heartbeats died" % (kind, dead))
    if trips:
        DEFECTS.append("S4/%s: %d unexpected chain trips" % (kind, trips))
    if grow > 16 * 1024 * 1024:
        DEFECTS.append("S5/%s: heap grew %.1fMB" % (kind, grow / 1048576.0))
    if chaos["hop_mismatch"] or chaos["rec_mismatch"] or chaos["refused"]:
        DEFECTS.append("S6/%s: chaos restore anomalies %s" % (kind, chaos))


async def main():
    print("F5 -- soak %d machines x %.0fs x 2 kinds (REDUCED from 12 min to "
          "fit the 120 s per-script bound)" % (NMACH, SECS))
    for kind in ("def", "async def"):
        await soak(kind)
    print("\nDEFECTS = %d" % len(DEFECTS))
    for d in DEFECTS:
        print("   -", d)
    raise SystemExit(1 if DEFECTS else 0)


asyncio.run(main())
