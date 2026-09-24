"""The p1 miss, minimised: snapshot taken AFTER a delayed self-send's timer
callback has run but BEFORE the macrostep handled the event.

The loop must be able to run callbacks (so we sleep in small awaits) while
the delivery is kept slow by a slow entry/transition action.  Question: is
the event in `pending_events`, in `scheduled_sends`, or in neither
(= silently dropped by the snapshot)?
"""
import asyncio, json, os, time
from xstate_statemachine import Interpreter, MachineLogic, create_machine

DELAY = int(os.environ.get("DELAY", "40"))
SLOW = float(os.environ.get("SLOW", "0.25"))   # seconds the handler blocks

CFG = {"id": "pk", "initial": "a", "context": {"fired": [], "enter": 0},
       "states": {"a": {"entry": [{"type": "raise",
                                   "params": {"event": "T0", "delay": DELAY,
                                              "id": "s0"}}, "slow"],
                        "on": {"T0": {"actions": ["fire"]}}}}}

def build(kind):
    def fire(i, c, e, a):
        c["fired"].append(e.type)
    if kind == "def":
        def slow(i, c, e, a):
            c["enter"] += 1
            time.sleep(SLOW)
    else:
        async def slow(i, c, e, a):
            c["enter"] += 1
            await asyncio.sleep(SLOW)
    return create_machine(json.loads(json.dumps(CFG)),
                          logic=MachineLogic(actions={"fire": fire,
                                                      "slow": slow}))

def blob_of(i):
    b = i.get_persisted_snapshot()
    return json.loads(b) if isinstance(b, str) else b

async def one(kind, at_ms):
    i = Interpreter(build(kind))
    task = asyncio.ensure_future(i.start())
    t0 = time.perf_counter()
    while (time.perf_counter() - t0) * 1000.0 < at_ms:
        await asyncio.sleep(0.002)
    b = blob_of(i)
    live = list(i.context["fired"])
    try:
        await asyncio.wait_for(task, 2)
    except Exception:
        pass
    await i.stop()
    k = Interpreter.from_snapshot(json.dumps(b), build(kind))
    await k.start()
    await asyncio.sleep(max(0.4, DELAY / 1000.0 + 0.4))
    after = list(k.context["fired"])
    await k.stop()
    return {"kind": kind, "snapshot_at_ms": at_ms, "fired_live_at_snap": live,
            "scheduled_sends": len(b.get("scheduled_sends") or []),
            "pending_events": [e.get("type") for e in
                               (b.get("pending_events") or [])],
            "deferred": len(b.get("deferred") or []),
            "ctx_fired_in_blob": (b.get("context") or {}).get("fired"),
            "fired_after_restore": after}

async def main():
    kind = os.environ.get("XS_SVC", "async")
    rows = []
    for at in (DELAY - 15, DELAY + 5, DELAY + 40, DELAY + 120):
        rows.append(await one(kind, at))
    lost = [r for r in rows
            if not r["ctx_fired_in_blob"] and r["scheduled_sends"] == 0
            and not r["pending_events"] and not r["fired_after_restore"]]
    for r in rows:
        r["LOST"] = r in lost
    print(json.dumps({"kind": kind, "delay_ms": DELAY, "slow_s": SLOW,
                      "rows": rows, "n_lost": len(lost),
                      "VERDICT": "LOSS" if lost else "no-loss"}, indent=1))

asyncio.run(main())
