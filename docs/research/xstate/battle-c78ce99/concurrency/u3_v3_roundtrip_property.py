"""u3 (@c78ce99) -- STANDALONE. #213 snapshot layout v3 `scheduled_sends`.

P1  Property, >=300 random machines x both action kinds: arm a
    `raise(delay=D)` self-send, snapshot mid-flight on a SimulatedClock,
    restore, and require the remaining delay to be honoured EXACTLY
    (must not fire at remaining-1 ms, must fire at remaining+1 ms).
P2  Restore -> re-persist BEFORE start(): armed sends must survive the
    second hop.
P3  Cancelled sends leave no record.
P4  `strict: True` + a FORGED scheduled_sends record naming an event the
    chart does not declare -- is it admitted? (#214 applies strict to
    `pending_events`; does it reach here?)
P5  machine_hash vs scheduled_sends -- recorded, not asserted.

Run: python u3_v3_roundtrip_property.py   (exit 1 == defect)
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import random
import sys
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
    persistence,
)
from xstate_statemachine.clock import SimulatedClock

N_MACHINES = 300


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


def cfg(delay_ms, send_id=None, strict=False, evt="PING"):
    p: Dict[str, Any] = {"event": evt, "delay": delay_ms}
    if send_id:
        p["id"] = send_id
    c: Dict[str, Any] = {
        "id": "u3",
        "initial": "arm",
        "context": {"n": 0},
        "states": {
            "arm": {
                "entry": [{"type": "raise", "params": p}],
                "on": {evt: "fired"},
            },
            "fired": {"entry": ["tick"], "type": "final"},
        },
    }
    if strict:
        c["strict"] = True
    return c


def logic(kind):
    if kind == "def":

        def tick(i, ctx, e, ad):  # noqa: ANN001
            ctx["n"] = ctx.get("n", 0) + 1

        return MachineLogic(actions={"tick": tick})

    async def atick(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    return MachineLogic(actions={"tick": atick})


def blob_of(interp) -> str:
    snap = interp.get_persisted_snapshot()
    return snap if isinstance(snap, str) else json.dumps(snap, default=str)


async def p1_cell(delay_ms, elapsed_ms, kind) -> Dict[str, Any]:
    c = SimulatedClock()
    m = create_machine(copy.deepcopy(cfg(delay_ms)), logic=logic(kind))
    interp = Interpreter(m, clock=c)
    await interp.start()
    if elapsed_ms:
        await c.increment(elapsed_ms)   # SimulatedClock.increment takes MS
    blob = blob_of(interp)
    recs = json.loads(blob).get("scheduled_sends") or []
    await interp.stop()
    remaining = delay_ms - elapsed_ms
    out: Dict[str, Any] = {
        "delay_ms": delay_ms, "elapsed_ms": elapsed_ms, "kind": kind,
        "records": len(recs),
        "remaining_recorded": recs[0].get("remaining_ms") if recs else None,
    }
    if not recs:
        out["fail"] = "no scheduled_sends record for an armed delayed self-send"
        return out
    c2 = SimulatedClock()
    m2 = create_machine(copy.deepcopy(cfg(delay_ms)), logic=logic(kind))
    r = Interpreter.from_snapshot(blob, m2, clock=c2)
    await r.start()
    await c2.increment(max(remaining - 1, 0))
    out["fired_early"] = "u3.fired" in r.current_state_ids
    await c2.increment(2)
    out["fired_on_time"] = "u3.fired" in r.current_state_ids
    out["n"] = r.context.get("n")
    await r.stop()
    if out["fired_early"]:
        out["fail"] = "fired before the persisted remaining delay"
    elif not out["fired_on_time"]:
        out["fail"] = "did not fire at the persisted remaining delay"
    return out


async def p2_resnapshot() -> Dict[str, Any]:
    m = create_machine(copy.deepcopy(cfg(500)), logic=logic("def"))
    i = Interpreter(m, clock=SimulatedClock())
    await i.start()
    blob1 = blob_of(i)
    await i.stop()
    n1 = len(json.loads(blob1).get("scheduled_sends") or [])
    m2 = create_machine(copy.deepcopy(cfg(500)), logic=logic("def"))
    r = Interpreter.from_snapshot(blob1, m2, clock=SimulatedClock())
    n2 = len(json.loads(blob_of(r)).get("scheduled_sends") or [])
    out = {"first_hop_records": n1, "second_hop_records_before_start": n2}
    if n1 and not n2:
        out["fail"] = ("restore -> re-persist WITHOUT start() drops every "
                       "armed delayed self-send")
    return out


async def p3_cancel() -> Dict[str, Any]:
    conf = {
        "id": "u3c", "initial": "arm", "context": {"n": 0},
        "states": {
            "arm": {"entry": [{"type": "raise",
                               "params": {"event": "PING", "delay": 500,
                                          "id": "s1"}}],
                    "on": {"KILL": "off"}},
            "off": {"entry": [{"type": "cancel",
                               "params": {"sendId": "s1"}}]},
        },
    }
    m = create_machine(copy.deepcopy(conf), logic=logic("def"))
    i = Interpreter(m, clock=SimulatedClock())
    await i.start()
    before = len(json.loads(blob_of(i)).get("scheduled_sends") or [])
    await i.send("KILL")
    await asyncio.sleep(0.05)
    after = len(json.loads(blob_of(i)).get("scheduled_sends") or [])
    await i.stop()
    out = {"armed_before_cancel": before, "records_after_cancel": after}
    if after:
        out["fail"] = "a cancelled delayed send still leaves a v3 record"
    return out


async def p4_strict_forgery() -> Dict[str, Any]:
    conf = cfg(500, strict=True)
    m = create_machine(copy.deepcopy(conf), logic=logic("def"))
    i = Interpreter(m, clock=SimulatedClock())
    await i.start()
    snap = json.loads(blob_of(i))
    await i.stop()
    snap["scheduled_sends"] = [{"type": "NOT_IN_CHART", "kind": "event",
                                "payload": {}, "remaining_ms": 1.0}]
    refused: List[str] = []

    class Spy(PluginBase):
        def on_invalid_event(self, interpreter, error, event=None):  # noqa: ANN001
            refused.append(str(error))

    c2 = SimulatedClock()
    m2 = create_machine(copy.deepcopy(conf), logic=logic("def"))
    r = Interpreter.from_snapshot(json.dumps(snap), m2, clock=c2)
    r.use(Spy())
    await r.start()
    await c2.increment(50)
    out = {"strict_refusals": refused,
           "last_error": None if r.last_error is None else str(r.last_error)}
    await r.stop()
    if not refused:
        out["fail"] = ("a forged scheduled_sends record bypasses `strict` "
                       "entirely -- #214 applies strict to pending_events only")
    return out


def p5_hash() -> Dict[str, Any]:
    m = create_machine(copy.deepcopy(cfg(500)), logic=logic("def"))
    m2 = create_machine(copy.deepcopy(cfg(900)), logic=logic("def"))
    return {"hash_delay500": persistence.structure_hash(m),
            "hash_delay900": persistence.structure_hash(m2),
            "note": ("machine_hash is a STRUCTURE hash; scheduled_sends is "
                     "runtime state and is deliberately not covered. Two "
                     "charts differing only in a raise(delay=) PARAM hash "
                     "equal -- action params are excluded by _node_shape.")}


async def main() -> int:
    rng = random.Random(9931)
    p1: List[Dict[str, Any]] = []
    for k in range(N_MACHINES):
        delay = rng.choice([50, 100, 250, 500, 1000, 2500])
        elapsed = rng.choice([0, delay // 4, delay // 2, delay - 10])
        kind = "def" if k % 2 == 0 else "async def"
        p1.append(await p1_cell(delay, elapsed, kind))
    p1_fails = [r for r in p1 if "fail" in r]
    res: Dict[str, Any] = {
        "p1_machines": len(p1), "p1_failures": len(p1_fails),
        "p1_failure_sample": p1_fails[:5],
        "p1_no_record_count": sum(1 for r in p1 if r["records"] == 0),
        "p2_resnapshot": await p2_resnapshot(),
        "p3_cancel": await p3_cancel(),
        "p4_strict_forgery": await p4_strict_forgery(),
        "p5_hash": p5_hash(),
    }
    bad = bool(p1_fails) or any(
        "fail" in res[k]
        for k in ("p2_resnapshot", "p3_cancel", "p4_strict_forgery"))
    res["verdict"] = "DEFECT" if bad else "CLEAN"
    emit("u3_v3_roundtrip_property", res)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
