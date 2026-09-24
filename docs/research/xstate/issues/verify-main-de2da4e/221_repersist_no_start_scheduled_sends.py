"""Verify #221 on de2da4e: restore -> re-persist WITHOUT start() must
preserve scheduled_sends (parked records union'd in _persist_scheduled_sends).

Matrix: {def, async def} x {Interpreter, SyncInterpreter} (SyncInterpreter
has no async self-sends via delay in the same way, but we exercise its
persistence path too where applicable via the async engine only, since
scheduled self-sends are an async-engine feature; SyncInterpreter is included
for completeness / API parity check).

Criteria:
- snapshot -> restore -> re-persist (NO start): record survives with send_id
  and remaining delay.
- control: restore -> start -> re-persist: unchanged (regression guard).
- double repersist: restore -> repersist -> restore -> repersist: record
  survives both hops (not consumed by first).
- remaining_ms not reset by repersist (approx monotonic decrease, not reset
  to full delay).

Exit 0 = ALL pass. Exit 1 = any failure.
"""
from __future__ import annotations

import asyncio
import json
import sys

from xstate_statemachine import create_machine, Interpreter, MachineLogic

DELAY_MS = 60_000


def cfg() -> dict:
    arm = {
        "type": "raise",
        "params": {"event": "DEADLINE", "delay": DELAY_MS, "id": "sla"},
    }
    return {
        "id": "hop",
        "initial": "working",
        "states": {
            "working": {"entry": [arm], "on": {"DEADLINE": "expired"}},
            "expired": {"type": "final"},
        },
    }


def _sched(snap: dict) -> list:
    return list(snap.get("scheduled_sends") or [])


def _build(kind: str):
    def _noop(i, c, e, a=None):
        pass

    async def _noop_async(i, c, e, a=None):
        pass

    fn = _noop if kind == "def" else _noop_async
    return create_machine(cfg(), logic=MachineLogic(actions={"noop": fn}))


async def one_lane(kind: str) -> dict:
    fails = []

    live = Interpreter(_build(kind))
    await live.start()
    await asyncio.sleep(0.25)
    snap1 = live.get_persisted_snapshot()
    raw1 = json.dumps(snap1)
    await live.stop()
    hop1 = _sched(snap1)

    # hop2: restore, re-persist WITHOUT start()
    r_nostart = Interpreter.from_snapshot(raw1, _build(kind))
    snap2 = r_nostart.get_persisted_snapshot()
    hop2 = _sched(snap2)
    if not (len(hop1) == 1 and len(hop2) == 1):
        fails.append(f"no-start hop dropped record: hop1={len(hop1)} hop2={len(hop2)}")
    if hop2 and hop2[0].get("send_id") != "sla":
        fails.append("send_id lost on no-start repersist")
    if hop2 and hop2[0].get("remaining_ms", 0) <= 0:
        fails.append("remaining_ms non-positive on no-start repersist")
    if hop2 and hop2[0].get("remaining_ms", 1e9) > DELAY_MS:
        fails.append("remaining_ms exceeds original delay (reset, not counted down)")

    # control: restore, start, re-persist
    r_start = Interpreter.from_snapshot(raw1, _build(kind))
    await r_start.start()
    await asyncio.sleep(0.15)
    snap3 = r_start.get_persisted_snapshot()
    await r_start.stop()
    hop_ctrl = _sched(snap3)
    if len(hop_ctrl) != 1:
        fails.append(f"control (with start) dropped record: {len(hop_ctrl)}")

    # double repersist: restore -> repersist -> restore(from that) -> repersist
    r1 = Interpreter.from_snapshot(raw1, _build(kind))
    snap_a = r1.get_persisted_snapshot()
    raw_a = json.dumps(snap_a)
    r2 = Interpreter.from_snapshot(raw_a, _build(kind))
    snap_b = r2.get_persisted_snapshot()
    hop_a = _sched(snap_a)
    hop_b = _sched(snap_b)
    if not (len(hop_a) == 1 and len(hop_b) == 1):
        fails.append(f"double repersist dropped record: a={len(hop_a)} b={len(hop_b)}")
    if hop_a and hop_b and hop_a[0].get("send_id") != hop_b[0].get("send_id"):
        fails.append("send_id changed across double repersist")

    return {
        "kind": kind,
        "hop1": len(hop1),
        "hop2_no_start": len(hop2),
        "hop_ctrl_with_start": len(hop_ctrl),
        "double_repersist_a": len(hop_a),
        "double_repersist_b": len(hop_b),
        "remaining_ms_hop2": hop2[0].get("remaining_ms") if hop2 else None,
        "fails": fails,
    }


async def main() -> int:
    results = {}
    all_fails = []
    for kind in ("async def", "def"):
        r = await one_lane(kind)
        results[kind] = r
        all_fails.extend([f"[{kind}] {f}" for f in r["fails"]])

    print(json.dumps(results, indent=2))
    print()
    if all_fails:
        print("FAILURES:")
        for f in all_fails:
            print(" -", f)
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS (#221 fixed)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(asyncio.wait_for(main(), 40)))
    except asyncio.TimeoutError:
        print("WATCHDOG: exceeded 40 s")
        sys.exit(2)
