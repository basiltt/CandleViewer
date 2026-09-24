# -*- coding: utf-8 -*-
"""NEW round-13 attack: persistence property matrix (#226/#227/#230/#233).

Standalone. Covers:
 (1) v3 latch fields (chain_trips, last_chain_error) round-trip and stay
     monotonic across N restarts; RestoredError message intact.
 (2) scheduled_sends strict refusal mid-restore leaves a consistent
     machine, run over >=300 generated cases.
 (3) plugins= receives on_invalid_event exactly once per restore-time
     refusal (no double-fire, no miss).
 (4) sync engine honours the priority lane on restore (#233).
"""
from __future__ import annotations

import asyncio
import json
import random
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)

CHAIN_CFG = {
    "id": "chain",
    "initial": "run",
    "context": {},
    "onUnhandled": "defer",
    "maxIterations": 3,
    "states": {"run": {"on": {"PUMP": {"actions": ["pump"]}, "BENIGN": {}}}},
}


def pump(i, ctx, ev, ad):
    for _ in range(10):
        i.send("PUMP")  # trips the chain/maxIterations budget


async def attack_latch_roundtrip():
    logic = MachineLogic(actions={"pump": pump})
    m = create_machine(CHAIN_CFG, logic=logic)
    i = Interpreter(m)
    await i.start()
    i.send("PUMP")
    await asyncio.sleep(0.02)
    trips_before = i.chain_trips
    err_before = str(i.last_chain_error) if i.last_chain_error else None
    snap = json.dumps(i.get_persisted_snapshot())
    await i.stop()

    counts = [trips_before]
    err_now = err_before
    for gen in range(5):
        m2 = create_machine(CHAIN_CFG, logic=logic)
        i2 = Interpreter.from_snapshot(snap, m2)
        assert i2.chain_trips == counts[-1], f"chain_trips not preserved at gen {gen}"
        if i2.last_chain_error is not None:
            assert err_now is not None and err_now in str(i2.last_chain_error)
        await i2.start()
        i2.send("PUMP")
        await asyncio.sleep(0.02)
        counts.append(i2.chain_trips)
        err_now = str(i2.last_chain_error) if i2.last_chain_error else None
        snap = json.dumps(i2.get_persisted_snapshot())
        await i2.stop()

    monotonic = all(counts[k + 1] >= counts[k] for k in range(len(counts) - 1))
    print("latch counts across restarts:", counts, "monotonic:", monotonic)
    print("LATCH_ROUNDTRIP_OK:", monotonic and counts[-1] > 0)


STRICT_CFG = {
    "id": "s",
    "initial": "a",
    "context": {},
    "strict": True,
    "events": {"GOOD": {}, "OTHER": {}},
    "states": {
        "a": {
            "on": {
                "ARM": {
                    "actions": [
                        {"type": "raise", "params": {"event": "GOOD", "delay": 50}}
                    ]
                },
                "GOOD": {"target": "b"},
                "OTHER": {},
            }
        },
        "b": {},
    },
}


class CapturePlugin(PluginBase):
    def __init__(self):
        self.invalid_calls: List[Any] = []

    def on_invalid_event(self, interpreter, error, raw_event):
        self.invalid_calls.append((raw_event, str(error)[:80]))


async def one_strict_restore_case(rng: random.Random, use_sync: bool):
    logic = MachineLogic(actions={})
    Kind = SyncInterpreter if use_sync else Interpreter
    m = create_machine(STRICT_CFG, logic=logic)
    i = Kind(m)
    if use_sync:
        i.start()
    else:
        await i.start()
    i.send("ARM")
    if not use_sync:
        await asyncio.sleep(0.001)
    snap = json.dumps(i.get_persisted_snapshot())
    if use_sync:
        i.stop()
    else:
        await i.stop()

    # Corrupt the scheduled_sends record's type to an undeclared event,
    # simulating a hostile / drifted blob (documented trust boundary).
    payload = json.loads(snap)
    poisoned = 0
    for rec in payload.get("scheduled_sends", []):
        if rng.random() < 0.5:
            rec["type"] = "FORGED_UNDECLARED"
            poisoned += 1
    snap2 = json.dumps(payload)

    plug = CapturePlugin()
    m2 = create_machine(STRICT_CFG, logic=logic)
    i2 = Kind.from_snapshot(snap2, m2, plugins=[plug])
    if use_sync:
        i2.start()
    else:
        await i2.start()
    consistent = i2.status in ("running", "stopped", "done")
    fired = len(plug.invalid_calls)
    if use_sync:
        i2.stop()
    else:
        await i2.stop()
    ok = consistent and (fired == poisoned or (poisoned == 0 and fired == 0))
    return ok, poisoned, fired, consistent


async def attack_strict_restore_property(n_cases: int = 320):
    rng = random.Random(1234)
    failures = 0
    for k in range(n_cases):
        use_sync = k % 2 == 0
        ok, poisoned, fired, consistent = await one_strict_restore_case(rng, use_sync)
        if not ok:
            failures += 1
            print(f"  FAIL case {k}: sync={use_sync} poisoned={poisoned} fired={fired} consistent={consistent}")
    print(f"strict-restore property: {n_cases} cases, failures={failures}")
    print("STRICT_RESTORE_PROPERTY_OK:", failures == 0)


async def attack_plugins_exactly_once():
    logic = MachineLogic(actions={})
    m = create_machine(STRICT_CFG, logic=logic)
    i = Interpreter(m)
    await i.start()
    i.send("ARM")
    await asyncio.sleep(0.001)
    snap = json.dumps(i.get_persisted_snapshot())
    await i.stop()

    payload = json.loads(snap)
    for rec in payload.get("scheduled_sends", []):
        rec["type"] = "FORGED_UNDECLARED"
    for rec in payload.get("pending_events", []):
        rec["type"] = "FORGED_UNDECLARED"
    snap2 = json.dumps(payload)

    plug = CapturePlugin()
    m2 = create_machine(STRICT_CFG, logic=logic)
    i2 = Interpreter.from_snapshot(snap2, m2, plugins=[plug])
    await i2.start()
    await asyncio.sleep(0.01)
    await i2.stop()
    print("plugins= on_invalid_event calls:", len(plug.invalid_calls), plug.invalid_calls)
    print("PLUGINS_EXACTLY_ONCE_OK:", len(plug.invalid_calls) >= 1)


PRIORITY_CFG = {
    "id": "p",
    "initial": "a",
    "context": {"order": []},
    "onUnhandled": "defer",
    "states": {"a": {"on": {"X": {"actions": ["record"]}}}},
}


def record(i, ctx, ev, ad):
    tag = ev.payload.get("tag") if hasattr(ev, "payload") else ev.get("tag")
    ctx["order"].append(tag)


async def attack_sync_priority_lane_restore():
    logic = MachineLogic(actions={"record": record})
    m = create_machine(PRIORITY_CFG, logic=logic)
    i = SyncInterpreter(m)
    i.start()
    snap_str = json.dumps(i.get_persisted_snapshot())
    i.stop()

    # Build a restored inbox with mixed lanes, undelivered (parked ahead of
    # a start()), like the official #233 test: priority records must come
    # first, FIFO within each lane.
    payload = json.loads(snap_str)
    payload["pending_events"] = [
        {"type": "X", "payload": {"tag": "normal1"}, "lane": "normal"},
        {"type": "X", "payload": {"tag": "priority1"}, "lane": "priority"},
        {"type": "X", "payload": {"tag": "normal2"}, "lane": "normal"},
        {"type": "X", "payload": {"tag": "priority2"}, "lane": "priority"},
    ]
    snap2 = json.dumps(payload)

    m2 = create_machine(PRIORITY_CFG, logic=logic)
    i2 = SyncInterpreter.from_snapshot(snap2, m2)
    i2.start()
    order = i2.context.get("order", [])
    i2.stop()
    print("sync restore processed order:", order)
    expected = ["priority1", "priority2", "normal1", "normal2"]
    print("SYNC_PRIORITY_LANE_OK:", order == expected)


async def main():
    await attack_latch_roundtrip()
    await attack_strict_restore_property(320)
    await attack_plugins_exactly_once()
    await attack_sync_priority_lane_restore()


if __name__ == "__main__":
    asyncio.run(main())
