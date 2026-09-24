# -*- coding: utf-8 -*-
"""P1 (#221) -- parked + armed `scheduled_sends` across restore->persist->
restore->start chains.  STANDALONE (stdlib + xstate_statemachine).

Property (>=300 cases x 2 service kinds): a machine arms 1..3 delayed
self-sends, is snapshotted mid-delay, then the blob is passed through a
RANDOM chain of 1..4 "journal compaction" hops (from_snapshot -> immediate
get_persisted_snapshot, NO start()) before a final restore that DOES
start().  The deadline must survive every hop verbatim, then fire exactly
once after the remaining delay -- not early, not twice, not never.

Also: mixed shape -- restore, start, arm MORE sends, re-persist: both the
re-armed (now live) and the newly armed records must appear exactly once
(no duplication of the parked list after start() consumed it).
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import sys
import time

from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine

KIND = os.environ.get("XS_SVC", "async")


def S(b):
    return b if isinstance(b, str) else json.dumps(b)


def J(b):
    return J(b) if isinstance(b, (str, bytes)) else b

N = int(os.environ.get("XS_N", "300"))
SEED = int(os.environ.get("XS_SEED", "1121"))


def spec(n_states, sends):
    st = {}
    entry = [{"type": "raise", "params": {"event": f"T{k}", "delay": d,
                                          "id": f"s{k}"}}
             for k, d in enumerate(sends)]
    st["a"] = {"entry": entry + ["mark"],
               "on": {f"T{k}": {"actions": ["fire"]} for k in range(len(sends))}}
    for j in range(1, n_states):
        st[f"z{j}"] = {}
    return {"id": "pk", "initial": "a", "context": {"fired": [], "marks": 0},
            "states": st}


def build(cfg):
    def mark(i, c, e, a):
        c["marks"] += 1

    def fire(i, c, e, a):
        c["fired"].append(e.type)

    return create_machine(json.loads(json.dumps(cfg)),
                          logic=MachineLogic(actions={"mark": mark,
                                                      "fire": fire}))


async def one(rnd):
    sends = [rnd.choice([40, 60, 90, 130]) for _ in range(rnd.randint(1, 3))]
    cfg = spec(rnd.randint(1, 3), sends)
    i = Interpreter(build(cfg))
    await i.start()
    hold = rnd.uniform(0.005, 0.020)
    await asyncio.sleep(hold)
    blob = i.get_persisted_snapshot()
    await i.stop()
    recs0 = J(blob)["scheduled_sends"]
    if len(recs0) != len(sends):
        return f"hop0 records {len(recs0)} != {len(sends)}"
    # journal-compaction hops: restore -> re-persist, never started
    hops = rnd.randint(1, 4)
    for h in range(hops):
        j = Interpreter.from_snapshot(S(blob), build(cfg))
        blob = j.get_persisted_snapshot()
        r = J(blob)["scheduled_sends"]
        if len(r) != len(sends):
            return f"hop{h+1} records {len(r)} != {len(sends)}"
        if sorted(x.get("send_id") for x in r) != sorted(
                x.get("send_id") for x in recs0):
            return f"hop{h+1} send_ids drifted"
        if any(abs(float(x["remaining_ms"]) - float(y["remaining_ms"])) > 1e-6
               for x, y in zip(sorted(r, key=lambda z: z["send_id"]),
                               sorted(recs0, key=lambda z: z["send_id"]))):
            return f"hop{h+1} remaining_ms drifted"
    rem = max(float(x["remaining_ms"]) for x in recs0)
    mn = min(float(x["remaining_ms"]) for x in recs0)
    k = Interpreter.from_snapshot(S(blob), build(cfg))
    await k.start()
    if k.context["fired"]:
        return "fired at start()"
    await asyncio.sleep(mn / 1000.0 * 0.4)
    early = list(k.context["fired"])
    deadline = time.perf_counter() + rem / 1000.0 + 1.5
    while time.perf_counter() < deadline and len(k.context["fired"]) < len(sends):
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.15)
    got = list(k.context["fired"])
    await k.stop()
    if early:
        return f"fired early {early}"
    if sorted(got) != sorted(f"T{x}" for x in range(len(sends))):
        return f"fired {got} want {len(sends)} distinct"
    # re-persist AFTER everything fired -> must be empty, not resurrect
    return None


async def part_b():
    """After start() consumed the parked list, re-persisting must not
    duplicate or resurrect it."""
    cfg = spec(1, [500])
    i = Interpreter(build(cfg))
    await i.start()
    await asyncio.sleep(0.02)
    b1 = i.get_persisted_snapshot()
    await i.stop()
    j = Interpreter.from_snapshot(S(b1), build(cfg))
    n_before = len(J(j.get_persisted_snapshot())["scheduled_sends"])
    await j.start()
    n_after = len(J(j.get_persisted_snapshot())["scheduled_sends"])
    b3 = j.get_persisted_snapshot()
    n_again = len(J(b3)["scheduled_sends"])
    await j.stop()
    return {"before_start": n_before, "after_start": n_after,
            "re_persist": n_again,
            "ok": n_before == 1 and n_after == 1 and n_again == 1}


async def part_c():
    """Sync engine: same restore->re-persist-without-start hop."""
    cfg = spec(1, [500])
    i = SyncInterpreter(build(cfg))
    i.start()
    time.sleep(0.02)
    b = i.get_persisted_snapshot()
    i.stop()
    n0 = len(J(b)["scheduled_sends"])
    j = SyncInterpreter.from_snapshot(S(b), build(cfg))
    n1 = len(J(j.get_persisted_snapshot())["scheduled_sends"])
    return {"sync_hop0": n0, "sync_hop1": n1, "ok": n0 == 1 and n1 == 1}


async def main():
    rnd = random.Random(SEED)
    fails = []
    for _ in range(N):
        r = await one(rnd)
        if r:
            fails.append(r)
            if len(fails) > 5:
                break
    b = await part_b()
    c = await part_c()
    ok = not fails and b["ok"] and c["ok"]
    print(json.dumps({"kind": KIND, "N": N, "fails": fails[:5],
                      "n_fail": len(fails), "part_b": b, "part_c": c,
                      "VERDICT": "PASS" if ok else "FAIL"}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
