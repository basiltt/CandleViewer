"""G1 v0.9.1 new-surface property sweep (async engine, def + async def actions):
 P1 drain->persist->restore->start delivers every drained event exactly once,
    priority lane first (300 cases) and drain order == pending_events order
 P2 wait=True receipts on drained events fail with InterpreterStoppedError
 P3 restored_from_snapshot correct after N restores; on_interpreter_start once
    per start under 100 concurrent restores
 P4 dropped_receipts exact + on_receipt_dropped exactly-once (1000 def actions)
 P5 RestoredChainError isinstance matrix; SyncInterpreter kwargs
STANDALONE."""
import asyncio, gc, json, logging, random, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
import xstate_statemachine as X
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, PluginBase, create_machine
D = []
TYPES = [f"E{i}" for i in range(6)]
def cfg(): return {"id": "p", "initial": "a", "context": {"seen": []},
    "states": {"a": {"on": {t: {"actions": ["mark"]} for t in TYPES}}}}
def mark_def(i, c, e, a=None): c["seen"].append(e.type)
async def mark_async(i, c, e, a=None): c["seen"].append(e.type)
class Hooks(PluginBase):
    def __init__(s): s.starts = []; s.dropped = []
    def on_interpreter_start(s, it): s.starts.append(it.restored_from_snapshot)
    def on_receipt_dropped(s, it, t): s.dropped.append(t)

async def p1(kind, rnd, idx):
    m = create_machine(cfg(), logic=MachineLogic(actions={"mark": mark_def if kind == "def" else mark_async}))
    it = Interpreter(m); await it.start()
    evs = []
    # block the loop by queuing synchronously (no await between sends)
    futs = []
    for k in range(rnd.randint(1, 12)):
        t = rnd.choice(TYPES); pr = rnd.random() < 0.4
        evs.append((t, pr))
        futs.append(it.send_priority(t) if pr else it.send(t))
    pend = [e.type for e in it.pending_events] if hasattr(it, "pending_events") else None
    npri = len([1 for _, p in evs if p])
    drained = await it.drain_pending()
    if [e.type for e in drained[:npri]] != [t for t, p in evs if p]:
        D.append(f'P1/{kind}/{idx} priority lane not first')
    dtypes = [e.type for e in drained]
    for f in futs:
        if asyncio.iscoroutine(f) or isinstance(f, asyncio.Future):
            try: await f
            except Exception: pass
    if pend is not None and pend != dtypes: D.append(f"P1/{kind}/{idx} drain order {dtypes} != pending {pend}")
    blob = it.get_snapshot(); already = list(it.context["seen"]); await it.stop()
    # recipe: the caller persists the drained list beside the snapshot and
    # re-sends it (priority items via send_priority) after restore+start
    saved = json.dumps([[e.type, i < npri] for i, e in enumerate(drained)])
    npri_saved = npri
    r = Interpreter.from_snapshot(blob, m); await r.start()
    for t, pr in json.loads(saved):
        (r.send_priority(t) if pr else r.send(t))
    for _ in range(8): await asyncio.sleep(0)
    got = r.context["seen"][len(already):]
    exp = [t for t, p in evs if p] + [t for t, p in evs if not p]
    exp = exp[len(already):] if already else exp
    # events processed before drain are in `already`; drained ones must replay exactly once
    if sorted(got) != sorted(dtypes) or got != dtypes:
        D.append(f"P1/{kind}/{idx} replay {got} != drained {dtypes} (already={already})")
    await r.stop()

async def p2():
    m = create_machine(cfg(), logic=MachineLogic(actions={"mark": mark_def}))
    it = Interpreter(m); await it.start()
    fs = [it.send("E0", wait=True) for _ in range(5)]
    fs = [asyncio.ensure_future(f) for f in fs]
    d = await it.drain_pending()
    print("  P2 drained", len(d))
    res = await asyncio.gather(*fs, return_exceptions=True)
    names = sorted({type(x).__name__ for x in res})
    print("  P2 receipts after drain:", names)
    await it.stop()

async def p3():
    m = create_machine(cfg(), logic=MachineLogic(actions={"mark": mark_def}))
    it = Interpreter(m); await it.start(); blob = it.get_snapshot(); await it.stop()
    flags = []
    for n in range(10):
        h = Hooks(); r = Interpreter.from_snapshot(blob, m, plugins=[h]); await r.start()
        flags.append((r.restored_from_snapshot, h.starts)); blob = r.get_snapshot(); await r.stop()
    if any(f != (True, [True]) for f in flags): D.append(f"P3 chain restores {flags}")
    hs = [Hooks() for _ in range(100)]
    rs = [Interpreter.from_snapshot(blob, m, plugins=[h]) for h in hs]
    await asyncio.gather(*(r.start() for r in rs))
    bad = sum(h.starts != [True] for h in hs)
    await asyncio.gather(*(r.stop() for r in rs))
    print(f"  P3 10 chained restores ok={not any(f != (True,[True]) for f in flags)}; 100 concurrent: bad={bad}")
    if bad: D.append(f"P3 concurrent start hook bad={bad}")

async def p4():
    N = 1000
    def act(i, c, e, a=None): i.send("E1", wait=True)
    c = {"id": "d", "initial": "a", "states": {"a": {"on": {"GO": {"actions": ["act"]}, "E1": {}}}}}
    h = Hooks(); it = Interpreter(create_machine(c, logic=MachineLogic(actions={"act": act})))
    it.use(h); await it.start()
    for _ in range(N): await it.send("GO")
    for _ in range(50):
        gc.collect(); await asyncio.sleep(0.01)
        if it.dropped_receipts >= N: break
    print(f"  P4 dropped_receipts={it.dropped_receipts} hook={len(h.dropped)} (expect {N})")
    if it.dropped_receipts != N or len(h.dropped) != N: D.append(f"P4 {it.dropped_receipts}/{len(h.dropped)} != {N}")
    await it.stop()

def p5():
    e = X.RestoredChainError
    print("  P5 RestoredChainError <: RunawayChainError", issubclass(e, X.RunawayChainError), "<: RestoredError", issubclass(e, X.RestoredError))
    out = []
    for kw in ({"max_queue_size": None}, {"overflow_policy": None}, {"max_queue_size": 5}, {"overflow_policy": "drop_newest"}):
        try: SyncInterpreter(create_machine(cfg(), logic=MachineLogic(actions={'mark': mark_def})), **kw); out.append((kw, "ok"))
        except Exception as x: out.append((kw, type(x).__name__))
    print("  P5 SyncInterpreter kwargs:", out)

async def main():
    rnd = random.Random(2026)
    for kind in ("def", "async def"):
        for i in range(150): await p1(kind, rnd, i)
    print(f"  P1 300 cases, defects={len(D)}")
    await p2(); await p3(); await p4(); p5()
    for d in D[:10]: print("   -", d)
    print("DEFECTS =", len(D))
asyncio.run(main())
