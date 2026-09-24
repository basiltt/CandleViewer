"""Is a delayed self-send LOST in the window between its timer firing and
the event being handled?  Snapshot exactly in that window and restore.

Deadline 40 ms; the snapshot is taken after the deadline has passed while
the loop is held busy, so the timer callback has run (record gone from
`scheduled_sends`) but the event has not been processed.
"""
import asyncio, json, os, time
from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {"id": "pk", "initial": "a", "context": {"fired": []},
       "states": {"a": {"entry": [{"type": "raise",
                                   "params": {"event": "T0", "delay": 40,
                                              "id": "s0"}}],
                        "on": {"T0": {"actions": ["fire"]}}}}}

def build():
    def fire(i, c, e, a):
        c["fired"].append(e.type)
    return create_machine(json.loads(json.dumps(CFG)),
                          logic=MachineLogic(actions={"fire": fire}))

def blob_of(i):
    b = i.get_persisted_snapshot()
    return json.loads(b) if isinstance(b, str) else b

async def one(busy_ms):
    i = Interpreter(build())
    await i.start()
    # hold the loop busy straight through the deadline, synchronously, so
    # the timer callback runs but no macrostep can drain the event.
    t0 = time.perf_counter()
    while (time.perf_counter() - t0) * 1000.0 < busy_ms:
        pass
    b = blob_of(i)
    fired_live = list(i.context["fired"])
    await i.stop()
    rec = {"busy_ms": busy_ms,
           "fired_live": fired_live,
           "scheduled_sends": len(b.get("scheduled_sends") or []),
           "pending_events": [e.get("type") for e in
                              (b.get("pending_events") or [])],
           "ctx_fired_in_blob": (b.get("context") or {}).get("fired")}
    # restore and let it run: does T0 ever arrive?
    k = Interpreter.from_snapshot(json.dumps(b), build())
    await k.start()
    await asyncio.sleep(0.30)
    rec["fired_after_restore"] = list(k.context["fired"])
    await k.stop()
    rec["LOST"] = (not rec["ctx_fired_in_blob"]
                   and rec["scheduled_sends"] == 0
                   and not rec["pending_events"]
                   and not rec["fired_after_restore"])
    return rec

async def main():
    out = []
    for busy in (10, 39, 45, 60, 80):
        for _ in range(int(os.environ.get("REP", "3"))):
            out.append(await one(busy))
    lost = [r for r in out if r["LOST"]]
    print(json.dumps({"rows": out, "n_lost": len(lost),
                      "VERDICT": "LOSS" if lost else "no-loss"}, indent=1))

asyncio.run(main())
