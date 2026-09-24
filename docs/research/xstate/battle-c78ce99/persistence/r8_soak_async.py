# -*- coding: utf-8 -*-
"""R8 -- 200-machine soak on the ASYNC service lane with an external
priority producer and chaos snapshot/restore at quiescence.

Derived from `m3_soak_executor.py` (which used plain-`def` services, the lane
round 6 measured) with three changes: the service is `async def`, each worker
also runs an external `send(priority=True)` producer (#180: an external
priority send must never be charged to the chain budget, i.e. 0 dropped), and
the dropped count is a failure condition.
Original m3 header follows.
Machines have PARALLEL regions; chaos snapshot/restore at quiescence only.
Run: python r8_soak_async.py [seconds] [n_machines]
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
from xstate_statemachine.plugins import PluginBase

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


async def ack_svc(interpreter, context, event):  # ASYNC lane (#179 budget path)
    await asyncio.sleep(0.001)
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

C = {"cycles": 0, "events": 0, "snapshots": 0, "restores": 0, "ext_sent": 0,
     "ext_dropped": 0, "drop_reasons": {},
     "raw": [], "mismatch": [], "midstep": 0, "typed": 0}


def canon(b):
    b = dict(b)
    b.pop("taken_at", None)
    return json.dumps(b, sort_keys=True, default=str)


class DropWatch(PluginBase):
    """Counts every dropped event, by reason -- the #180 observable."""

    def on_event_dropped(self, interp, event, reason):  # noqa: ANN001
        C["ext_dropped"] += 1
        C["drop_reasons"][reason] = C["drop_reasons"].get(reason, 0) + 1


def _new(rng=None):
    i = Interpreter(build(), clock=SimulatedClock())
    i.use(DropWatch())
    return i


async def worker(budget: float, rng: random.Random, chaos_every: float):
    i = _new()
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
        # 📤 external priority producer: send(priority=True) from OUTSIDE
        #    the machine must NEVER be charged to the chain budget (#180).
        for _ in range(3):
            try:
                await i.send("NOPE", priority=True)
                C["ext_sent"] += 1
            except Exception as e:  # noqa: BLE001
                C["raw"].append(f"ext {type(e).__name__}: {e}")
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
                i = _new()
                await i.start()
                continue
            try:
                i2 = Interpreter.from_snapshot(json.dumps(blob), build(),
                                               clock=SimulatedClock())
                i2.use(DropWatch())
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
    print("services             : ASYNC def (the #179 charged-completion lane)")
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
    for k in ("cycles", "events", "snapshots", "restores", "midstep",
              "ext_sent", "ext_dropped"):
        print(f"{k:21}: {C[k]}")
    print(f"raw exceptions       : {len(C['raw'])}   <- must be 0")
    for r in sorted(set(C["raw"]))[:6]:
        print("   -", r[:200])
    print(f"round-trip mismatch  : {len(C['mismatch'])}   <- must be 0")
    print(f"drop reasons         : {C['drop_reasons']}   <- must be {{}}")
    print(f"\nRSS   {rss0:.1f} MB -> {rss1:.1f} MB   objs {obj0} -> {obj1}")
    ok = not C["raw"] and not C["mismatch"] and not C["ext_dropped"]
    print("\nVERDICT:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
    asyncio.run(main())
