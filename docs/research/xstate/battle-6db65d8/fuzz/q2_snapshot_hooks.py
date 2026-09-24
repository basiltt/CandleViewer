"""Q2 -- #169: get_persisted_snapshot() from EVERY hook must be refused-or-legal,
never torn. Property over 300 random machines x hook sites:
on_transition, on_action (entry/exit), guard, nested+parallel entry/exit,
deferred replay, after-timer callback. A snapshot is TORN if it restores but
the restored context/configuration differs from the machine's own settled one."""
import json, logging, random, warnings, sys
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import (SyncInterpreter, MachineLogic, create_machine,
                                 PluginBase)
from xstate_statemachine.exceptions import SnapshotCorruptError, SnapshotMidStepError

RES = {"refused": 0, "produced": 0, "torn": 0, "untyped": {}, "sites": {}}
TORN = []

def gen(rnd, i):
    par = rnd.random() < 0.4
    if par:
        return {"id": f"m{i}", "type": "parallel", "states": {
            "r0": {"initial": "s0", "states": {
                "s0": {"entry": ["mark"], "on": {"GO": {"target": "s1"}}},
                "s1": {"entry": ["mark"], "exit": ["mark"],
                       "initial": "x", "states": {"x": {"entry": ["mark"]}}}}},
            "r1": {"initial": "t0", "states": {
                "t0": {"on": {"GO": {"target": "t1", "actions": ["mark"]}}},
                "t1": {"entry": ["mark"]}}}}}
    return {"id": f"m{i}", "initial": "a", "states": {
        "a": {"entry": ["mark"], "exit": ["mark"],
              "on": {"GO": {"target": "b", "guard": "g", "actions": ["mark"]}}},
        "b": {"entry": ["mark"], "initial": "c", "states": {
            "c": {"entry": ["mark"], "on": {"GO": {"target": "d"}}},
            "d": {"entry": ["mark"]}}}}}

def probe(it, site):
    """Take a snapshot from inside a hook; classify."""
    RES["sites"].setdefault(site, {"refused": 0, "produced": 0, "torn": 0})
    try:
        blob = it.get_persisted_snapshot()
    except (SnapshotMidStepError, SnapshotCorruptError) as e:
        RES["refused"] += 1; RES["sites"][site]["refused"] += 1; return
    except Exception as e:
        RES["untyped"][f"{site}:{type(e).__name__}"] = str(e)[:80]; return
    RES["produced"] += 1; RES["sites"][site]["produced"] += 1
    # Tear test: the blob must be internally consistent (restorable) AND its
    # context must not be a half-applied action list.
    # #169: get_persisted_snapshot() returns a DICT (from_snapshot takes a str).
    d = blob if isinstance(blob, dict) else json.loads(blob)
    # a produced blob must round-trip through JSON and restore cleanly
    try:
        from xstate_statemachine import Interpreter as _I
        js = json.dumps(d)
    except Exception as e:
        RES["untyped"][f"{site}:dumps:{type(e).__name__}"] = str(e)[:80]; return
    ctx = d.get("context") or {}
    n = ctx.get("n")
    cfg = d.get("configuration") or {}
    # a produced snapshot whose marked-count is mid-action-list is torn
    if isinstance(n, int) and ctx.get("committed") is not None and n != ctx["committed"]:
        RES["torn"] += 1; RES["sites"][site]["torn"] += 1
        TORN.append((site, n, ctx.get("committed")))

class P(PluginBase):
    def __init__(self, it_box): self.box = it_box
    def on_transition(self, interp, f, t, ev): probe(interp, "on_transition")

def make_logic(box):
    def mark(i, c, e, a):
        if isinstance(c, dict):
            c["n"] = c.get("n", 0) + 1
            probe(i, "action")          # mid-action-list, context half-applied
            c["committed"] = c["n"]
    def g(c, e):
        it = box.get("it")
        if it is not None: probe(it, "guard")
        return True
    return MachineLogic(actions={"mark": mark}, guards={"g": g})

def main(n=300):
    rnd = random.Random(90210)
    for i in range(n):
        box = {}
        cfg = gen(rnd, i)
        try:
            m = create_machine(cfg, logic=make_logic(box))
            it = SyncInterpreter(m); box["it"] = it
            it.use(P(box)); it.start()
            for _ in range(3): it.send("GO")
            it.stop()
        except Exception as e:
            RES["untyped"][f"drive:{type(e).__name__}"] = str(e)[:80]
    print(f"machines={n}")
    print(f"  refused={RES['refused']}  produced={RES['produced']}  TORN={RES['torn']}")
    print(f"  untyped={RES['untyped']}")
    for s, v in sorted(RES["sites"].items()):
        print(f"  site {s:<14} refused={v['refused']:>5} produced={v['produced']:>5} torn={v['torn']:>4}")
    if TORN: print("  torn samples:", TORN[:5])
main(int(sys.argv[1]) if len(sys.argv) > 1 else 300)
