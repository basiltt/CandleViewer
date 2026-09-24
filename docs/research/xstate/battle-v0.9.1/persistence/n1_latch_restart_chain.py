"""#226: the chain-trip latch across N restarts.

Count monotonic, RestoredError message intact and stable through repeated
snapshot->restore hops, clear_chain_error() keeps the count, a trip AFTER a
restore is previous+1.  Both engines, both service kinds.
"""
import asyncio, json, os
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 create_machine, RestoredError)

CFG = {"id": "cl", "initial": "idle", "context": {"n": 0},
       "maxIterations": 5,
       "states": {
           "idle": {"on": {"LOOP": "spin", "PING": {"actions": ["bump"]}}},
           "spin": {"entry": [{"type": "raise", "params": {"event": "LOOP2"}},
                              "bump"],
                    "on": {"LOOP2": "spin2"}},
           "spin2": {"entry": [{"type": "raise", "params": {"event": "LOOP"}},
                               "bump"],
                     "on": {"LOOP": "spin"}}}}

def build(kind):
    if kind == "def":
        def bump(i, c, e, a):
            c["n"] += 1
    else:
        async def bump(i, c, e, a):
            c["n"] += 1
    return create_machine(json.loads(json.dumps(CFG)),
                          logic=MachineLogic(actions={"bump": bump}))

def blob(i):
    b = i.get_persisted_snapshot()
    return b if isinstance(b, str) else json.dumps(b)

async def trip_async(i):
    try:
        await i.send("LOOP")
    except Exception:
        pass
    await asyncio.sleep(0.05)

def trip_sync(i):
    try:
        i.send("LOOP")
    except Exception:
        pass

async def run(kind, engine, hops):
    rows = []
    # the sync engine cannot run an `async def` action at all
    # (NotSupportedError), so the kind axis only applies to the async engine.
    if engine == "sync":
        kind = "def"
    m = build(kind)
    if engine == "async":
        i = Interpreter(m); await i.start(); await trip_async(i)
    else:
        i = SyncInterpreter(m); i.start(); trip_sync(i)
    first_msg = str(i.last_chain_error)
    rows.append({"stage": "live", "trips": i.chain_trips,
                 "latch_type": type(i.last_chain_error).__name__,
                 "msg_eq_first": True})
    cur = blob(i)
    if engine == "async":
        await i.stop()
    else:
        i.stop()
    for h in range(hops):
        cls = Interpreter if engine == "async" else SyncInterpreter
        j = cls.from_snapshot(cur, build("def" if engine == "sync" else kind))
        rows.append({"stage": f"restore{h}", "trips": j.chain_trips,
                     "latch_type": type(j.last_chain_error).__name__,
                     "msg_eq_first": str(j.last_chain_error) == first_msg,
                     "is_RestoredError": isinstance(j.last_chain_error,
                                                    RestoredError)})
        cur = blob(j)
    # a trip after the last restore must be previous + 1
    cls = Interpreter if engine == "async" else SyncInterpreter
    k = cls.from_snapshot(cur, build("def" if engine == "sync" else kind))
    before = k.chain_trips
    if engine == "async":
        await k.start(); await trip_async(k)
    else:
        k.start(); trip_sync(k)
    rows.append({"stage": "trip_after_restore", "trips": k.chain_trips,
                 "expected": before + 1,
                 "latch_type": type(k.last_chain_error).__name__})
    k.clear_chain_error()
    rows.append({"stage": "after_clear", "trips": k.chain_trips,
                 "latch_type": type(k.last_chain_error).__name__})
    cleared_blob = blob(k)
    if engine == "async":
        await k.stop()
    else:
        k.stop()
    z = cls.from_snapshot(cleared_blob, build("def" if engine == "sync" else kind))
    rows.append({"stage": "restore_after_clear", "trips": z.chain_trips,
                 "latch_type": type(z.last_chain_error).__name__})
    return rows, first_msg

async def main():
    kind = os.environ.get("XS_SVC", "async")
    hops = int(os.environ.get("HOPS", "6"))
    out = {}
    fails = []
    for engine in ("async", "sync"):
        rows, first = await run(kind, engine, hops)
        out[engine] = {"first_msg": first, "rows": rows}
        live = rows[0]["trips"]
        for r in rows[1:1 + hops]:
            if r["trips"] != live:
                fails.append(f"{engine} {r['stage']} count drift")
            if not r["msg_eq_first"]:
                fails.append(f"{engine} {r['stage']} message drift")
            if not r["is_RestoredError"]:
                fails.append(f"{engine} {r['stage']} not RestoredError")
        t = [r for r in rows if r["stage"] == "trip_after_restore"][0]
        if t["trips"] != t["expected"]:
            fails.append(f"{engine} post-restore trip not monotonic "
                         f"{t['trips']} != {t['expected']}")
        c = [r for r in rows if r["stage"] == "after_clear"][0]
        if c["latch_type"] != "NoneType" or c["trips"] != t["trips"]:
            fails.append(f"{engine} clear_chain_error broke count/latch")
        rz = [r for r in rows if r["stage"] == "restore_after_clear"][0]
        if rz["latch_type"] != "NoneType" or rz["trips"] != t["trips"]:
            fails.append(f"{engine} cleared latch resurrected on restore")
    print(json.dumps({"kind": kind, "hops": hops, "out": out, "fails": fails,
                      "VERDICT": "PASS" if not fails else "FAIL"}, indent=1))

asyncio.run(main())
