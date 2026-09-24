"""STANDALONE: engine-parity controls for the n1 findings (#213 re-arm,
#214 lane restore).  Both engines; live-baseline control vs restored.
"""

import asyncio
import json
import time

from xstate_statemachine import create_machine, Interpreter, MachineLogic
from xstate_statemachine.sync_interpreter import SyncInterpreter
from xstate_statemachine.persistence import structure_hash

CFG = {
    "id": "h",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {
            "entry": [{"type": "raise",
                       "params": {"event": "PONG", "delay": 150}}],
            "on": {"PONG": {"target": "b"}},
        },
        "b": {},
    },
}


def sync_live():
    m = create_machine(dict(CFG))
    it = SyncInterpreter(m).start()
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 1.0:
        if "h.b" in it.current_state_ids:
            break
        time.sleep(0.005)
    r = ("sync LIVE delayed raise fires", "h.b" in it.current_state_ids,
         "%.3fs" % (time.perf_counter() - t0))
    it.stop()
    return r


def sync_restored():
    m = create_machine(dict(CFG))
    it = SyncInterpreter(m).start()
    snap = json.loads(it.get_snapshot())
    it.stop()
    ss = snap.get("scheduled_sends") or []
    it2 = SyncInterpreter.from_snapshot(json.dumps(snap), m).start()
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 1.5:
        if "h.b" in it2.current_state_ids:
            break
        time.sleep(0.005)
    r = ("sync RESTORED scheduled_sends persisted", len(ss),
         "rearmed_fired", "h.b" in it2.current_state_ids,
         "%.3fs" % (time.perf_counter() - t0))
    it2.stop()
    return r


async def _async_live():
    m = create_machine(dict(CFG))
    it = await Interpreter(m).start()
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 1.0:
        if "h.b" in it.current_state_ids:
            break
        await asyncio.sleep(0.005)
    r = ("async LIVE delayed raise fires", "h.b" in it.current_state_ids,
         "%.3fs" % (time.perf_counter() - t0))
    await it.stop()
    return r


async def _async_restored():
    m = create_machine(dict(CFG))
    it = await Interpreter(m).start()
    snap = json.loads(it.get_snapshot())
    await it.stop()
    ss = snap.get("scheduled_sends") or []
    it2 = await Interpreter.from_snapshot(json.dumps(snap), m).start()
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 1.5:
        if "h.b" in it2.current_state_ids:
            break
        await asyncio.sleep(0.005)
    r = ("async RESTORED scheduled_sends persisted", len(ss),
         "rearmed_fired", "h.b" in it2.current_state_ids,
         "%.3fs" % (time.perf_counter() - t0))
    await it2.stop()
    return r


# ---- lane restore ordering, async engine -------------------------------
def lane_cfg():
    return {
        "id": "l",
        "initial": "w",
        "context": {"seen": []},
        "states": {
            "w": {
                "on": {
                    "EXT": {"actions": ["rec"]},
                    "after.1000.l.w": {"actions": ["rec"]},
                }
            }
        },
    }


def rec(i, ctx, e, ad):
    ctx["seen"].append(e.type)


def lane_snapshot(m):
    return {
        "version": 3, "machine_id": m.id, "machine_hash": structure_hash(m),
        "taken_at": time.time(), "status": "running",
        "context": {"seen": []}, "state_ids": ["l.w"], "value": "w",
        "configuration": ["l", "l.w"], "output": None, "error": None,
        "pending_events": [
            {"kind": "event", "type": "EXT", "lane": "inbox"},
            {"kind": "after", "type": "after.1000.l.w", "engine": True,
             "lane": "priority"},
        ],
        "deferred": [], "scheduled_sends": [], "history": {},
        "actors": {}, "system": {},
    }


async def _async_lane():
    m = create_machine(logic=MachineLogic(actions={"rec": rec}),
                       config=lane_cfg())
    it = await Interpreter.from_snapshot(
        json.dumps(lane_snapshot(m)), m).start()
    await asyncio.sleep(0.3)
    r = ("async lane restore order", list(it.context["seen"]))
    await it.stop()
    return r


def main():
    for r in (sync_live(), sync_restored()):
        print(r, flush=True)

    async def go():
        print(await _async_live(), flush=True)
        print(await _async_restored(), flush=True)
        print(await _async_lane(), flush=True)

    asyncio.run(go())


if __name__ == "__main__":
    main()
