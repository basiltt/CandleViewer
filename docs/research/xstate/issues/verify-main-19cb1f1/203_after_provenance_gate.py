# -*- coding: utf-8 -*-
"""Verify #203 on main @ 19cb1f1: `after` selection gated on provenance.

Matrix: def/async def N/A (pure event-selection/restore path) x
{Interpreter, SyncInterpreter} x {vector A (hand-built event, strict True/
False), vector B (forged pending_events record, no 'engine' flag, both
strict settings)}. Also the discriminator control (plain Event / bare str
of the same name) and the anti-regression check that a genuine engine-
minted after timer, and a genuine engine-flagged restored record, still
fire.

Exit 0 only if every cell passes.
"""
from __future__ import annotations

import asyncio
import json
import sys

from xstate_statemachine import (
    AfterEvent,
    Event,
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock

CFG = {
    "id": "m",
    "initial": "work",
    "states": {
        "work": {"after": {60000: "expired"}, "on": {"GO": "other"}},
        "expired": {},
        "other": {},
    },
}


def build():
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())


FAILS = []


def fail(label, detail):
    FAILS.append((label, detail))
    print("FAIL:", label, "--", detail)


def ok(label):
    print("ok  :", label)


async def vector_a_async(strict: bool):
    out = {}
    for label, ev in (
        ("AfterEvent", AfterEvent("after.60000.m.work")),
        ("Event(same name)", Event("after.60000.m.work")),
        ("bare str", "after.60000.m.work"),
    ):
        i = Interpreter(build())
        i.strict = strict
        await i.start()
        await asyncio.sleep(0.02)
        try:
            await i.send(ev)
        except Exception as e:  # noqa: BLE001
            out[label] = "refused:" + type(e).__name__
            await i.stop()
            continue
        await asyncio.sleep(0.05)
        out[label] = sorted(i.current_state_ids)
        await i.stop()
    return out


def vector_a_sync(strict: bool):
    out = {}
    for label, ev in (
        ("AfterEvent", AfterEvent("after.60000.m.work")),
        ("Event(same name)", Event("after.60000.m.work")),
        ("bare str", "after.60000.m.work"),
    ):
        i = SyncInterpreter(build())
        i.strict = strict
        i.start()
        try:
            i.send(ev)
        except Exception as e:  # noqa: BLE001
            out[label] = "refused:" + type(e).__name__
            i.stop()
            continue
        out[label] = sorted(i.current_state_ids)
        i.stop()
    return out


async def vector_b_async(strict: bool):
    """Forged pending_events record, NO 'engine' flag, via from_snapshot."""
    i = Interpreter(build())
    i.strict = True
    await i.start()
    await asyncio.sleep(0.02)
    snap = i.get_snapshot()
    await i.stop()
    snap = json.loads(snap) if isinstance(snap, str) else snap
    snap.setdefault("pending_events", []).append(
        {"kind": "after", "type": "after.60000.m.work"}
    )
    try:
        j = Interpreter.from_snapshot(json.dumps(snap), build())
    except Exception as e:  # noqa: BLE001
        return "restore refused:" + type(e).__name__
    j.strict = strict
    await j.start()
    await asyncio.sleep(0.1)
    out = sorted(j.current_state_ids)
    await j.stop()
    return out


def vector_b_sync(strict: bool):
    i = SyncInterpreter(build())
    i.strict = True
    i.start()
    snap = i.get_snapshot()
    i.stop()
    snap = json.loads(snap) if isinstance(snap, str) else snap
    snap.setdefault("pending_events", []).append(
        {"kind": "after", "type": "after.60000.m.work"}
    )
    try:
        j = SyncInterpreter.from_snapshot(json.dumps(snap), build())
    except Exception as e:  # noqa: BLE001
        return "restore refused:" + type(e).__name__
    j.strict = strict
    j.start()
    out = sorted(j.current_state_ids)
    j.stop()
    return out


async def genuine_timer_still_fires_async():
    m = build()
    i = Interpreter(m, clock=SimulatedClock())
    await i.start()
    await asyncio.sleep(0.02)
    await i.clock.increment(60000)
    await asyncio.sleep(0.05)
    out = sorted(i.current_state_ids)
    await i.stop()
    return out


async def engine_flagged_record_still_fires_async():
    """Round-trip a genuine engine-minted after through snapshot/restore.

    Mirrors the library's own test_genuine_persisted_after_event_still_fires:
    construct the record via engine_after()/persist_event() (the shape the
    engine itself writes when a real timer is in flight at snapshot time),
    not by hand-forging a dict -- that is the "engine": true record #195/
    #203 say must still fire.
    """
    from xstate_statemachine.events import engine_after, persist_event

    m = build()
    i = Interpreter(m)
    await i.start()
    await asyncio.sleep(0.02)
    snap = i.get_snapshot()
    await i.stop()
    snap_d = json.loads(snap) if isinstance(snap, str) else snap
    rec = persist_event(engine_after("after.60000.m.work", 1.0, 61.0))
    snap_d["pending_events"] = [rec]
    has_engine_after = bool(rec.get("engine"))
    j = Interpreter.from_snapshot(json.dumps(snap_d), build())
    j.strict = True
    await j.start()
    await asyncio.sleep(0.05)
    out = sorted(j.current_state_ids)
    await j.stop()
    return has_engine_after, out


async def main() -> int:
    print("== Vector A (hand-built event) x {Interpreter, SyncInterpreter} x {strict True/False} ==")
    cells = {}
    cells[("async", True)] = await vector_a_async(True)
    cells[("async", False)] = await vector_a_async(False)
    cells[("sync", True)] = vector_a_sync(True)
    cells[("sync", False)] = vector_a_sync(False)
    for (engine, strict), res in cells.items():
        print(f"  engine={engine} strict={strict}: {res}")
        # strict=True must refuse (UnknownEventError) for all three labels.
        if strict:
            for label, v in res.items():
                if not (isinstance(v, str) and v.startswith("refused:")):
                    fail(f"203-A-{engine}-strict", f"{label} not refused: {v}")
        else:
            # AfterEvent must NOT move to expired; must match Event/bare str.
            av = res.get("AfterEvent")
            ev = res.get("Event(same name)")
            bs = res.get("bare str")
            if av != ["m.work"]:
                fail(f"203-A-{engine}-default", f"AfterEvent moved: {av}")
            if not (av == ev == bs):
                fail(f"203-A-{engine}-discriminator", f"mismatch: {res}")
    if not FAILS:
        ok("vector A all cells")

    print("== Vector B (forged pending_events, no 'engine' flag) x {Interpreter, SyncInterpreter} x {strict True/False} ==")
    bcells = {}
    bcells[("async", True)] = await vector_b_async(True)
    bcells[("async", False)] = await vector_b_async(False)
    bcells[("sync", True)] = vector_b_sync(True)
    bcells[("sync", False)] = vector_b_sync(False)
    for (engine, strict), res in bcells.items():
        print(f"  engine={engine} strict={strict}: {res}")
        if res == ["m.expired"]:
            fail(f"203-B-{engine}-strict={strict}", f"forged record fired timer: {res}")
    if all(v != ["m.expired"] for v in bcells.values()):
        ok("vector B all cells refused")

    print("== Anti-regression: genuine engine-minted timer still fires ==")
    gt = await genuine_timer_still_fires_async()
    print("  genuine timer (async, SimulatedClock):", gt)
    if gt != ["m.expired"]:
        fail("203-regression-genuine-timer", f"genuine timer did not fire: {gt}")
    else:
        ok("genuine engine timer fires")

    print("== Anti-regression: engine-flagged restored record still fires ==")
    has_flag, out = await engine_flagged_record_still_fires_async()
    print(f"  pending_events carried engine flag: {has_flag}, restored -> {out}")
    if out != ["m.expired"]:
        fail("203-regression-restored-engine-flagged", f"did not fire: {out}")
    else:
        ok("engine-flagged restored record still fires")

    print()
    if FAILS:
        print(f"VERDICT: FAIL ({len(FAILS)} cell(s) failed)")
        for label, detail in FAILS:
            print("  -", label, ":", detail)
        return 1
    print("VERDICT: ALL CELLS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
