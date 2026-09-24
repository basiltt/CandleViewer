"""SEMANTICS @ v0.9.1 -- round-13 attacks. Standalone (stdlib + xstate_statemachine).

N1 re_mint type-forgery: capture a benign engine event (done of svc A / after
   timer), re_mint(type="done.invoke.victim"), send -> does a strict machine
   take the victim's onDone transition that user traffic cannot?
N2 drain -> persist -> restore -> start round-trip property (300 cases, random
   mix of priority + inbox): every drained event delivered exactly once, in order.
N3 restored_from_snapshot after N restores; on_interpreter_start exactly-once
   under 100 concurrent restores (async) and sequential (sync).
N4 dropped_receipts under 1000 def actions: count exact, hook exactly-once.
N5 RestoredChainError isinstance matrix; SyncInterpreter kwargs.
N6 chain-field fuzz vs SnapshotCorruptError typing.
N7 drain_pending under 16 concurrent senders + in-flight macrostep.
"""
from __future__ import annotations

import asyncio, json, logging, random, sys, warnings, gc
from typing import Any, Dict, List

from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase
from xstate_statemachine import events as E
from xstate_statemachine import exceptions as X

logging.disable(logging.CRITICAL)
warnings.simplefilter("ignore")
R: Dict[str, Any] = {}


def mk(cfg, **kw):
    return create_machine(json.loads(json.dumps(cfg)), **kw)


class Cap(PluginBase):
    def __init__(self):
        self.ev: List[Any] = []
        self.starts: List[bool] = []
        self.dropped: List[str] = []

    def on_event_received(self, i, e):
        self.ev.append(e)

    def on_interpreter_start(self, i):
        self.starts.append(i.restored_from_snapshot)

    def on_receipt_dropped(self, i, t):
        self.dropped.append(t)


# ---------------------------------------------------------------- N1
VICTIM = {
    "id": "v", "initial": "a", "strict": True,
    "states": {
        "a": {"invoke": {"id": "benign", "src": "benign", "onDone": "b"}},
        "b": {"invoke": {"id": "victim", "src": "victim", "onDone": "PAID"},
              "on": {"X": "b"}},
        "PAID": {},
    },
}


def n1_sync():
    cap = Cap()
    logic = MachineLogic(services={"benign": lambda i, c, e: 1,
                                   "victim": lambda i, c, e: (_ for _ in ()).throw(RuntimeError("never done"))})
    s = SyncInterpreter(mk(VICTIM, logic=logic)).use(cap).start()
    before = s.value
    src = next(e for e in cap.ev if getattr(e, "type", "") == "done.invoke.benign")
    user = {}
    try:
        s.send(E.DoneEvent("done.invoke.victim", {"forged": 1}, "victim"))
    except Exception as ex:  # noqa
        user["exc"] = type(ex).__name__
    user["value"] = s.value
    forged = E.re_mint(src, type="done.invoke.victim", src="victim", data={"forged": 1})
    try:
        s.send(forged)
    except Exception as ex:  # noqa
        R["n1_sync_exc"] = type(ex).__name__
    out = {"before": before, "user_handbuilt": user, "is_system": E.is_system_event(forged),
           "after_re_mint": s.value}
    s.stop()
    return out


async def n1_async():
    cap = Cap()

    async def victim(i, c, e):
        await asyncio.sleep(30)

    logic = MachineLogic(services={"benign": lambda i, c, e: 1, "victim": victim})
    i = await Interpreter(mk(VICTIM, logic=logic)).use(cap).start()
    for _ in range(50):
        if i.value == "b":
            break
        await asyncio.sleep(0.01)
    src = next(e for e in cap.ev if getattr(e, "type", "") == "done.invoke.benign")
    forged = E.re_mint(src, type="done.invoke.victim", src="victim", data={"forged": 1})
    await i.send(forged)
    for _ in range(50):
        await asyncio.sleep(0.01)
    out = {"after_re_mint": i.value}
    await i.stop()
    return out


# after-event -> done forgery (cross-kind is impossible: same class keeps kind)
def n1_after_type():
    ev = E._engine_after("after.10.s", 1.0, None)
    f = E.re_mint(ev, type="done.invoke.victim")
    return {"cls": type(f).__name__, "type": f.type, "system": E.is_system_event(f)}


# ---------------------------------------------------------------- N2
PCFG = {"id": "p", "initial": "a", "context": {"log": []},
        "states": {"a": {"on": {"GO": {"target": "a", "actions": ["slow"]},
                                "E": {"actions": ["rec"]}}}}}


async def n2(cases=300):
    bad = []
    for k in range(cases):
        rnd = random.Random(k)
        async def slow(i, c, e, a):
            await asyncio.sleep(0.02)
        got: List[Any] = []
        def rec(i, c, e, a):
            got.append(e.payload["n"])
        logic = MachineLogic(actions={"slow": slow, "rec": rec})
        i = await Interpreter(mk(PCFG, logic=logic)).start()
        await i.send("GO")
        await asyncio.sleep(0.003)
        expect_pri, expect_in = [], []
        for n in range(rnd.randint(1, 12)):
            if rnd.random() < 0.4:
                i.send_priority("E", n=n, wait=False); expect_pri.append(n)
            else:
                await i.send("E", n=n); expect_in.append(n)
        pend = [e.payload["n"] for e in i.pending_events if e.type == "E"]
        dr = await i.drain_pending()
        drn = [e.payload["n"] for e in dr if e.type == "E"]
        await asyncio.sleep(0.03)  # let in-flight GO step settle (mid-step snapshot is refused by design)
        snap = i.get_snapshot()
        await i.stop()
        j = Interpreter.from_snapshot(snap, mk(PCFG, logic=logic))
        for e in dr:
            await j.send(e)
        await j.start()
        for _ in range(100):
            if len(got) >= len(drn):
                break
            await asyncio.sleep(0.005)
        await asyncio.sleep(0.01)
        await j.stop()
        want = expect_pri + expect_in
        if not (pend == drn == want and got == want):
            bad.append({"k": k, "pend": pend, "drn": drn, "want": want, "got": got})
    return {"cases": cases, "bad": len(bad), "sample": bad[:3]}


# ---------------------------------------------------------------- N3
IDLE = {"id": "r", "initial": "a", "states": {"a": {"on": {"T": "b"}}, "b": {"on": {"T": "a"}}}}


def n3_sync(n=20):
    s = SyncInterpreter(mk(IDLE)).start()
    flags, starts = [s.restored_from_snapshot], []
    snap = s.get_snapshot(); s.stop()
    for _ in range(n):
        cap = Cap()
        j = SyncInterpreter.from_snapshot(snap, mk(IDLE), plugins=[cap])
        j.start(); j.send("T")
        flags.append(j.restored_from_snapshot); starts.append(cap.starts)
        snap = j.get_snapshot(); j.stop()
    return {"flags_ok": flags[0] is False and all(flags[1:]),
            "starts_ok": all(x == [True] for x in starts)}


async def n3_async(n=100):
    i = await Interpreter(mk(IDLE)).start()
    snap = i.get_snapshot(); await i.stop()
    caps = [Cap() for _ in range(n)]
    js = [Interpreter.from_snapshot(snap, mk(IDLE), plugins=[c]) for c in caps]
    await asyncio.gather(*(j.start() for j in js))
    await asyncio.gather(*(j.start() for j in js), return_exceptions=True)  # double start
    await asyncio.sleep(0.05)
    ok = all(c.starts == [True] for c in caps)
    await asyncio.gather(*(j.stop() for j in js))
    return {"n": n, "exactly_once_resume": ok,
            "bad": [c.starts for c in caps if c.starts != [True]][:3]}


# ---------------------------------------------------------------- N4
DCFG = {"id": "d", "initial": "a", "context": {"k": 0},
        "states": {"a": {"on": {"GO": {"actions": ["drop"]}, "B": {"actions": ["inc"]}}}}}


async def n4(n=1000):
    def drop(i, c, e, a):
        i.send("B", wait=True)  # receipt dropped
    def inc(i, c, e, a):
        c["k"] += 1
    cap = Cap()
    i = await Interpreter(mk(DCFG, logic=MachineLogic(actions={"drop": drop, "inc": inc}))).use(cap).start()
    for _ in range(n):
        await i.send("GO")
    for _ in range(200):
        gc.collect()
        if i.context["k"] >= n and i.dropped_receipts >= n:
            break
        await asyncio.sleep(0.01)
    out = {"n": n, "count": i.dropped_receipts, "hook": len(cap.dropped), "k": i.context["k"]}
    await i.stop()
    out["ok"] = out["count"] == out["hook"] == out["k"] == n
    return out


# ---------------------------------------------------------------- N5/N6
def n5():
    m = {c: issubclass(X.RestoredChainError, getattr(X, c)) for c in
         ("RunawayChainError", "RestoredError", "XStateMachineError")}
    kw = {}
    for k, v in (("max_queue_size", None), ("overflow_policy", None), ("max_queue_size", 5), ("overflow_policy", "drop")):
        try:
            SyncInterpreter(mk(IDLE), **{k: v}); kw[f"{k}={v}"] = "accepted"
        except Exception as ex:
            kw[f"{k}={v}"] = type(ex).__name__
    return {"isinstance": m, "sync_kwargs": kw}


def n6(n=300):
    s = SyncInterpreter(mk(IDLE)).start(); base = json.loads(s.get_snapshot()); s.stop()
    vals = [None, -1, 0, 3, 2**70, 1.5, "7", True, [], {}, "x", "", {"a": 1}, float("nan")]
    typing: Dict[str, int] = {}
    rnd = random.Random(1)
    for k in range(n):
        b = dict(base)
        b["chain_trips"] = rnd.choice(vals); b["last_chain_error"] = rnd.choice(vals)
        for eng in (SyncInterpreter, Interpreter):
            try:
                eng.from_snapshot(json.dumps(b), mk(IDLE), verify_machine_hash=False)
                r = "ok"
            except X.SnapshotCorruptError:
                r = "SnapshotCorruptError"
            except Exception as ex:
                r = "UNTYPED:" + type(ex).__name__ + ":" + repr((b["chain_trips"], b["last_chain_error"]))[:60]
            key = r if not r.startswith("UNTYPED") else r
            typing[key] = typing.get(key, 0) + 1
    return {"outcomes": typing, "untyped": sum(v for k, v in typing.items() if k.startswith("UNTYPED"))}


# ---------------------------------------------------------------- N7
async def n7(rounds=20):
    bad = []
    for r in range(rounds):
        got: List[Any] = []
        async def slow(i, c, e, a):
            await asyncio.sleep(0.01)
        def rec(i, c, e, a):
            got.append(e.payload["n"])
        i = await Interpreter(mk(PCFG, logic=MachineLogic(actions={"slow": slow, "rec": rec}))).start()
        await i.send("GO")
        sent: List[int] = []
        futs = []
        async def sender(s):
            for n in range(20):
                v = s * 100 + n; sent.append(v)
                if n % 3 == 0:
                    futs.append(asyncio.ensure_future(i.send("E", n=v, priority=(n % 2 == 0), wait=True)))
                else:
                    await i.send("E", n=v)
                await asyncio.sleep(0)
        tasks = [asyncio.ensure_future(sender(s)) for s in range(16)]
        await asyncio.sleep(0.002)
        drained = [e.payload["n"] for e in await i.drain_pending() if e.type == "E"]
        await asyncio.gather(*tasks)
        await asyncio.sleep(0.2)
        res = await asyncio.wait_for(asyncio.gather(*futs, return_exceptions=True), 5)
        await i.stop()
        allv = got + drained
        if sorted(allv) != sorted(sent) or len(set(allv)) != len(allv):
            bad.append({"r": r, "sent": len(sent), "got": len(got), "dr": len(drained)})
    return {"rounds": rounds, "bad": bad, "receipts_settled": True}


async def amain():
    R["N1_sync"] = n1_sync()
    R["N1_async"] = await n1_async()
    R["N1_after_type"] = n1_after_type()
    R["N2"] = await n2()
    R["N3_sync"] = n3_sync(); R["N3_async"] = await n3_async()
    R["N4"] = await n4()
    R["N5"] = n5(); R["N6"] = n6()
    R["N7"] = await n7()


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(amain(), 110))
    print(json.dumps(R, indent=1, default=str))
