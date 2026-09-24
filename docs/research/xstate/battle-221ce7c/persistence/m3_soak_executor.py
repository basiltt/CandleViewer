# -*- coding: utf-8 -*-
"""M3 - reduced soak: many order-like machines with PARALLEL regions and
plain-`def` services (which #149 routes through `service_executor`), plus
chaos snapshot/restore. Snapshots are taken only at quiescence.

Run: python m3_soak_executor.py [seconds] [n_machines]
"""
from __future__ import annotations

import asyncio
import gc
import json
import logging
import random
import sys
import time

import psutil

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

logging.disable(logging.CRITICAL)

SPEC = {
    "id": "ord",
    "initial": "draft",
    "context": {"filled": 0, "risk": "unknown", "acks": 0},
    "onUnhandled": "defer",
    "states": {
        "draft": {"on": {"SUBMIT": "submitted"}},
        "submitted": {
            "type": "parallel",
            "states": {
                "exchange": {
                    "initial": "acking",
                    "states": {
                        "acking": {
                            "invoke": {"id": "ack", "src": "ack_svc",
                                       "onDone": {"target": "working",
                                                  "actions": ["store_ack"]},
                                       "onError": "failed"},
                        },
                        "working": {"on": {"FILL": {"actions": ["add_fill"]},
                                           "DONE": "complete"}},
                        "complete": {"type": "final"},
                        "failed": {"type": "final"},
                    },
                },
                "risk": {
                    "initial": "checking",
                    "states": {
                        "checking": {"on": {"RISK_OK": "passed", "RISK_BAD": "held"}},
                        "passed": {"type": "final"},
                        "held": {"on": {"RECHECK": "checking"}},
                    },
                },
            },
            "on": {"CANCEL": "cancelled"},
        },
        "cancelled": {"type": "final"},
    },
}


def ack_svc(interpreter, context, event):  # plain def -> service_executor (#149)
    time.sleep(0.001)
    return {"ack": 1}


def store_ack(i, c, e, a):
    c["acks"] = c.get("acks", 0) + 1


def add_fill(i, c, e, a):
    c["filled"] = c.get("filled", 0) + int(getattr(e, "payload", {}).get("n", 1))


def build():
    return create_machine(
        SPEC,
        logic=MachineLogic(actions={"store_ack": store_ack, "add_fill": add_fill},
                           services={"ack_svc": ack_svc}),
    )


EVENTS = ["SUBMIT", "RISK_OK", "RISK_BAD", "FILL", "DONE", "RECHECK", "NOPE"]

C = {"cycles": 0, "events": 0, "snapshots": 0, "restores": 0,
     "raw": [], "mismatch": [], "midstep": 0, "typed": 0}


def canon(b):
    b = dict(b)
    b.pop("taken_at", None)
    return json.dumps(b, sort_keys=True, default=str)


async def worker(budget: float, rng: random.Random, chaos_every: float):
    i = Interpreter(build(), clock=SimulatedClock())
    await i.start()
    last_chaos = time.monotonic()
    end = time.monotonic() + budget
    while time.monotonic() < end:
        C["cycles"] += 1
        ev = rng.choice(EVENTS)
        try:
            if ev == "FILL":
                await i.send(ev, n=rng.randint(1, 3), wait=True)
            else:
                await i.send(ev, wait=True)
            C["events"] += 1
        except Exception as e:  # noqa: BLE001
            C["raw"].append(f"send {type(e).__name__}: {e}")
        await asyncio.sleep(0)  # quiescence
        if time.monotonic() - last_chaos >= chaos_every:
            last_chaos = time.monotonic()
            try:
                blob = i.get_persisted_snapshot()
                C["snapshots"] += 1
            except Exception as e:  # noqa: BLE001
                name = type(e).__name__
                if name == "SnapshotMidStepError":
                    C["midstep"] += 1
                else:
                    C["raw"].append(f"snap {name}: {e}")
                continue
            if blob["status"] != "running":
                await i.stop()
                i = Interpreter(build(), clock=SimulatedClock())
                await i.start()
                continue
            try:
                i2 = Interpreter.from_snapshot(json.dumps(blob), build(),
                                               clock=SimulatedClock())
                await i2.start()
                await asyncio.sleep(0)
                b2 = i2.get_persisted_snapshot()
                C["restores"] += 1
                if canon(blob) != canon(b2):
                    C["mismatch"].append(canon(blob)[:200])
                await i.stop()
                i = i2
            except Exception as e:  # noqa: BLE001
                C["raw"].append(f"restore {type(e).__name__}: {e}")
    await i.stop()


async def main():
    budget = float(sys.argv[1]) if len(sys.argv) > 1 else 180.0
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    print(f"soak budget          : {budget}s (REDUCED from the brief's 12 min)")
    print(f"concurrent machines  : {n}")
    proc = psutil.Process()
    gc.collect()
    rss0, obj0 = proc.memory_info().rss / 1e6, len(gc.get_objects())
    t0 = time.monotonic()
    await asyncio.gather(*[worker(budget, random.Random(1000 + k), 2.0)
                           for k in range(n)])
    gc.collect()
    rss1, obj1 = proc.memory_info().rss / 1e6, len(gc.get_objects())
    print(f"elapsed              : {time.monotonic() - t0:.1f}s")
    for k in ("cycles", "events", "snapshots", "restores", "midstep"):
        print(f"{k:21}: {C[k]}")
    print(f"raw exceptions       : {len(C['raw'])}   <- must be 0")
    for r in sorted(set(C["raw"]))[:6]:
        print("   -", r[:200])
    print(f"round-trip mismatch  : {len(C['mismatch'])}   <- must be 0")
    print(f"\nRSS   {rss0:.1f} MB -> {rss1:.1f} MB   objs {obj0} -> {obj1}")
    ok = not C["raw"] and not C["mismatch"]
    print("\nVERDICT:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
    asyncio.run(main())
