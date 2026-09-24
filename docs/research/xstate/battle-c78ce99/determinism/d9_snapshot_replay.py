"""D9 -- audit-log reproducibility: does a snapshot round-trip preserve bytes?

Two questions for a replay/audit pipeline:

  R1  Is `get_persisted_snapshot()` byte-stable for the same logical state?
      Take a snapshot, restore it, take another -- do they match (modulo
      `taken_at`)? Repeat across runs of the same script.

  R2  Is a snapshot taken mid-stream on the async engine byte-identical to one
      taken at the same logical point on the sync engine?

  R3  Does replaying from a restored snapshot produce the same subsequent
      trace as running straight through?
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.disable(logging.CRITICAL)

from dmachine import Recorder, build, canon_snapshot, make_script  # noqa: E402
from xstate_statemachine import Interpreter, SyncInterpreter  # noqa: E402
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

SPLIT = 120
TOTAL = 260


async def straight(script):
    rec = Recorder()
    clock = SimulatedClock()
    i = Interpreter(build(rec), clock=clock)
    await i.start()
    mid = None
    for k, step in enumerate(script):
        if step[0] == "tick":
            await clock.increment(step[1])
        else:
            await i.send(step[1], **step[2])
        if k == SPLIT:
            mid = i.get_persisted_snapshot()
    end = canon_snapshot(i.get_persisted_snapshot())
    await i.stop()
    return rec.actions, mid, end


async def resumed(script, mid_json):
    """Restore at SPLIT and replay the tail.

    ⚠️ `from_snapshot` has NO `clock=` parameter (base_interpreter.py:1103) and
    constructs `cls(machine)` (base_interpreter.py:1189), so the restored
    interpreter gets a `RealClock`. A replay harness cannot keep virtual time
    across a restore -- see D-determinism-5.
    """
    rec = Recorder()
    i = Interpreter.from_snapshot(mid_json, build(rec))
    for step in script[SPLIT + 1 :]:
        if step[0] == "tick":
            pass  # no injectable clock on a restored interpreter
        else:
            r = i.send(step[1], **step[2])
            if asyncio.iscoroutine(r):
                await r
    for _ in range(2000):
        await asyncio.sleep(0)
    end = canon_snapshot(i.get_persisted_snapshot())
    return rec.actions, end, type(i.clock).__name__


async def main():
    script = make_script(TOTAL)

    # R1 -- snapshot stability across identical runs
    outs = []
    for _ in range(8):
        acts, mid, end = await straight(script)
        outs.append((canon_snapshot(mid), end, acts))
    mids = {o[0] for o in outs}
    ends = {o[1] for o in outs}
    acts_same = all(o[2] == outs[0][2] for o in outs)
    print("R1 snapshot byte-stability over 8 identical async runs")
    print(f"   distinct mid-stream snapshots : {len(mids)}")
    print(f"   distinct final snapshots      : {len(ends)}")
    print(f"   action traces identical       : {acts_same}")

    # R1b -- restore then re-snapshot: same bytes?
    _, mid_raw, _ = await straight(script)
    mid_json = json.dumps(mid_raw, default=str)
    rec = Recorder()
    i = Interpreter.from_snapshot(mid_json, build(rec))
    round_trip = canon_snapshot(i.get_persisted_snapshot())
    original = canon_snapshot(mid_raw)
    print(f"   restored clock type: {type(i.clock).__name__}")
    print("\nR1b snapshot -> restore -> snapshot")
    print(f"   byte-identical: {round_trip == original}")
    if round_trip != original:
        a, b = json.loads(original), json.loads(round_trip)
        for k in sorted(set(a) | set(b)):
            if a.get(k) != b.get(k):
                print(f"     key '{k}' differs")
                print(f"       before: {json.dumps(a.get(k))[:300]}")
                print(f"       after : {json.dumps(b.get(k))[:300]}")

    # R2 -- async vs sync snapshot at the same logical point
    rec = Recorder()
    clock = SimulatedClock()
    s = SyncInterpreter(build(rec), clock=clock)
    s.start()
    for k, step in enumerate(script):
        if step[0] == "tick":
            clock.increment(step[1])
        else:
            s.send(step[1], **step[2])
        if k == SPLIT:
            s_mid = canon_snapshot(s.get_persisted_snapshot())
            break
    s.stop()
    print("\nR2 async vs sync snapshot at step %d" % SPLIT)
    print(f"   byte-identical: {s_mid == original}")
    if s_mid != original:
        a, b = json.loads(original), json.loads(s_mid)
        for k in sorted(set(a) | set(b)):
            if a.get(k) != b.get(k):
                print(f"     key '{k}':")
                print(f"       async: {json.dumps(a.get(k))[:220]}")
                print(f"       sync : {json.dumps(b.get(k))[:220]}")

    # R3 -- straight-through tail vs replay-from-snapshot tail
    acts_straight, mid_raw2, end_straight = await straight(script)
    tail_straight = acts_straight[len(acts_straight) // 2 :]
    acts_res, end_res, rclock = await resumed(
        script, json.dumps(mid_raw2, default=str)
    )
    print("\nR3 resume-from-snapshot vs straight-through")
    print(f"   restored interpreter clock: {rclock}")
    print(f"   final snapshots identical : {end_res == end_straight}")
    print(f"   resumed trace length      : {len(acts_res)}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "d9_snapshot.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "R1_distinct_mid": len(mids),
                "R1_distinct_end": len(ends),
                "R1_actions_identical": acts_same,
                "R1b_roundtrip_identical": round_trip == original,
                "R2_cross_engine_identical": s_mid == original,
                "R3_resume_identical": end_res == end_straight,
                "R3_restored_clock": rclock,
            },
            f,
            indent=2,
        )
    print("\nwrote out/d9_snapshot.json")


if __name__ == "__main__":
    asyncio.run(main())
