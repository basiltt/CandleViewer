# -*- coding: utf-8 -*-
"""v0.9.1 contract check: drain_pending -> persist -> stop -> restore -> start.

STANDALONE: stdlib + xstate_statemachine only. Reads the corrected catalogue
JSON (B11-B15) by absolute path; everything else is inline.
Run:  python -W error::RuntimeWarning h1_shutdown_recipe.py [async|def]
"""
import asyncio, copy, json, pathlib, sys
from xstate_statemachine import (Interpreter, MachineLogic, OverflowPolicy,
                                 create_machine)
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase
from xstate_statemachine.actions import is_builtin
from xstate_statemachine.exceptions import InterpreterStoppedError

CORPUS = pathlib.Path(r"<workspace>/"
                      r"CandleViewer/docs/research/xstate/battle-v0.9.0/contracts")
STYLE = sys.argv[1] if len(sys.argv) > 1 else "async"
FAILS, N = [], [0]


def rec(k, ok, note=""):
    N[0] += 1
    print(("PASS " if ok else "FAIL ") + "[%s] %s  %s" % (STYLE, k, note), flush=True)
    if not ok:
        FAILS.append(k)


def names(c):
    A, G, S = set(), set(), set()
    def acts(v):
        for x in (v if isinstance(v, list) else [v] if v else []):
            A.add(x if isinstance(x, str) else x.get("type"))
    def tr(v):
        for t in (v if isinstance(v, list) else [v] if v else []):
            if isinstance(t, dict):
                acts(t.get("actions"))
                if isinstance(t.get("guard"), str):
                    G.add(t["guard"])
    def walk(n):
        acts(n.get("entry")); acts(n.get("exit"))
        for v in (n.get("on") or {}).values(): tr(v)
        tr(n.get("always"))
        for v in (n.get("after") or {}).values(): tr(v)
        inv = n.get("invoke")
        for i in (inv if isinstance(inv, list) else [inv] if inv else []):
            S.add(i["src"]); tr(i.get("onDone")); tr(i.get("onError"))
        for s in (n.get("states") or {}).values(): walk(s)
    walk(c)
    return A, G, S


def logic(c, guards):
    A, G, S = names(c)
    def mk_a(n):
        def f(i, ctx, e, a): pass
        f.__name__ = n; return f
    def mk_g(n):
        def g(ctx, e):
            v = guards.get(n, False)
            return bool(v(ctx, e)) if callable(v) else bool(v)
        g.__name__ = n; return g
    def mk_s(n):
        if STYLE == "async":
            async def s(i, ctx, e): return {"ok": True}
        else:
            def s(i, ctx, e): return {"ok": True}
        s.__name__ = n; return s
    return MachineLogic(
        actions={n: mk_a(n) for n in A if n and not is_builtin(n)
                 and not n.startswith("spawn_")},
        guards={n: mk_g(n) for n in G}, services={n: mk_s(n) for n in S},
        strict=True)


class Hooks(PluginBase):
    def __init__(self):
        self.starts, self.restored, self.seen, self.dropped_rc = 0, [], [], 0
        self.unhandled, self.errors = [], []
    def on_interpreter_start(self, i):
        self.starts += 1; self.restored.append(i.restored_from_snapshot)
    def on_event_received(self, i, e):
        p = getattr(e, "payload", None) or {}
        if "seq" in p: self.seen.append(p["seq"])
    def on_receipt_dropped(self, i, t): self.dropped_rc += 1
    def on_unhandled_event(self, i, e, ids, d): self.unhandled.append((e.type, d))
    def on_error(self, i, e): self.errors.append(repr(e))


def machine(bid, guards):
    c = json.loads((CORPUS / (bid + ".machine.json")).read_text("utf-8"))
    c["strictConfig"] = True
    return create_machine(copy.deepcopy(c), logic=logic(c, guards),
                          strict_targets=True, strict_config=True)


async def settle(n=8):
    for _ in range(n):
        await asyncio.sleep(0.02)


def ids(i):
    return sorted(i.current_state_ids)


T = True
SCEN = {  # bid: (guards, boot events, steady-state event, expected steady ids)
    "B11": ({"reasons_remain": T, "all_streams_healthy": T},
            ["REASON_ADDED"], "GAP_DETECTED", ["recording.recording"]),
    "B12": ({}, ["PREPARE", "PLAY"], "SET_SPEED", ["replay.playing"]),
    "B13": ({"connection_budget_exhausted": False, "is_private": False},
            ["CONNECT"], "PONG", ["ws_conn.live"]),
    "B14": ({}, ["SUBSCRIBE", "SNAPSHOT"], "DELTA", None),
    "B15": ({}, [], "MARK_UPDATE", ["paper_account.active"]),
}
K_IN, K_PRI = 5, 3


async def one(bid):
    guards, boot, ev, want = SCEN[bid]
    m = machine(bid, guards)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=64,
                    overflow_policy=OverflowPolicy.RAISE)
    h = Hooks(); i.use(h)
    await i.start()
    rec(bid + ".boot.start_hook", h.restored == [False], str(h.restored))
    for b in boot:
        await i.send(b, wait=True); await settle()
    steady = ids(i)
    rec(bid + ".steady", want is None or steady == want, str(steady))
    # --- enqueue work WITHOUT yielding to the run loop, both lanes -------
    for s in range(K_IN):
        i.send(ev, seq=s)                       # eager put; awaitable dropped
    for s in range(K_IN, K_IN + K_PRI):
        i.send_priority(ev, wait=False, seq=s)
    aw = i.send(ev, wait=True, seq=99)          # eager put; receipt pending
    pre = list(h.seen)                          # nothing yielded yet
    drained = await i.drain_pending()           # no internal await -> no yield
    waiter = asyncio.ensure_future(aw)
    await asyncio.sleep(0)
    try:
        r = await asyncio.wait_for(waiter, 2)   # #239: Receipt.error, no raise
        wr = type(r.error).__name__ if r is not None and r.error else "clean:%r" % (r,)
        if r is not None and r.changed:
            wr += "+changed"
    except InterpreterStoppedError:
        wr = "InterpreterStoppedError"
    except asyncio.TimeoutError:
        wr = "HANG"
    rec(bid + ".drain.waiter_failed", wr == "InterpreterStoppedError", wr)
    dseq = [e.payload.get("seq") for e in drained]
    rec(bid + ".drain.priority_first",
        dseq[:K_PRI] == list(range(K_IN, K_IN + K_PRI)), str(dseq))
    rec(bid + ".drain.disjoint_complete",
        sorted(pre + dseq) == list(range(K_IN + K_PRI)) + [99]
        and not set(pre) & set(dseq), "pre=%s drained=%s" % (pre, dseq))
    rec(bid + ".pre.chain0_drop0", i.chain_trips == 0 and i.dropped_receipts
        == 0 and h.dropped_rc == 0, "ct=%s dr=%s" % (i.chain_trips, i.dropped_receipts))
    blob = i.get_persisted_snapshot()
    if not isinstance(blob, str):
        blob = json.dumps(blob)
    await i.stop()
    # --- restore on a fresh machine with a plugin passed via plugins= ----
    h2 = Hooks()
    j = Interpreter.from_snapshot(blob, machine(bid, guards),
                                  clock=SimulatedClock(), minimum_version=3,
                                  plugins=[h2])
    await j.start(); await settle()
    rec(bid + ".restore.start_hook_restored",
        h2.starts == 1 and h2.restored == [True], "starts=%s %s" % (h2.starts, h2.restored))
    rec(bid + ".restore.same_state", ids(j) == steady, str(ids(j)))
    for e in drained:                           # replay the persisted work
        await j.send(e.type, wait=True, **e.payload)
    await settle()
    rec(bid + ".replay.exactly_once",
        sorted(pre + h2.seen) == list(range(K_IN + K_PRI)) + [99]
        and len(h2.seen) == len(set(h2.seen)), "post=%s" % h2.seen)
    rec(bid + ".post.chain0_drop0_noerr",
        j.chain_trips == 0 and j.dropped_receipts == 0 and not h2.errors
        and j.status == "running", "ct=%s dr=%s st=%s err=%s" % (
            j.chain_trips, j.dropped_receipts, j.status, h2.errors[:1]))
    await j.stop()


async def main():
    for bid in SCEN:
        try:
            await asyncio.wait_for(one(bid), 25)
        except Exception as e:
            rec(bid + ".EXC", False, repr(e)[:200])
    print("--- %d checks, %d FAIL: %s" % (N[0], len(FAILS), FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
