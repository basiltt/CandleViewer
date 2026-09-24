# -*- coding: utf-8 -*-
"""S2 -- priority-lane provenance across a snapshot round-trip (#192/#180).

#192 made every priority-lane item carry its PROVENANCE (external vs
self-generated) so the shed site only ever cuts self-generated work and an
action-issued priority send is charged. That flag lives on the in-memory
lane item ``(event, self_generated)`` (`interpreter.py:355`).

A snapshot flattens the lane: `_snapshot_pending_events` returns
``[ev for ev, _ in self._priority_queue] + inbox`` (`interpreter.py:1488`)
and the restore path puts every record back with `_enqueue_restored` ->
`_put_inbox` (`interpreter.py:1490`). So this probe asks:

  A. Does a PENDING external `send(priority=True)` survive the round-trip
     at all, and on which lane?
  B. Does a PENDING engine completion (self-generated, charged) survive,
     and does it come back CHARGED -- i.e. does a chain that was one lap
     from tripping still trip after a restore, or does the restore reset
     the budget and let a runaway run forever?
  C. Ordering: priority-before-inbox must still hold after restore.

STANDALONE. Both service kinds via XS_SVC=def|async.
"""
from __future__ import annotations

import asyncio
import json
import os

from xstate_statemachine import Interpreter, MachineLogic, create_machine

KIND = os.environ.get("XS_SVC", "async")
FAIL: list[str] = []

# A machine that sits still: we only care about queue contents.
PARK = {
    "id": "park",
    "initial": "a",
    "states": {
        "a": {"on": {"EXT": {"target": "b"}, "INB": {"target": "b"}}},
        "b": {},
    },
}


async def part_a() -> None:
    """External priority send, snapshotted before it is processed."""
    print("=== A. external priority send across a round-trip ===")
    m = create_machine(PARK, logic=MachineLogic())
    i = Interpreter(m)
    await i.start()
    # No `await` between the sends and the snapshot, so the run loop never
    # gets a turn and both events are still queued when we capture.
    i.send("INB")
    i.send("EXT", priority=True)
    pend = [getattr(e, "type", "?") for e in i.pending_events]
    print("  live pending order:", pend)
    blob = i.get_persisted_snapshot()

    await i.stop()
    rec = blob["pending_events"]
    print("  persisted records :", [r.get("type") for r in rec])
    print("  record keys       :", [sorted(r.keys()) for r in rec])
    if [r.get("type") for r in rec] != pend:
        FAIL.append("A: persisted pending order != live order")
    if not any("priority" in r or "lane" in r for r in rec):
        print("  NOTE: no record carries a lane/priority/provenance field")

    m2 = create_machine(PARK, logic=MachineLogic())
    j = Interpreter.from_snapshot(json.dumps(blob), m2)
    back = [getattr(e, "type", "?") for e in j.pending_events]
    print("  restored pending  :", back)
    if back != pend:
        FAIL.append("A: restored lane order %s != persisted %s"
                    % (back, pend))
    # which lane did each land on?
    lane = [t for t, _ in list(j._priority_queue)]  # noqa: SLF001
    print("  restored priority lane:", [getattr(e, "type", "?") for e in lane])
    if not lane:
        print("  => the priority lane is EMPTY after restore: the external "
              "priority send came back as ORDINARY inbox traffic")
    await j.stop()


CHAIN = {
    "id": "ch",
    "initial": "a",
    "maxIterations": 25,
    "states": {
        "a": {"entry": ["bump"], "on": {"TICK": {"target": "a"}}},
    },
}


def chain_machine(limit: int = 25):
    n = {"v": 0}

    def bump(interp, ctx, ev, act):
        n["v"] += 1
        interp.send("TICK", priority=True)  # action-issued priority send

    spec = json.loads(json.dumps(CHAIN))
    spec["maxIterations"] = limit
    return create_machine(spec, logic=MachineLogic(actions={"bump": bump})), n


async def part_b() -> None:
    """Does the chain budget survive a restore, or is it reset?"""
    print("\n=== B. chain budget across a round-trip (#192 charge site) ===")
    m, n = chain_machine(25)
    i = Interpreter(m)
    await i.start()
    await asyncio.sleep(0.6)
    print("  live: bumps=%d status=%s err=%r"
          % (n["v"], i.status, i.error))
    tripped_live = n["v"] < 500
    blob = i.get_persisted_snapshot()
    await i.stop()
    m2, n2 = chain_machine(25)
    j = Interpreter.from_snapshot(json.dumps(blob), m2)
    await j.start()
    await asyncio.sleep(0.6)
    print("  restored: bumps=%d status=%s err=%r"
          % (n2["v"], j.status, j.error))
    await j.stop()
    if tripped_live and n2["v"] > 10 * max(n["v"], 1):
        FAIL.append("B: the restored machine ran far past the live trip "
                    "point (%d vs %d bumps) -- the budget did not survive"
                    % (n2["v"], n["v"]))


async def main() -> None:
    print("=== S2 priority-lane provenance round-trip [%s] ===" % KIND)
    await part_a()
    await part_b()
    print("\nFAILURES:", FAIL if FAIL else "none")
    print("VERDICT:", "FAIL" if FAIL else "PASS")


asyncio.run(main())
