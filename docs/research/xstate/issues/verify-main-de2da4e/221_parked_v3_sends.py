"""VERIFY #221 on de2da4e (STANDALONE; stdlib + xstate_statemachine only).

Claim: restore -> re-persist -> restore -> start() fires the parked
scheduled send EXACTLY ONCE, with the correct remaining delay, on both
engines, both action spellings (sync only supports `def`).

Exit 0 = all cells pass.
"""
import asyncio
import json
import sys

from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine
from xstate_statemachine.clock import SimulatedClock

CFG = {
    "id": "sla",
    "initial": "a",
    "states": {
        "a": {
            "entry": [
                {
                    "type": "raise",
                    "params": {"event": "PONG", "delay": 60000, "id": "sla"},
                },
                "noop",
            ],
            "on": {"PONG": "b"},
        },
        "b": {},
    },
}


def _mk(logic):
    return create_machine(json.loads(json.dumps(CFG)), logic=logic)


def _sync_hop1(logic):
    clock = SimulatedClock()
    s = SyncInterpreter(_mk(logic), clock=clock)
    s.start()
    clock.increment(1000)
    blob = s.get_persisted_snapshot()
    s.stop()
    return blob


async def _async_hop1(logic):
    clock = SimulatedClock()
    i = await Interpreter(_mk(logic), clock=clock).start()
    await clock.increment(1000)
    blob = i.get_persisted_snapshot()
    await i.stop()
    return blob


def cell_sync_no_start_repersist_roundtrips():
    logic = MachineLogic(actions={"noop": lambda i, c, e, a: None})
    blob = _sync_hop1(logic)
    ok = len(blob["scheduled_sends"]) == 1 and blob["scheduled_sends"][0]["send_id"] == "sla"
    ok = ok and abs(blob["scheduled_sends"][0]["remaining_ms"] - 59000.0) < 1.0

    r = SyncInterpreter.from_snapshot(json.dumps(blob), _mk(logic))
    blob2 = r.get_persisted_snapshot()
    ok = ok and blob2["scheduled_sends"] == blob["scheduled_sends"]

    r2 = SyncInterpreter.from_snapshot(json.dumps(blob2), _mk(logic))
    ok = ok and r2.get_persisted_snapshot()["scheduled_sends"] == blob["scheduled_sends"]
    return ok, blob


async def cell_async_no_start_repersist_roundtrips(kind):
    if kind == "async":
        async def noop(i, c, e, a):
            pass
    else:
        def noop(i, c, e, a):
            pass

    logic = MachineLogic(actions={"noop": noop})
    blob = await _async_hop1(logic)
    ok = len(blob["scheduled_sends"]) == 1 and blob["scheduled_sends"][0]["send_id"] == "sla"
    ok = ok and abs(blob["scheduled_sends"][0]["remaining_ms"] - 59000.0) < 1.0

    r = Interpreter.from_snapshot(json.dumps(blob), _mk(logic))
    blob2 = r.get_persisted_snapshot()
    ok = ok and blob2["scheduled_sends"] == blob["scheduled_sends"]

    r2 = Interpreter.from_snapshot(json.dumps(blob2), _mk(logic))
    ok = ok and r2.get_persisted_snapshot()["scheduled_sends"] == blob["scheduled_sends"]
    return ok, blob


def cell_sync_started_restore_fires_exactly_once():
    logic = MachineLogic(actions={"noop": lambda i, c, e, a: None})
    blob = _sync_hop1(logic)
    clock = SimulatedClock()
    r = SyncInterpreter.from_snapshot(json.dumps(blob), _mk(logic), clock=clock)
    r.start()
    recs = r.get_persisted_snapshot()["scheduled_sends"]
    ok = len(recs) == 1 and abs(recs[0]["remaining_ms"] - 59000.0) < 1.0
    clock.increment(59000)
    ok = ok and r.value == "b"
    ok = ok and r.get_persisted_snapshot()["scheduled_sends"] == []
    r.stop()
    return ok


async def cell_async_started_restore_fires_exactly_once(kind):
    if kind == "async":
        async def noop(i, c, e, a):
            pass
    else:
        def noop(i, c, e, a):
            pass

    logic = MachineLogic(actions={"noop": noop})
    blob = await _async_hop1(logic)
    clock = SimulatedClock()
    r = Interpreter.from_snapshot(json.dumps(blob), _mk(logic), clock=clock)
    await r.start()
    recs = r.get_persisted_snapshot()["scheduled_sends"]
    ok = len(recs) == 1 and abs(recs[0]["remaining_ms"] - 59000.0) < 1.0
    await clock.increment(59000)
    ok = ok and r.value == "b"
    ok = ok and r.get_persisted_snapshot()["scheduled_sends"] == []
    await r.stop()
    return ok


def main():
    fail = False

    ok, blob = cell_sync_no_start_repersist_roundtrips()
    print(f"[sync no-start repersist round-trips verbatim] {'OK' if ok else 'FAIL'}")
    fail = fail or not ok

    for kind in ("def", "async"):
        ok, blob = asyncio.run(cell_async_no_start_repersist_roundtrips(kind))
        print(f"[async no-start repersist round-trips verbatim kind={kind}] {'OK' if ok else 'FAIL'}")
        fail = fail or not ok

    ok = cell_sync_started_restore_fires_exactly_once()
    print(f"[sync started-restore fires exactly once, right delay] {'OK' if ok else 'FAIL'}")
    fail = fail or not ok

    for kind in ("def", "async"):
        ok = asyncio.run(cell_async_started_restore_fires_exactly_once(kind))
        print(f"[async started-restore fires exactly once, right delay kind={kind}] {'OK' if ok else 'FAIL'}")
        fail = fail or not ok

    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
