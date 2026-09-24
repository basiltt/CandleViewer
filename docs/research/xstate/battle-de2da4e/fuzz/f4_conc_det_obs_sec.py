"""F4 -- concurrency / determinism / observability / security on de2da4e.

A: 200 heartbeat machines x 10 s, both kinds -- total timer handles flat,
   beats alive, tracemalloc-measured heap flat (stdlib only, no psutil).
B: determinism -- 50 runs of one chart on BOTH engines and BOTH kinds:
   the (state, action, context) trace and the final chain_trips must be
   byte-identical across runs.
C: observability -- #222 exactly-once: chain_trips increments once per
   trip, on_chain_budget_exceeded fires once per trip, last_chain_error
   latches until clear_chain_error(), and clear_chain_error() does NOT
   rewind chain_trips. Plus on_event_dropped ordering vs on_event_received.
D: security -- snapshot forgery of scheduled_sends (can a hand-written
   record mint a `done`/`after`/engine event through the #221 parked path?)
   and of the priority lane. Trust-boundary framed: only a crossing counts.

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import gc
import json
import logging
import os
import tracemalloc
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

DEFECTS = []
SECS = float(os.environ.get("SECS", "10"))
NMACH = int(os.environ.get("NMACH", "200"))

HB = {
    "id": "hb",
    "initial": "t",
    "context": {"n": 0},
    "states": {
        "t": {
            "entry": [{"type": "raise", "params": {"event": "TICK",
                                                   "delay": 10, "id": "hb"}}],
            "on": {"TICK": {"actions": [
                "beat",
                {"type": "raise", "params": {"event": "TICK", "delay": 10,
                                             "id": "hb"}}]}},
        }
    },
}


def beat(i, c, e, a=None):
    c["n"] = c.get("n", 0) + 1


async def beat_a(i, c, e, a=None):
    c["n"] = c.get("n", 0) + 1


def hb_logic(kind):
    return MachineLogic(actions={"beat": beat_a if kind == "async def"
                                 else beat})


def handles(it):
    th = getattr(it, "_timer_handles", {}) or {}
    return sum(len(v) for v in th.values())


async def part_a(kind):
    gc.collect()
    tracemalloc.start()
    its = []
    for k in range(NMACH):
        m = create_machine(json.loads(json.dumps(HB)), logic=hb_logic(kind))
        its.append(Interpreter(m))
    await asyncio.gather(*[i.start() for i in its])
    base = tracemalloc.take_snapshot()
    samples = []
    t0 = asyncio.get_running_loop().time()
    while asyncio.get_running_loop().time() - t0 < SECS:
        await asyncio.sleep(1.0)
        samples.append((sum(handles(i) for i in its),
                        sum(len(getattr(i, "_armed_self_sends", {}) or {})
                            for i in its)))
    gc.collect()
    cur = tracemalloc.take_snapshot()
    grow = sum(s.size_diff for s in cur.compare_to(base, "filename"))
    tracemalloc.stop()
    beats = [i.context.get("n", 0) for i in its]
    alive = sum(1 for b in beats if b > 0)
    await asyncio.gather(*[i.stop() for i in its], return_exceptions=True)
    hmax = max(h for h, _ in samples)
    hmin = min(h for h, _ in samples)
    print("  A/%-9s handles per sample=%s armed=%s heap_growth=%+.1fKB "
          "beats min=%d max=%d alive=%d/%d"
          % (kind, [h for h, _ in samples], sorted({a for _, a in samples}),
             grow / 1024.0, min(beats), max(beats), alive, NMACH))
    if hmax > NMACH * 2:
        DEFECTS.append("A/%s: timer handles peaked at %d for %d machines "
                       "(expected <=%d)" % (kind, hmax, NMACH, NMACH))
    if alive != NMACH:
        DEFECTS.append("A/%s: only %d/%d heartbeats alive after %.0fs"
                       % (kind, alive, NMACH, SECS))
    if grow > 8 * 1024 * 1024:
        DEFECTS.append("A/%s: heap grew %.1fMB over %.0fs of heartbeats"
                       % (kind, grow / 1048576.0, SECS))
    return hmin, hmax


DET = {
    "id": "det",
    "initial": "a",
    "context": {"log": [], "n": 0},
    "states": {
        "a": {
            "entry": ["mark"],
            "on": {"GO": {"target": "b", "actions": ["mark"]},
                   "SPIN": {"actions": [
                       {"type": "raise", "params": {"event": "SPIN"}}]}},
        },
        "b": {"entry": ["mark"],
              "on": {"GO": {"target": "a", "actions": ["mark"]}}},
    },
}


def mk_det_logic(kind):
    def mark(i, c, e, a=None):
        c["n"] = c.get("n", 0) + 1
        c.setdefault("log", []).append((e.type, c["n"]))

    async def mark_a(i, c, e, a=None):
        mark(i, c, e, a)

    return MachineLogic(actions={"mark": mark_a if kind == "async def"
                                 else mark})


async def det_async(kind):
    m = create_machine(json.loads(json.dumps(DET)), logic=mk_det_logic(kind))
    it = Interpreter(m)
    await it.start()
    for ev in ("GO", "GO", "SPIN", "GO"):
        await it.send(ev)
    await asyncio.sleep(0.15)
    tr = (tuple(tuple(x) for x in it.context.get("log", [])),
          tuple(sorted(it.current_state_ids)), it.chain_trips)
    await it.stop()
    return tr


def det_sync(kind):
    m = create_machine(json.loads(json.dumps(DET)), logic=mk_det_logic("def"))
    it = SyncInterpreter(m)
    it.start()
    for ev in ("GO", "GO", "SPIN", "GO"):
        it.send(ev)
    tr = (tuple(tuple(x) for x in it.context.get("log", [])),
          tuple(sorted(it.current_state_ids)), it.chain_trips)
    it.stop()
    return tr


async def part_b():
    print("\nB -- determinism: 50 runs x both engines x both kinds "
          "(trace + chain_trips)")
    for kind in ("def", "async def"):
        seen = set()
        for _ in range(50):
            seen.add(await det_async(kind))
        print("  async engine /%-9s distinct traces=%d trips=%s"
              % (kind, len(seen), sorted({t[2] for t in seen})))
        if len(seen) != 1:
            DEFECTS.append("B/async/%s: %d distinct traces over 50 runs"
                           % (kind, len(seen)))
    sseen = set()
    for _ in range(50):
        sseen.add(det_sync("def"))
    print("  sync engine  /def       distinct traces=%d trips=%s"
          % (len(sseen), sorted({t[2] for t in sseen})))
    if len(sseen) != 1:
        DEFECTS.append("B/sync: %d distinct traces over 50 runs" % len(sseen))


class Spy(PluginBase):
    def __init__(self):
        self.order = []
        self.chain = 0

    def on_chain_budget_exceeded(self, interpreter, error, event):
        self.chain += 1
        self.order.append("chain:" + type(error).__name__)

    def on_event_received(self, interpreter, event):
        self.order.append("recv:" + event.type)

    def on_event_dropped(self, interpreter, event, reason):
        self.order.append("drop:%s:%s" % (event.type, reason))


TRIPPER = {
    "id": "tp",
    "initial": "a",
    "context": {},
    "states": {
        "a": {
            "on": {
                "GO": {"actions": [{"type": "raise",
                                    "params": {"event": "GO"}}]},
                "OK": {"actions": ["noop"]},
            }
        }
    },
}


async def part_c(kind):
    def noop(i, c, e, a=None):
        c["k"] = c.get("k", 0) + 1

    async def noop_a(i, c, e, a=None):
        noop(i, c, e, a)

    lg = MachineLogic(actions={"noop": noop_a if kind == "async def"
                               else noop})
    it = Interpreter(create_machine(json.loads(json.dumps(TRIPPER)),
                                    logic=lg))
    spy = Spy()
    it.use(spy)
    await it.start()
    await it.send("GO")
    await asyncio.sleep(0.2)
    t1, h1 = it.chain_trips, spy.chain
    await it.send("OK")
    await asyncio.sleep(0.05)
    t2, e2 = it.chain_trips, type(it.last_chain_error).__name__
    await it.send("GO")          # second trip
    await asyncio.sleep(0.2)
    t3, h3 = it.chain_trips, spy.chain
    it.clear_chain_error()
    t4, e4 = it.chain_trips, type(it.last_chain_error).__name__
    await it.stop()
    print("  C/%-9s trip1 trips=%d hook=%d | after benign trips=%d err=%s | "
          "trip2 trips=%d hook=%d | after clear trips=%d err=%s"
          % (kind, t1, h1, t2, e2, t3, h3, t4, e4))
    print("           plugin order tail=%s" % (spy.order[-6:],))
    if (t1, h1) != (1, 1):
        DEFECTS.append("C/%s: first trip gave chain_trips=%d hook=%d "
                       "(expected 1,1)" % (kind, t1, h1))
    if t2 != 1 or e2 == "NoneType":
        DEFECTS.append("C/%s: benign event disturbed the latch (%d,%s)"
                       % (kind, t2, e2))
    if (t3, h3) != (2, 2):
        DEFECTS.append("C/%s: second trip gave chain_trips=%d hook=%d "
                       "(expected 2,2)" % (kind, t3, h3))
    if t4 != t3 or e4 != "NoneType":
        DEFECTS.append("C/%s: clear_chain_error() left trips=%d err=%s "
                       "(expected %d, None)" % (kind, t4, e4, t3))


FORGE = {
    "id": "fg",
    "initial": "armed",
    "context": {"hit": None},
    "states": {
        "armed": {
            "entry": [{"type": "raise", "params": {"event": "LATER",
                                                   "delay": 60000,
                                                   "id": "z"}}],
            "on": {"LATER": {"target": "expired"},
                   "done.invoke.job": {"target": "expired",
                                       "actions": ["grab"]},
                   "after.999.fg.armed": {"target": "expired"}},
        },
        "expired": {},
    },
}


def grab(i, c, e, a=None):
    c["hit"] = getattr(e, "data", None)


async def part_d(kind):
    lg = MachineLogic(actions={"grab": grab})
    m = create_machine(json.loads(json.dumps(FORGE)), logic=lg)
    it = Interpreter(m)
    await it.start()
    await asyncio.sleep(0)
    blob = json.loads(it.get_snapshot())
    await it.stop()
    rows = []

    async def run(name, mutate):
        b = json.loads(json.dumps(blob))
        mutate(b)
        try:
            r = Interpreter.from_snapshot(json.dumps(b), m)
        except Exception as ex:  # noqa: BLE001
            rows.append((name, "REFUSED:" + type(ex).__name__, None))
            return
        await r.start()
        await asyncio.sleep(0.15)
        st = sorted(r.current_state_ids)
        rows.append((name, "DROVE" if st == ["fg.expired"] else "inert",
                     r.context.get("hit")))
        await r.stop()

    # D1: forge a `done.invoke.*` record into scheduled_sends (a delayed
    #     self-send is never a completion -- #221 re-emits records verbatim)
    def m1(b):
        b.setdefault("scheduled_sends", []).append(
            {"type": "done.invoke.job", "payload": {},
             "data": {"filled": 999999}, "remaining_ms": 0.5})
    # D2: forge an `after.*` record
    def m2(b):
        b.setdefault("scheduled_sends", []).append(
            {"type": "after.999.fg.armed", "payload": {},
             "remaining_ms": 0.5})
    # D3: shorten a genuine record's remaining_ms 60000 -> 1
    def m3(b):
        for r in b.get("scheduled_sends") or []:
            r["remaining_ms"] = 1.0
    # D4: negative remaining_ms
    def m4(b):
        for r in b.get("scheduled_sends") or []:
            r["remaining_ms"] = -10 ** 9
    # D5: lane forgery on a pending event
    def m5(b):
        b.setdefault("pending_events", []).append(
            {"type": "LATER", "payload": {}, "lane": "priority"})

    for n, f in (("D1 forged done.invoke in scheduled_sends", m1),
                 ("D2 forged after.* in scheduled_sends", m2),
                 ("D3 remaining_ms 60000->1", m3),
                 ("D4 remaining_ms negative", m4),
                 ("D5 lane:'priority' on a pending event", m5)):
        await run(n, f)
    for n, o, hit in rows:
        print("  D/%-9s %-42s -> %-8s hit=%r" % (kind, n, o, hit))
    return rows


async def main():
    print("F4 -- concurrency / determinism / observability / security "
          "@ de2da4e")
    print("\nA -- %d heartbeat machines x %.0fs, handles + heap"
          % (NMACH, SECS))
    for kind in ("def", "async def"):
        await part_a(kind)
    await part_b()
    print("\nC -- #222 exactly-once: chain_trips / hook / latch / clear")
    for kind in ("def", "async def"):
        await part_c(kind)
    print("\nD -- snapshot forgery of scheduled_sends / lane "
          "(trust-boundary framed)")
    for kind in ("def", "async def"):
        rows = await part_d(kind)
        for n, o, hit in rows:
            if n.startswith(("D1", "D2")) and o == "DROVE":
                DEFECTS.append(
                    "D/%s: %s -- a hand-written snapshot record minted an "
                    "ENGINE-ONLY event through the #221 parked path "
                    "(hit=%r)" % (kind, n, hit))
    print("\nDEFECTS = %d" % len(DEFECTS))
    for d in DEFECTS[:20]:
        print("   -", d)
    raise SystemExit(1 if DEFECTS else 0)


asyncio.run(main())
