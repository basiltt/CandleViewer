# -*- coding: utf-8 -*-
"""v0.9.1 round-13 surface used by the contracts. STANDALONE (stdlib + lib).
#244 dropped_receipts/on_receipt_dropped (def action), #245 Sync ValueError,
#240 sync restore hook, #241 malformed chain field, #243 latch type.
Run: python -W error::RuntimeWarning h2_r13_surface.py
"""
import asyncio, gc, json, sys
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 create_machine)
from xstate_statemachine.plugins import PluginBase
from xstate_statemachine.exceptions import (SnapshotCorruptError,
    RunawayChainError, RestoredError)

F, N = [], [0]
def rec(k, ok, n=""):
    N[0] += 1; print(("PASS " if ok else "FAIL ") + k + "  " + str(n), flush=True)
    if not ok: F.append(k)

CFG = {"id": "m", "initial": "a", "strictConfig": True, "states": {
    "a": {"on": {"GO": {"target": "b", "actions": ["fire"]}}},
    "b": {"on": {"PING": {}, "BACK": "a"}}}}

class H(PluginBase):
    def __init__(s): s.rd, s.starts = [], []
    def on_receipt_dropped(s, i, t): s.rd.append(t)
    def on_interpreter_start(s, i): s.starts.append(i.restored_from_snapshot)

def mk():
    def fire(i, c, e, a):          # plain def: cannot await its receipt
        i.send("PING", wait=True)
    return create_machine(CFG, logic=MachineLogic(actions={"fire": fire}),
                          strict_config=True)

async def amain():
    i = Interpreter(mk()); h = H(); i.use(h); await i.start()
    await i.send("GO", wait=True)
    for _ in range(10):
        gc.collect(); await asyncio.sleep(0.02)
        if i.dropped_receipts: break
    rec("244.dropped_receipts", i.dropped_receipts == 1 and h.rd == ["PING"],
        "dr=%s hook=%s" % (i.dropped_receipts, h.rd))
    await i.stop()

def smain():
    for kw in ({"max_queue_size": 8}, {"max_queue_size": 8, "overflow_policy": "raise"}):
        try:
            SyncInterpreter(mk(), **kw); r = "accepted"
        except ValueError: r = "ValueError"
        except Exception as e: r = repr(e)
        rec("245.sync.%s" % "+".join(kw), r == "ValueError", r)
    SyncInterpreter(mk(), max_queue_size=None, overflow_policy=None)
    rec("245.sync.None_ok", True)
    m = create_machine(CFG, logic=MachineLogic(actions={"fire": lambda *a: None}))
    s = SyncInterpreter(m); s.start(); s.send("GO")
    blob = s.get_persisted_snapshot()
    blob = blob if isinstance(blob, str) else json.dumps(blob)
    h = H(); j = SyncInterpreter.from_snapshot(blob, m, plugins=[h]); j.start()
    rec("240.sync.restore_hook", h.starts == [True], h.starts)
    raw = json.loads(blob)
    for bad in ("NaN", [1], {"x": 1}, True, -1):
        d = dict(raw, chain_trips=bad)
        try:
            SyncInterpreter.from_snapshot(json.dumps(d), m); r = "accepted"
        except SnapshotCorruptError: r = "SnapshotCorruptError"
        except Exception as e: r = repr(e)[:60]
        rec("241.chain_trips=%r" % (bad,), r == "SnapshotCorruptError", r)
    d = dict(raw, chain_trips=1, last_chain_error="RunawayChainError: x")
    k = SyncInterpreter.from_snapshot(json.dumps(d), m)
    e = k.last_chain_error
    rec("243.latch_isa_both", isinstance(e, RunawayChainError)
        and isinstance(e, RestoredError) and k.chain_trips == 1, repr(e)[:80])

smain(); asyncio.run(amain())
print("--- %d checks, %d FAIL: %s" % (N[0], len(F), F)); sys.exit(1 if F else 0)
