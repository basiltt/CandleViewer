"""Q6 -- determinism, semantics, security.
D1 50x identical traces both engines incl. trip points (same lap count?).
D2 perf-PR (#165/#176) shared init/exit SENTINEL aliasing: two machines,
   does a mutation of one's init/exit action list cross-talk?
S1 guard-crash vs denied vs deferred vs unhandled 4-way Receipt matrix.
S2 start() ordering vs #116 (async vs sync, plain-def service).
S3 entry-window snapshot refusal at child vs root (#169).
X1 internal=True forgery post-fix.
X2 __slots__ attribute surface (can an attacker attach arbitrary attrs?).
"""
import asyncio, json, logging, warnings, copy, collections
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 create_machine, PluginBase)
from xstate_statemachine.exceptions import (SnapshotMidStepError,
                                            SnapshotCorruptError)
import xstate_statemachine.base_interpreter as bi

# ---------- D1 ----------
TRIP = {"id": "m", "initial": "a", "maxIterations": 30, "states": {
    "a": {"always": {"target": "b", "guard": "g"}},
    "b": {"always": {"target": "a", "guard": "g", "actions": ["bump"]}}}}
def mk_logic():
    def bump(i, c, e, a): c["n"] = c.get("n", 0) + 1
    return MachineLogic(actions={"bump": bump}, guards={"g": lambda c, e: True})

def d1_sync():
    traces = set(); laps = set()
    for _ in range(50):
        it = SyncInterpreter(create_machine(copy.deepcopy(TRIP) | {"context": {"n": 0}}, logic=mk_logic()))
        it.start()
        traces.add((tuple(sorted(it.current_state_ids)),
                    type(it.last_error).__name__ if it.last_error else None))
        laps.add(it.context.get("n")); it.stop()
    return traces, laps

async def d1_async():
    traces = set(); laps = set()
    for _ in range(50):
        it = Interpreter(create_machine(copy.deepcopy(TRIP) | {"context": {"n": 0}}, logic=mk_logic()))
        await asyncio.wait_for(it.start(), 15)
        await asyncio.sleep(0.02)
        traces.add((tuple(sorted(it.current_state_ids)),
                    type(it.last_error).__name__ if it.last_error else None))
        laps.add(it.context.get("n")); await it.stop()
    return traces, laps

# ---------- D2 ----------
def d2():
    A = {"id": "A", "initial": "a", "states": {"a": {}}}
    B = {"id": "B", "initial": "a", "states": {"a": {}}}
    ma = create_machine(copy.deepcopy(A), logic=MachineLogic())
    mb = create_machine(copy.deepcopy(B), logic=MachineLogic())
    na, nb = ma.states["a"], mb.states["a"]
    ids = {"entry": (id(na.entry), id(nb.entry)), "exit": (id(na.exit), id(nb.exit))}
    shared = na.entry is nb.entry or na.exit is nb.exit
    crosstalk = "n/a"
    if shared:
        try:
            na.entry.append("POISON")
            crosstalk = ("CROSS-TALK" if "POISON" in nb.entry else "isolated")
            na.entry.remove("POISON")
        except AttributeError as e:
            crosstalk = f"immutable ({type(e).__name__}) -> safe"
    print(f"D2 sentinel shared={shared} ids={ids} mutation={crosstalk}")

# ---------- S1 ----------
def s1():
    CFG = {"id": "m", "initial": "a", "guardErrorPolicy": "raise",
           "onUnhandled": "defer", "states": {
        "a": {"on": {
            "CRASH": {"target": "b", "guard": "boom"},
            "DENY":  {"target": "b", "guard": "no"}}},
        "b": {}}}
    def boom(c, e): raise ValueError("guard exploded")
    L = MachineLogic(guards={"boom": boom, "no": lambda c, e: False})
    rows = []
    for ev in ("CRASH", "DENY", "NOPE"):
        it = SyncInterpreter(create_machine(copy.deepcopy(CFG), logic=L)); it.start()
        try:
            r = it.send(ev, wait=True)
            rows.append((ev, getattr(r, "denied", "?"),
                         type(getattr(r, "error", None)).__name__ if getattr(r, "error", None) else None))
        except Exception as e:
            rows.append((ev, f"RAISED:{type(e).__name__}", None))
        it.stop()
    for ev, den, err in rows:
        print(f"S1 {ev:<6} denied={den!s:<6} error={err}")

# ---------- S2 ----------
async def s2():
    CFG = {"id": "m", "initial": "a", "states": {
        "a": {"invoke": {"id": "i", "src": "svc", "onDone": {"target": "b"}}},
        "b": {"on": {"GO": {"target": "c"}}}, "c": {}}}
    def svc(i, c, e): return 1
    L = MachineLogic(services={"svc": svc})
    s = SyncInterpreter(create_machine(copy.deepcopy(CFG), logic=L)); s.start()
    sa = sorted(s.current_state_ids); s.send("GO"); sb = sorted(s.current_state_ids); s.stop()
    div = 0; sample = None
    for _ in range(10):
        a = Interpreter(create_machine(copy.deepcopy(CFG), logic=L))
        await asyncio.wait_for(a.start(), 10)
        aa = sorted(a.current_state_ids); await a.send("GO")
        await asyncio.sleep(0.05); ab = sorted(a.current_state_ids); await a.stop()
        if (aa, ab) != (sa, sb): div += 1; sample = (aa, ab)
    print(f"S2 #116 start-ordering: sync=({sa},{sb}) async divergent {div}/10 sample={sample}")

# ---------- S3 ----------
def s3():
    CFG = {"id": "m", "initial": "a", "states": {
        "a": {"on": {"GO": {"target": "b"}}},
        "b": {"entry": ["snap_root"], "initial": "c", "states": {
            "c": {"entry": ["snap_child"]}}}}}
    out = {}
    def snap(tag):
        def f(i, c, e, a):
            try: i.get_persisted_snapshot(); out[tag] = "PRODUCED"
            except (SnapshotMidStepError, SnapshotCorruptError) as ex: out[tag] = f"REFUSED:{type(ex).__name__}"
            except Exception as ex: out[tag] = f"UNTYPED:{type(ex).__name__}"
        return f
    it = SyncInterpreter(create_machine(CFG, logic=MachineLogic(
        actions={"snap_root": snap("root_entry"), "snap_child": snap("child_entry")})))
    it.start(); it.send("GO"); it.stop()
    print(f"S3 #169 entry-window: {out}")

# ---------- X1 ----------
async def x1():
    CFG = {"id": "m", "initial": "a", "maxIterations": 20, "states": {
        "a": {"on": {"T": {"target": "a"}}}}}
    it = Interpreter(create_machine(CFG, logic=MachineLogic()))
    await asyncio.wait_for(it.start(), 10)
    import threading
    # forge: an external thread claiming internal=True to bypass the chain bound
    res = []
    def w():
        for _ in range(200):
            try: res.append(it.send_threadsafe("T", internal=True))
            except Exception as e: res.append(e)
    t = threading.Thread(target=w); t.start(); t.join()
    await asyncio.sleep(1.0)
    err = type(it.last_error).__name__ if getattr(it, "last_error", None) else None
    print(f"X1 internal=True forgery from foreign thread: sends={len(res)} "
          f"in_flight={it._threadsafe_self_sends_in_flight} last_error={err} status={it.status}")
    await it.stop()

# ---------- X2 ----------
def x2():
    CFG = {"id": "m", "initial": "a", "states": {"a": {}}}
    it = SyncInterpreter(create_machine(CFG, logic=MachineLogic()))
    has_dict = hasattr(it, "__dict__")
    try:
        it.injected_attr = 1; inj = "ACCEPTED"
    except AttributeError: inj = "refused (__slots__)"
    print(f"X2 __slots__: interpreter __dict__={has_dict} arbitrary attr -> {inj}")

async def main():
    st, sl = d1_sync(); at, al = await d1_async()
    print(f"D1 sync distinct_traces={len(st)} laps={sl} | async distinct={len(at)} laps={al} "
          f"| cross_equal={st == at} lap_parity={sl == al}")
    d2(); s1(); await s2(); s3(); await x1(); x2()
asyncio.run(main())
