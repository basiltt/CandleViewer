"""STANDALONE. v0.9.1 persistence/concurrency/semantics attacks (XS_SVC=async|def).
A drain->persist->restore->start round-trip, 300 cases, priority + inbox
B restored_from_snapshot after N=10 chained restores
C chain field fuzz vs SnapshotCorruptError
D drain_pending under 16 concurrent senders + in-flight macrostep
E dropped_receipts under 1000 dropped receipts (count exact, hook once each)
F on_interpreter_start exactly once under 100 concurrent restores
G RestoredChainError isinstance matrix; H SyncInterpreter kwargs"""
import asyncio, gc, json, os, random, sys, warnings
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic, create_machine,
                                 PluginBase, SnapshotCorruptError, RunawayChainError,
                                 RestoredError, InterpreterStoppedError)
from xstate_statemachine.exceptions import RestoredChainError
import logging; logging.disable(logging.CRITICAL)
warnings.simplefilter("ignore")
KIND = os.environ.get("XS_SVC", "async")
R = {}

def act(fn_sync, fn_async):
    return fn_sync if KIND == "def" else fn_async

def mk(hold=0.05):
    def cnt_s(i, c, e, a): c.setdefault("seen", []).append(e.type)
    async def cnt_a(i, c, e, a): c.setdefault("seen", []).append(e.type)
    async def slow(i, c, e, a): await asyncio.sleep(hold)
    ev = {f"E{k}": {"actions": "cnt"} for k in range(40)}
    cfg = {"id": "m", "initial": "a", "context": {"seen": []}, "states": {
        "a": {"on": {"GO": {"target": "b", "actions": "slow"}, **ev}},
        "b": {"on": {"GO": {"target": "b", "actions": "slow"}, **ev}}}}
    return create_machine(cfg, logic=MachineLogic(actions={"cnt": act(cnt_s, cnt_a), "slow": slow}))

def blob(i):
    b = i.get_persisted_snapshot(); return b if isinstance(b, str) else json.dumps(b)

async def A():
    fails = 0; rnd = random.Random(7)
    for case in range(300):
        i = await Interpreter(mk(0.02)).start()
        await i.send("GO"); await asyncio.sleep(0.003)
        sent = []
        for k in range(rnd.randint(1, 8)):
            t = f"E{rnd.randrange(40)}"; sent.append(t)
            if rnd.random() < 0.5: i.send_priority(t, wait=False)
            else: await i.send(t)
        view = [e.type for e in i.pending_events]
        drained = [e.type for e in await i.drain_pending()]
        await asyncio.sleep(0.04)  # let the in-flight step settle
        snap = blob(i); await i.stop()
        k = Interpreter.from_snapshot(snap, mk(0.0)); await k.start()
        for t in drained: await k.send(t)
        await asyncio.sleep(0.01)
        seen = list(k.context["seen"]); await k.stop()
        if drained != view or sorted(seen) != sorted(sent) or len(seen) != len(sent):
            fails += 1
            if fails < 4: R.setdefault("A_ex", []).append([sent, view, drained, seen])
    R["A_roundtrip_300_fails"] = fails

async def B():
    i = await Interpreter(mk()).start(); flags = [i.restored_from_snapshot]
    for n in range(10):
        s = blob(i); await i.stop()
        i = Interpreter.from_snapshot(s, mk()); await i.start(); flags.append(i.restored_from_snapshot)
    await i.stop(); R["B_flags"] = flags
    R["B_ok"] = flags == [False] + [True] * 10

async def C():
    i = await Interpreter(mk()).start(); base = json.loads(blob(i)); await i.stop()
    vals = ["NaN", [], {}, -1, 1.5, True, None, "12", "-3", 10**30, "", " 1", float("inf")]
    msgs = [None, "x", 3, [], {}, True]
    out = {}
    for v in vals:
        for m in msgs:
            b = dict(base); b["chain_trips"] = v; b["last_chain_error"] = m
            try:
                Interpreter.from_snapshot(json.dumps(b, allow_nan=True), mk()); r = "ok"
            except SnapshotCorruptError: r = "SCE"
            except Exception as x: r = "RAW:" + type(x).__name__
            out[f"{v!r}|{m!r}"] = r
    R["C_raw"] = {k: v for k, v in out.items() if v.startswith("RAW")}
    R["C_ok_cells"] = sorted(k for k, v in out.items() if v == "ok")

async def D():
    i = await Interpreter(mk(0.2)).start()
    await i.send("GO"); await asyncio.sleep(0.01)
    rec = []
    async def sender(s):
        for n in range(20):
            t = f"E{(s * 20 + n) % 40}"
            if n % 3 == 0:
                rec.append(asyncio.ensure_future(i.send(t, wait=True)))
            elif n % 3 == 1: i.send_priority(t, wait=False)
            else: await i.send(t)
            await asyncio.sleep(0)
    await asyncio.gather(*(sender(s) for s in range(16)))
    await asyncio.sleep(0.01)
    drained = await i.drain_pending()
    done, pend = await asyncio.wait(rec, timeout=3)
    errs = [type(f.result().error).__name__ if f.result().error else "ok" for f in done]
    await asyncio.sleep(0.3)
    seen = len(i.context["seen"]); await i.stop()
    R["D"] = {"sent": 320, "drained": len(drained), "processed": seen,
              "lost_or_dup": 320 - len(drained) - seen, "receipts_pending": len(pend),
              "receipt_kinds": sorted(set(errs))}

async def E():
    class Spy(PluginBase):
        def __init__(s): s.n = []
        def on_receipt_dropped(s, it, et): s.n.append(et)
    spy = Spy()
    def d_s(i, c, e, a): i.send("E1", wait=True)
    async def d_a(i, c, e, a): i.send("E1", wait=True)
    cfg = {"id": "m", "initial": "a", "states": {"a": {"on": {"X": {"actions": "d"}, "E1": {}}}}}
    i = Interpreter(create_machine(cfg, logic=MachineLogic(actions={"d": act(d_s, d_a)}))).use(spy)
    await i.start()
    for _ in range(1000): await i.send("X")
    for _ in range(50):
        await asyncio.sleep(0.01); gc.collect()
        if i.dropped_receipts >= 1000: break
    R["E"] = {"dropped_receipts": i.dropped_receipts, "hook": len(spy.n)}
    await i.stop()

async def F():
    class Spy(PluginBase):
        def __init__(s): s.st = []; s.sp = []
        def on_interpreter_start(s, it): s.st.append((id(it), it.restored_from_snapshot))
        def on_interpreter_stop(s, it): s.sp.append(id(it))
    i = await Interpreter(mk()).start(); s = blob(i); await i.stop()
    spy = Spy()
    ks = [Interpreter.from_snapshot(s, mk(), plugins=[spy]) for _ in range(100)]
    await asyncio.gather(*(k.start() for k in ks)); await asyncio.gather(*(k.stop() for k in ks))
    ids = [a for a, _ in spy.st]
    R["F"] = {"starts": len(ids), "unique": len(set(ids)), "all_restored": all(f for _, f in spy.st),
              "stops": len(spy.sp)}

def G():
    e = RestoredChainError.__mro__
    R["G"] = {"is_Runaway": issubclass(RestoredChainError, RunawayChainError),
              "is_Restored": issubclass(RestoredChainError, RestoredError)}

def H():
    m = mk(); out = {}
    for kw in ({}, {"max_queue_size": None, "overflow_policy": None}, {"max_queue_size": 5},
               {"overflow_policy": "drop"}):
        try: SyncInterpreter(m, **kw); out[str(kw)] = "ok"
        except Exception as x: out[str(kw)] = type(x).__name__
    R["H"] = out

async def main():
    for f in (A, B, C, D, E, F):
        try: await asyncio.wait_for(f(), 60)
        except Exception as x: R[f.__name__ + "_EXC"] = repr(x)
    G(); H()
    print(json.dumps(R, indent=1, default=str))

asyncio.run(main())
