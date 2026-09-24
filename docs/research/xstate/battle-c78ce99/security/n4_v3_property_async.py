"""STANDALONE: v3 round-trip property on the ASYNC engine (#213).

>=300 random machines with an armed delayed self-send at a random
remaining delay; snapshot mid-window, restore, assert the send re-arms
and fires no earlier than the persisted `remaining_ms`.
"""

import asyncio
import json
import random
import sys
import time

from xstate_statemachine import create_machine, Interpreter


def cfg(mid, delay_ms):
    return {
        "id": mid, "initial": "a", "context": {},
        "states": {
            "a": {
                "entry": [{"type": "raise",
                           "params": {"event": "PONG", "delay": delay_ms}}],
                "on": {"PONG": {"target": "b"}},
            },
            "b": {},
        },
    }


async def one(i, rng):
    delay = rng.choice([60, 120, 200, 300])
    hold = rng.uniform(0.0, delay / 2000.0)
    m = create_machine(cfg("p%d" % i, delay))
    it = await Interpreter(m).start()
    await asyncio.sleep(hold)
    snap = json.loads(it.get_snapshot())
    await it.stop()
    ss = snap.get("scheduled_sends") or []
    if len(ss) != 1:
        return ("no_record", delay, len(ss))
    rem = float(ss[0]["remaining_ms"])
    if not (0 < rem <= delay + 5):
        return ("bad_remaining", delay, rem)
    it2 = await Interpreter.from_snapshot(json.dumps(snap), m).start()
    t0 = time.perf_counter()
    deadline = t0 + delay / 1000.0 * 3 + 0.5
    while time.perf_counter() < deadline:
        if "p%d.b" % i in it2.current_state_ids:
            break
        await asyncio.sleep(0.005)
    el = (time.perf_counter() - t0) * 1000.0
    fired = "p%d.b" % i in it2.current_state_ids
    await it2.stop()
    if not fired:
        return ("never_fired", delay, rem)
    if el < rem - 25:
        return ("fired_early", rem, el)
    return ("ok", rem, el)


async def main(n):
    rng = random.Random(99)
    tally = {}
    bad = []
    for i in range(n):
        r = await one(i, rng)
        tally[r[0]] = tally.get(r[0], 0) + 1
        if r[0] != "ok" and len(bad) < 8:
            bad.append(r)
    print("v3 async roundtrip n=%d %s" % (n, tally), flush=True)
    for b in bad:
        print("  ", b, flush=True)


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 300))
