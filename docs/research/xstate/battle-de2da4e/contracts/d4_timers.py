# -*- coding: utf-8 -*-
"""D4 (de2da4e): round-11 timer + persistence contract for catalogue deadlines.

  #218  a `raise(delay=)` heartbeat must hold <= 1 clock handle for 200 beats,
        on BOTH engines (B11 linger, B13 pong/backoff deadlines are exactly
        this shape once implemented as self-scheduled deadlines).
  #221  restore -> re-persist WITHOUT start() must re-emit the parked v3
        `scheduled_sends` verbatim (a journal-compaction job must not drop an
        armed linger / pong deadline).
"""
from __future__ import annotations
import asyncio, json
import cvb as H
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 create_machine, OverflowPolicy)
from xstate_statemachine.clock import SimulatedClock

BEATS = 200

HEART = {
    "id": "hb", "actionErrorPolicy": "rollback", "guardErrorPolicy": "raise",
    "strictTargets": True, "strict": True, "strictConfig": True,
    "maxIterations": 5,
    "initial": "beating", "context": {"n": 0},
    "states": {
        "beating": {
            "entry": [{"type": "raise", "params": {"event": "TICK",
                                                   "delay": 50}}],
            "on": {"TICK": {"actions": [
                "bump", {"type": "raise", "params": {"event": "TICK",
                                                     "delay": 50}}]},
                   "STOP": {"target": "#hb.done"}},
        },
        "done": {"type": "final"},
    },
}


def heart_logic(box):
    def bump(i, c, e, a):
        box["n"] += 1
    return MachineLogic(actions={"bump": bump}, strict=True)


def handle_count(i):
    """Total live clock handles across every owner (the #218 ledger)."""
    return sum(len(v) for v in getattr(i, "_timer_handles", {}).values())


async def h218_async():
    box = {"n": 0}
    m = create_machine(json.loads(json.dumps(HEART)), logic=heart_logic(box),
                       strict_targets=True, strict_config=True)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=256,
                    overflow_policy=OverflowPolicy.RAISE)
    p = H.CvHooks(); i.use(p)
    await i.start(); await H.quiesce(i, 2)
    peak = handle_count(i)
    for _ in range(BEATS):
        await i.clock.increment(50.0)
        await asyncio.sleep(0.002)
        peak = max(peak, handle_count(i))
    await H.quiesce(i, 2)
    H.rec("D4/218/async/heartbeat-runs-%d-beats" % BEATS, box["n"] >= BEATS - 5,
          "beats=%d of %d (maxIterations=5; #212: a delay is a timer)"
          % (box["n"], BEATS))
    H.rec("D4/218/async/handles-flat", peak <= 1,
          "peak live handles=%d over %d beats, final=%d"
          % (peak, BEATS, handle_count(i)))
    H.rec("D4/218/async/no-chain-trip", i.chain_trips == 0,
          "chain_trips=%d last_chain_error=%s"
          % (i.chain_trips, i.last_chain_error))
    await asyncio.wait_for(i.send("STOP"), 5); await H.quiesce(i, 2)
    H.rec("D4/218/async/cancel-releases-handle", handle_count(i) == 0,
          "after STOP -> %s, handles=%d" % (H.ids(i), handle_count(i)))
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass


def h218_sync():
    box = {"n": 0}
    m = create_machine(json.loads(json.dumps(HEART)), logic=heart_logic(box),
                       strict_targets=True, strict_config=True)
    i = SyncInterpreter(m, clock=SimulatedClock())
    p = H.CvHooks(); i.use(p)
    i.start()
    peak = handle_count(i)
    for _ in range(BEATS):
        i.clock.increment(50.0)
        peak = max(peak, handle_count(i))
    H.rec("D4/218/sync/heartbeat-runs-%d-beats" % BEATS, box["n"] >= BEATS - 5,
          "beats=%d of %d" % (box["n"], BEATS))
    H.rec("D4/218/sync/handles-flat", peak <= 1,
          "peak live handles=%d over %d beats, final=%d"
          % (peak, BEATS, handle_count(i)))
    H.rec("D4/218/sync/no-chain-trip", i.chain_trips == 0,
          "chain_trips=%d" % i.chain_trips)
    i.send("STOP")
    H.rec("D4/218/sync/cancel-releases-handle", handle_count(i) == 0,
          "after STOP -> %s, handles=%d" % (H.ids(i), handle_count(i)))
    try:
        i.stop()
    except Exception:
        pass


# --------------------------------------------------------------- #221 ------
LINGER = {
    "id": "linger", "actionErrorPolicy": "rollback",
    "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
    "strictConfig": True,
    "initial": "idle", "context": {},
    "states": {
        "idle": {"on": {"ARM": {"target": "#linger.lingering"}}},
        "lingering": {
            "entry": [{"type": "raise", "params": {"event": "LINGER_DUE",
                                                   "delay": 30000}}],
            "on": {"LINGER_DUE": {"target": "#linger.stopping"}},
        },
        "stopping": {"type": "final"},
    },
}


def linger_machine():
    return create_machine(json.loads(json.dumps(LINGER)),
                          logic=MachineLogic(actions={}, strict=True),
                          strict_targets=True, strict_config=True)


def as_json(blob):
    return json.loads(blob) if isinstance(blob, str) else blob


def as_str(blob):
    return blob if isinstance(blob, str) else json.dumps(blob)


async def h221():
    i = Interpreter(linger_machine(), clock=SimulatedClock(),
                    max_queue_size=64, overflow_policy=OverflowPolicy.RAISE)
    await i.start(); await H.quiesce(i, 2)
    await asyncio.wait_for(i.send("ARM"), 5); await H.quiesce(i, 2)
    await i.clock.increment(10000.0); await H.quiesce(i, 2)
    blob = i.get_persisted_snapshot()
    raw = as_json(blob)
    sched = raw.get("scheduled_sends") or []
    H.rec("D4/221/v3-records-armed-deadline",
          raw.get("version") == 3 and len(sched) == 1,
          "v=%s scheduled_sends=%s"
          % (raw.get("version"), json.dumps(sched, default=str)[:200]))
    await i.stop()

    j = Interpreter.from_snapshot(as_str(blob), linger_machine(),
                                  clock=SimulatedClock(), minimum_version=3)
    raw2 = as_json(j.get_persisted_snapshot())
    sched2 = raw2.get("scheduled_sends") or []
    H.rec("D4/221/repersist-without-start-keeps-deadline", sched2 == sched,
          "before=%s after=%s" % (json.dumps(sched, default=str)[:150],
                                  json.dumps(sched2, default=str)[:150]))

    k = Interpreter.from_snapshot(as_str(j.get_persisted_snapshot()),
                                  linger_machine(), clock=SimulatedClock(),
                                  minimum_version=3)
    raw3 = as_json(k.get_persisted_snapshot())
    H.rec("D4/221/two-hop-compaction-keeps-deadline",
          (raw3.get("scheduled_sends") or []) == sched,
          "hop2=%s" % json.dumps(raw3.get("scheduled_sends"), default=str)[:150])

    await k.start(); await H.quiesce(k, 2)
    await k.clock.increment(19000.0); await H.quiesce(k, 3)
    mid = H.ids(k)
    await k.clock.increment(2000.0); await H.quiesce(k, 3)
    H.rec("D4/221/remaining-delay-honoured",
          mid == ["linger.lingering"] and H.ids(k) == ["linger.stopping"],
          "at +19s=%s, at +21s=%s (20 000 ms remained of 30 000)"
          % (mid, H.ids(k)))
    raw4 = as_json(k.get_persisted_snapshot())
    H.rec("D4/221/no-duplicate-after-fire",
          len(raw4.get("scheduled_sends") or []) == 0,
          "post-fire scheduled_sends=%s" % (raw4.get("scheduled_sends"),))
    try:
        await asyncio.wait_for(k.stop(), 5)
    except Exception:
        pass


async def main():
    await h218_async()
    await h221()


# NOTE: SyncInterpreter + SimulatedClock must run with NO running loop --
# `increment` returns a _MustAwait inside one, so a sync drive nested in
# asyncio.run() silently advances nothing (harness bug, not a library one).
h218_sync()
asyncio.run(main())
H.dump("results/d4_timers.json")
