# -*- coding: utf-8 -*-
"""STANDALONE (stdlib + xstate_statemachine only) repro of the three
round-11 behaviours an OMS deadline depends on, on a self-contained chart
shaped like a catalogue linger / pong deadline. Run from any cwd.

Exit 0 = all three behaviours present (expected on de2da4e);
non-zero = regression.
"""
from __future__ import annotations
import asyncio, json, sys

from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 create_machine, OverflowPolicy)
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import ReentrantWaitError

FAILS = []
BEATS = 200


def rec(name, ok, note=""):
    print(("PASS " if ok else "FAIL ") + name + ("  | " + note if note else ""))
    if not ok:
        FAILS.append(name)


HEART = {
    "id": "hb", "strict": True, "strictTargets": True, "strictConfig": True,
    "actionErrorPolicy": "rollback", "guardErrorPolicy": "raise",
    "maxIterations": 5, "initial": "beating", "context": {},
    "states": {
        "beating": {
            "entry": [{"type": "raise",
                       "params": {"event": "TICK", "delay": 50}}],
            "on": {"TICK": {"actions": [
                       "bump",
                       {"type": "raise",
                        "params": {"event": "TICK", "delay": 50}}]},
                   "STOP": {"target": "#hb.done"}}},
        "done": {"type": "final"}},
}

LINGER = {
    "id": "linger", "strict": True, "strictTargets": True,
    "strictConfig": True, "actionErrorPolicy": "rollback",
    "guardErrorPolicy": "raise", "initial": "idle", "context": {},
    "states": {
        "idle": {"on": {"ARM": {"target": "#linger.lingering"}}},
        "lingering": {
            "entry": [{"type": "raise",
                       "params": {"event": "DUE", "delay": 30000}}],
            "on": {"DUE": {"target": "#linger.stopping"}}},
        "stopping": {"type": "final"}},
}

PONG = {
    "id": "ws", "strict": True, "strictTargets": True, "strictConfig": True,
    "actionErrorPolicy": "rollback", "guardErrorPolicy": "raise",
    "initial": "live", "context": {},
    "states": {"live": {"on": {"PONG": {"actions": ["rearm"]}}}},
}


def handles(i):
    return sum(len(v) for v in getattr(i, "_timer_handles", {}).values())


def mk(cfg, actions):
    return create_machine(json.loads(json.dumps(cfg)),
                          logic=MachineLogic(actions=actions, strict=True),
                          strict_targets=True, strict_config=True)


# ----------------------------------------------------------------- #218 ---
def heartbeat_sync():
    box = {"n": 0}
    i = SyncInterpreter(mk(HEART, {"bump": lambda *a: box.__setitem__(
        "n", box["n"] + 1)}), clock=SimulatedClock())
    i.start()
    peak = handles(i)
    for _ in range(BEATS):
        i.clock.increment(50.0)
        peak = max(peak, handles(i))
    rec("218/sync/beats", box["n"] >= BEATS - 5, "%d/%d" % (box["n"], BEATS))
    rec("218/sync/handles-flat", peak <= 1, "peak=%d" % peak)
    i.send("STOP")
    rec("218/sync/cancel-releases", handles(i) == 0, "h=%d" % handles(i))
    try:
        i.stop()
    except Exception:
        pass


async def heartbeat_async():
    box = {"n": 0}
    i = Interpreter(mk(HEART, {"bump": lambda *a: box.__setitem__(
        "n", box["n"] + 1)}), clock=SimulatedClock(),
        max_queue_size=256, overflow_policy=OverflowPolicy.RAISE)
    await i.start()
    await asyncio.sleep(0.05)
    peak = handles(i)
    for _ in range(BEATS):
        await i.clock.increment(50.0)
        await asyncio.sleep(0.002)
        peak = max(peak, handles(i))
    rec("218/async/beats", box["n"] >= BEATS - 5, "%d/%d" % (box["n"], BEATS))
    rec("218/async/handles-flat", peak <= 1, "peak=%d" % peak)
    rec("218/async/no-chain-trip", i.chain_trips == 0,
        "chain_trips=%d" % i.chain_trips)
    await asyncio.wait_for(i.send("STOP"), 5)
    await asyncio.sleep(0.05)
    rec("218/async/cancel-releases", handles(i) == 0, "h=%d" % handles(i))
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass


# ----------------------------------------------------------------- #221 ---
def js(b):
    return b if isinstance(b, str) else json.dumps(b)


def dj(b):
    return json.loads(b) if isinstance(b, str) else b


async def compaction():
    i = Interpreter(mk(LINGER, {}), clock=SimulatedClock(),
                    max_queue_size=64, overflow_policy=OverflowPolicy.RAISE)
    await i.start(); await asyncio.sleep(0.05)
    await asyncio.wait_for(i.send("ARM"), 5); await asyncio.sleep(0.05)
    await i.clock.increment(10000.0); await asyncio.sleep(0.05)
    blob = i.get_persisted_snapshot()
    sched = dj(blob).get("scheduled_sends") or []
    rec("221/armed-deadline-persisted",
        dj(blob).get("version") == 3 and len(sched) == 1, json.dumps(sched))
    await i.stop()
    # two compaction hops: load + re-persist WITHOUT start()
    cur = js(blob)
    for hop in (1, 2):
        j = Interpreter.from_snapshot(cur, mk(LINGER, {}),
                                      clock=SimulatedClock(),
                                      minimum_version=3)
        cur = js(j.get_persisted_snapshot())
        got = dj(cur).get("scheduled_sends") or []
        rec("221/hop%d-keeps-deadline" % hop, got == sched, json.dumps(got))
    k = Interpreter.from_snapshot(cur, mk(LINGER, {}),
                                  clock=SimulatedClock(), minimum_version=3)
    await k.start(); await asyncio.sleep(0.05)
    await k.clock.increment(19000.0); await asyncio.sleep(0.05)
    mid = sorted(k.current_state_ids)
    await k.clock.increment(2000.0); await asyncio.sleep(0.05)
    rec("221/remaining-20s-honoured",
        mid == ["linger.lingering"] and
        sorted(k.current_state_ids) == ["linger.stopping"],
        "+19s=%s +21s=%s" % (mid, sorted(k.current_state_ids)))
    try:
        await asyncio.wait_for(k.stop(), 5)
    except Exception:
        pass


# ----------------------------------------------------------------- #219 ---
def reentrant_sync():
    seen = []

    def rearm(i, ctx, e, ad):
        return i.send("PONG", wait=True)

    i = SyncInterpreter(mk(PONG, {"rearm": rearm}), clock=SimulatedClock())
    exc = None
    i.start()
    try:
        i.send("PONG")
    except Exception as e:
        exc = e
    rec("219/sync/refused-not-hung",
        isinstance(exc, ReentrantWaitError) or i.status == "running",
        "raised=%r status=%s" % (exc, i.status))
    try:
        i.stop()
    except Exception:
        pass


async def reentrant_async():
    async def rearm(i, ctx, e, ad):
        return await i.send("PONG", wait=True)

    i = Interpreter(mk(PONG, {"rearm": rearm}), clock=SimulatedClock(),
                    max_queue_size=64, overflow_policy=OverflowPolicy.RAISE)
    await i.start(); await asyncio.sleep(0.05)
    hung = False
    try:
        await asyncio.wait_for(i.send("PONG", wait=True), 10)
    except asyncio.TimeoutError:
        hung = True
    except Exception:
        pass
    await asyncio.sleep(0.05)
    rec("219/async/refused-not-hung", not hung and i.status == "running",
        "hung=%s status=%s" % (hung, i.status))
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass


async def main():
    await heartbeat_async()
    await compaction()
    await reentrant_async()


heartbeat_sync()
reentrant_sync()
asyncio.run(main())
print("\n%d FAIL: %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
