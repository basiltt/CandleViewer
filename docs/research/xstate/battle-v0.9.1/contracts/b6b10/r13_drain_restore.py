# -*- coding: utf-8 -*-
"""STANDALONE (stdlib + xstate_statemachine only). v0.9.1 round-13 checks
on B6..B10: drain_pending() -> persist -> stop() -> from_snapshot(plugins=)
-> start -> replay; every drained event delivered exactly once; restore hook
fires with restored_from_snapshot=True; chain_trips 0; dropped_receipts 0.
Usage: python -W error::RuntimeWarning r13_drain_restore.py async|def
"""
import asyncio, copy, json, pathlib, sys
from collections import Counter
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 OverflowPolicy, create_machine)
from xstate_statemachine.actions import is_builtin
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase
from xstate_statemachine.exceptions import InterpreterStoppedError

STYLE = sys.argv[1] if len(sys.argv) > 1 else "async"
HERE = pathlib.Path(__file__).parent
RES = {}
HAPPY_TRUE = {"exchange_reports_sl"}


def rec(k, ok, note=""):
    RES["[%s]%s" % (STYLE, k)] = bool(ok)
    print(("PASS " if ok else "FAIL ") + "[%s]%s" % (STYLE, k)
          + ("  | " + str(note) if note else ""), flush=True)


def load(bid):
    c = json.loads((HERE / (bid + ".machine.json")).read_text("utf-8"))
    c["strictConfig"] = True
    return c


def collect(c):
    A, G, S, D = set(), set(), set(), set()
    def a(v):
        if isinstance(v, str): A.add(v)
        elif isinstance(v, dict) and isinstance(v.get("type"), str): A.add(v["type"])
        elif isinstance(v, list): [a(x) for x in v]
    def g(v):
        if isinstance(v, str): G.add(v)
        elif isinstance(v, dict):
            for k in ("and", "or", "not"):
                if k in v:
                    x = v[k]; [g(y) for y in (x if isinstance(x, list) else [x])]
    def t(v):
        if isinstance(v, list): [t(x) for x in v]
        elif isinstance(v, dict): a(v.get("actions")); g(v.get("guard") or v.get("cond"))
    def w(n):
        a(n.get("entry")); a(n.get("exit"))
        for v in (n.get("on") or {}).values(): t(v)
        t(n.get("always"))
        for d, v in (n.get("after") or {}).items():
            if not str(d).lstrip("-").isdigit(): D.add(str(d))
            t(v)
        inv = n.get("invoke")
        for i in (inv if isinstance(inv, list) else [inv] if inv else []):
            if isinstance(i.get("src"), str): S.add(i["src"])
            t(i.get("onDone")); t(i.get("onError"))
        for s in (n.get("states") or {}).values(): w(s)
    w(c)
    return A, G, S, D


def walk_all(n):
    yield n
    for s in (n.get("states") or {}).values(): yield from walk_all(s)


def logic(c, style=None):
    style = style or STYLE
    A, G, S, D = collect(c)
    def mk_a(n):
        def f(i, ctx, e, ad): return None
        f.__name__ = n; return f
    def mk_g(n):
        def f(ctx, e): return n in HAPPY_TRUE  # B8 CD-03: exchange_reports_sl must be true on the happy path
        f.__name__ = n; return f
    def mk_s(n):
        if style == "def":
            def s(i, ctx, e): return {"ok": True}
        else:
            async def s(i, ctx, e): return {"ok": True}
        s.__name__ = n; return s
    return MachineLogic(
        actions={n: mk_a(n) for n in A if not is_builtin(n) and not n.startswith("spawn_")},
        guards={n: mk_g(n) for n in G}, services={n: mk_s(n) for n in S},
        delays={n: 1000 for n in D}, strict=True)


class Hooks(PluginBase):
    def __init__(self):
        self.starts, self.restored_flags, self.recv = 0, [], Counter()
        self.dropped = 0; self.seqs = []; self.unh = []
    def on_interpreter_start(self, i):
        self.starts += 1; self.restored_flags.append(i.restored_from_snapshot)
    def on_event_received(self, i, e):
        self.recv[getattr(e, "type", str(e))] += 1
        pl = getattr(e, "payload", None) or {}
        if isinstance(pl, dict) and "seq" in pl: self.seqs.append((pl["seq"], id(e)))
    def on_unhandled_event(self, i, e, *a):
        pl = getattr(e, "payload", None) or {}
        if isinstance(pl, dict) and "seq" in pl: self.unh.append(pl["seq"])
    def on_receipt_dropped(self, i, t): self.dropped += 1


def handled_events(c, ids):
    out = []
    def w(n, path):
        if path in ids:
            out.extend(k for k in (n.get("on") or {}) if k != "*" and not k.startswith(("done.", "error.", "xstate.")))
        for k, s in (n.get("states") or {}).items(): w(s, path + "." + k)
    w(c, c["id"])
    return sorted(set(out))


async def settle(n=8):
    for _ in range(n): await asyncio.sleep(0)


def evt_type(e): return getattr(e, "type", None) or (e.get("type") if isinstance(e, dict) else e)


async def one(bid):
    from xstate_statemachine.exceptions import SnapshotCorruptError
    c = load(bid)
    m = create_machine(copy.deepcopy(c), logic=logic(c), strict_config=True,
                       strict_targets=c.get("strictTargets", True))
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=64,
                    overflow_policy=OverflowPolicy.RAISE)
    h = Hooks(); i.use(h)
    await i.start(); await settle()
    try: await body(bid, c, m, i, h)
    finally: await i.stop()


async def body(bid, c, m, i, h):
    from xstate_statemachine.exceptions import SnapshotCorruptError
    rec(bid + ".boot_hook", h.starts == 1 and h.restored_flags == [False], h.restored_flags)
    ids = {s.id for s in i.active_state_nodes} if hasattr(i, "active_state_nodes") else set()
    allev = sorted({k for n in walk_all(c) for k in (n.get("on") or {}) if k != "*" and not k.startswith(("done.", "error.", "xstate."))})
    fin = {n.get("id") or k for n in walk_all(c) for k, n in (n.get("states") or {}).items() if n.get("type") == "final"}
    def to_final(ev):
        for n in walk_all(c):
            v = (n.get("on") or {}).get(ev)
            for t in (v if isinstance(v, list) else [v]):
                tg = t if isinstance(t, str) else (t or {}).get("target")
                for x in (tg if isinstance(tg, list) else [tg]):
                    if isinstance(x, str) and x.strip(".#").split(".")[-1] in fin: return True
        return False
    names = [e for e in allev if e not in handled_events(c, ids) and not to_final(e)][:3]  # declared, unhandled here -> defer
    if len(names) < 3: rec(bid + ".probe_pick", False, names); return
    # enqueue synchronously (no await between calls => run loop cannot step)
    aw = [i.send(names[0], wait=False, seq=1), i.send(names[1], wait=False, seq=2),
          i.send_priority(names[2], wait=False, seq=3)]
    rcpt = i.send(names[0], wait=True, seq=4)
    npend = len(i.pending_events)
    drained = await i.drain_pending()
    for a in aw: await a
    dt = [evt_type(e) for e in drained]
    rec(bid + ".drain_both_lanes_priority_first",
        npend == 4 and len(drained) == 4 and dt[0] == names[2], (npend, dt))
    r = await asyncio.wait_for(rcpt, 5)
    rec(bid + ".wait_receipt_fails_stopped",
        isinstance(getattr(r, "error", None), InterpreterStoppedError), repr(getattr(r, "error", r)))
    rec(bid + ".queues_empty_after_drain", len(i.pending_events) == 0)
    blob = i.get_persisted_snapshot()
    if isinstance(blob, dict): blob = json.dumps(blob)
    before = sorted(s.id for s in i.active_state_nodes) if hasattr(i, "active_state_nodes") else None
    ct0 = i.chain_trips
    await i.stop()
    persisted = [{"type": evt_type(e), "seq": getattr(e, "payload", {}).get("seq") if isinstance(getattr(e, "payload", None), dict) else None} for e in drained]
    # restore
    h2 = Hooks()
    j = Interpreter.from_snapshot(blob, m, minimum_version=3, plugins=[h2],
                                  clock=SimulatedClock())
    await j.start(); await settle()
    rec(bid + ".restore_hook_fires_restored", h2.starts == 1 and h2.restored_flags == [True],
        h2.restored_flags)
    after = sorted(s.id for s in j.active_state_nodes) if hasattr(j, "active_state_nodes") else None
    rec(bid + ".state_match", before == after, after)
    for p in persisted:
        await j.send(p["type"], wait=False, seq=p["seq"])
    for _ in range(200):   # poll to convergence (def services run off-loop: real sleep)
        await settle(5); await asyncio.sleep(0.01)
        if not j.pending_events and len({q for q, _ in h2.seqs}) >= len(persisted): break
    per = Counter(q for q, _ in set(h2.seqs))
    got = dict(per)
    uniq = sorted({q for q, _ in h2.seqs})
    rec(bid + ".replay_every_seq_seen", uniq == sorted(p["seq"] for p in persisted),
        "seqs=%s distinct_objs=%d unhandled=%s pend=%d state=%s" % (uniq, len({o for _, o in h2.seqs}), h2.unh, len(j.pending_events), sorted(j.current_state_ids)))
    rec(bid + ".replayed_exactly_once", got == {p["seq"]: 1 for p in persisted}, got)
    rec(bid + ".chain_trips_0", ct0 == 0 and j.chain_trips == 0, (ct0, j.chain_trips))
    rec(bid + ".dropped_receipts_0", i.dropped_receipts == 0 and j.dropped_receipts == 0
        and h.dropped == 0 and h2.dropped == 0)
    # #241 malformed chain fields
    bad_ok = True; notes = []
    for v in ("NaN", [1], {"a": 1}, True, -1):
        b = json.loads(blob); b["chain_trips"] = v
        try: Interpreter.from_snapshot(json.dumps(b), m); bad_ok = False; notes.append("accepted %r" % (v,))
        except SnapshotCorruptError: pass
        except Exception as e: bad_ok = False; notes.append("%r->%s" % (v, type(e).__name__))
    rec(bid + ".malformed_chain_fields_corrupt", bad_ok, notes)
    await j.stop()


def sync_one(bid):
    c = load(bid)
    m = create_machine(copy.deepcopy(c), logic=logic(c, "def"), strict_config=True,
                       strict_targets=c.get("strictTargets", True))
    ok = True
    try: SyncInterpreter(m, max_queue_size=8); ok = False
    except ValueError: pass
    SyncInterpreter(m, max_queue_size=None, overflow_policy=None)
    rec(bid + ".sync_kw_parity_valueerror", ok)
    s = SyncInterpreter(m, clock=SimulatedClock()); h = Hooks(); s.use(h); s.start()
    blob = s.get_persisted_snapshot()
    if isinstance(blob, dict): blob = json.dumps(blob)
    s.stop(); h2 = Hooks()
    r = SyncInterpreter.from_snapshot(blob, m, plugins=[h2], clock=SimulatedClock()); r.start()
    rec(bid + ".sync_restore_hook", h2.restored_flags == [True], h2.restored_flags)
    r.stop()


async def main():
    for b in ("B6", "B7", "B8", "B9", "B10"):
        try: await one(b)
        except Exception as e: rec(b + ".CRASH", False, repr(e))
        try: sync_one(b)
        except Exception as e: rec(b + ".SYNC_CRASH", False, repr(e))
    from xstate_statemachine.exceptions import RestoredChainError, RunawayChainError, RestoredError
    rec("RestoredChainError_isa", issubclass(RestoredChainError, RunawayChainError)
        and issubclass(RestoredChainError, RestoredError))
    bad = [k for k, v in RES.items() if not v]
    print("--- %d checks, %d FAIL: %s" % (len(RES), len(bad), bad))
    (HERE / ("r13_drain_restore.%s.json" % STYLE)).write_text(json.dumps(RES, indent=1))


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), 100))
