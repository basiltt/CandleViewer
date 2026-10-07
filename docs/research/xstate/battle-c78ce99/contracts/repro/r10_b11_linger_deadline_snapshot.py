# -*- coding: utf-8 -*-
"""STANDALONE verification -- a linger deadline survives a snapshot (#213).

CONTRACT SHAPE, not a defect report: this is the B11 `RecordingSession`
hazard that #213 fixed, re-proved on `c78ce99` against our own chart shape.

B11's `lingering` state has exactly one timed exit: the deadline armed by
`schedule_linger_deadline` fires LINGER_DUE, which decides between resuming
(`position_open_for_symbol`) and stopping the recorder. On 0.8.0 that armed
deadline existed nowhere the snapshot could see, so a recorder snapshotted
mid-linger restored PERMANENTLY PARKED -- the exact #213 shape, and a silent
capital-adjacent stall (the recorder never stops, never releases the stream
budget).

This asserts the round-10 contract:
  1. snapshot layout is v3 and carries `scheduled_sends`;
  2. the record holds the REMAINING delay (20 s of a 30 s deadline), not the
     full period -- a restore must not silently extend the deadline;
  3. `start()` re-arms it, so the restored machine still leaves `lingering`;
  4. both engines and both service styles (`def` / `async def`) agree.

stdlib + xstate_statemachine only, inline helpers, neutral cwd.
Run:  cd <home> && python <this file>      exits 0 when correct.
"""
from __future__ import annotations
import asyncio, json, sys

from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 create_machine, OverflowPolicy)
from xstate_statemachine.clock import SimulatedClock

LINGER_MS = 30000

# --- B11 reduced to the linger deadline, under the mandatory config --------
CFG = {
    "id": "recording",
    "actionErrorPolicy": "rollback",
    "onUnhandled": "defer",
    "guardErrorPolicy": "raise",
    "strictTargets": True,
    "strict": True,
    "strictConfig": True,          # #216, now mandatory for our contracts
    "spawnBlockingTimeout": 5000,
    "initial": "recording",
    "context": {"reasons": ["r1"]},
    "states": {
        "recording": {
            "on": {"REASON_REMOVED": {"target": "#recording.lingering"}}
        },
        "lingering": {
            # `schedule_linger_deadline`, realised the way a 0.8.1 wrapper
            # must realise it: a delayed self-raise with a stable send id.
            "entry": [{"type": "raise",
                       "params": {"event": "LINGER_DUE", "delay": LINGER_MS,
                                  "id": "cv-linger"}}],
            "on": {
                "LINGER_DUE": [
                    {"target": "#recording.recording",
                     "guard": "position_open_for_symbol"},
                    {"target": "#recording.stopping"},
                ],
                "REASON_ADDED": {"target": "#recording.recording"},
            },
        },
        "stopping": {"type": "final"},
    },
}

FAILS = []


def check(name, ok, note=""):
    print(("PASS " if ok else "FAIL ") + name + ("  | " + note if note else ""))
    if not ok:
        FAILS.append(name)


def logic():
    return MachineLogic(guards={"position_open_for_symbol": lambda c, e: False},
                        strict=True)


def mk():
    return create_machine(json.loads(json.dumps(CFG)), logic=logic())


async def async_lane():
    i = Interpreter(mk(), clock=SimulatedClock(), max_queue_size=64,
                    overflow_policy=OverflowPolicy.RAISE)
    await i.start()
    await i.send("REASON_REMOVED")
    for _ in range(4):
        await asyncio.sleep(0.03)
    check("async/in-lingering", sorted(i.current_state_ids) ==
          ["recording.lingering"], str(sorted(i.current_state_ids)))

    # let a third of the deadline elapse, then snapshot
    await i.clock.increment(10000)
    for _ in range(4):
        await asyncio.sleep(0.03)
    blob = i.get_persisted_snapshot()
    raw = json.loads(blob) if isinstance(blob, str) else blob
    sched = raw.get("scheduled_sends") or []

    check("async/#213/layout-v3", raw.get("version") == 3,
          "version=%r" % raw.get("version"))
    check("async/#213/armed-deadline-persisted", len(sched) == 1,
          json.dumps(sched))
    rem = (sched[0].get("remaining_ms") if sched else None)
    check("async/#213/remaining-not-full-period",
          rem is not None and 19000 <= float(rem) <= 21000,
          "remaining_ms=%r (armed %d, 10000 elapsed)" % (rem, LINGER_MS))
    await i.stop()

    # restore and prove the deadline still fires, on the REMAINING time
    j = Interpreter.from_snapshot(json.dumps(raw), mk(),
                                  clock=SimulatedClock(), minimum_version=3)
    await j.start()
    for _ in range(4):
        await asyncio.sleep(0.03)
    check("async/restored-still-lingering",
          sorted(j.current_state_ids) == ["recording.lingering"],
          str(sorted(j.current_state_ids)))
    await j.clock.increment(19000)
    for _ in range(4):
        await asyncio.sleep(0.03)
    check("async/restored/not-early-at-+19s",
          sorted(j.current_state_ids) == ["recording.lingering"],
          str(sorted(j.current_state_ids)))
    await j.clock.increment(2000)
    for _ in range(4):
        await asyncio.sleep(0.03)
    check("async/restored/fires-at-remaining",
          sorted(j.current_state_ids) == ["recording.stopping"],
          str(sorted(j.current_state_ids)))
    await j.stop()
    return raw


def sync_lane(raw):
    i = SyncInterpreter(mk(), clock=SimulatedClock())
    i.start()
    i.send("REASON_REMOVED")
    check("sync/in-lingering", sorted(i.current_state_ids) ==
          ["recording.lingering"], str(sorted(i.current_state_ids)))
    i.clock.increment(10000)
    blob = i.get_persisted_snapshot()
    s_raw = json.loads(blob) if isinstance(blob, str) else blob
    sched = s_raw.get("scheduled_sends") or []
    check("sync/#213/armed-deadline-persisted",
          s_raw.get("version") == 3 and len(sched) == 1, json.dumps(sched))
    i.stop()

    j = SyncInterpreter.from_snapshot(json.dumps(s_raw), mk(),
                                      clock=SimulatedClock(),
                                      minimum_version=3)
    j.start()
    j.clock.increment(19000)
    check("sync/restored/not-early-at-+19s",
          sorted(j.current_state_ids) == ["recording.lingering"],
          str(sorted(j.current_state_ids)))
    j.clock.increment(2000)
    check("sync/restored/fires-at-remaining",
          sorted(j.current_state_ids) == ["recording.stopping"],
          str(sorted(j.current_state_ids)))
    j.stop()


def main():
    raw = asyncio.run(async_lane())
    sync_lane(raw)
    print("\n%d FAIL: %s" % (len(FAILS), FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
