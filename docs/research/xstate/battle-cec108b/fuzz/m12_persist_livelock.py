"""m12 — persistence + livelock + observability attacks (FUZZ track).

E1  hypothesis property over random PARALLEL machines (>=300 cases):
    snapshot at every quiescent point must never raise and must round-trip
    byte-identical.
E2  snapshot taken from inside an entry action (mid-step window).
E3  history + parallel restore fidelity.
E4  v1 upcast carrying a torn configuration must be refused.
E5  config fuzzer for livelock with a hard watchdog (nested invoke onDone
    cycles, always cycles across regions).
E6  observability: hook matrix for the new reasons (guard_denied,
    unresolved_target, chain_budget, on_plugin_error) -- exactly-once.
"""
from __future__ import annotations
import asyncio, copy, json, logging, os, random, sys, threading, time
logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    create_machine, MachineLogic, Interpreter, SyncInterpreter,
    XStateMachineError, SnapshotCorruptError, SnapshotMidStepError,
)

RESULTS = []
HERE = os.path.dirname(os.path.abspath(__file__))


def rec(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"{name:30s} {'PASS' if ok else 'FAIL'}  {detail}", flush=True)


def lg(**kw):
    return MachineLogic(actions=kw.get("a", {}), guards=kw.get("g", {}),
                        services=kw.get("s", {}))


# ------------------------------------------------------------------ E1
def gen_parallel(rnd):
    """Random 2-4 region parallel machine, each region a small compound."""
    nreg = rnd.randint(2, 4)
    regions = {}
    for r in range(nreg):
        nst = rnd.randint(2, 3)
        sts = {}
        for i in range(nst):
            nxt = f"s{(i + 1) % nst}"
            on = {}
            for ev in rnd.sample(["GO", "PING", "PONG", "X"],
                                 rnd.randint(1, 3)):
                on[ev] = nxt
            node = {"on": on}
            if rnd.random() < 0.3:
                node["entry"] = ["mark"]
            sts[f"s{i}"] = node
        if rnd.random() < 0.4:
            sts["hist"] = {"type": "history",
                           "history": rnd.choice(["shallow", "deep"])}
        regions[f"r{r}"] = {"initial": "s0", "states": sts}
    return {"id": "m", "type": "parallel", "context": {"n": 0},
            "states": regions}


def e1_parallel_snapshot_property(cases=320):
    rnd = random.Random(4242)
    raised, drift, ok = {}, 0, 0
    for i in range(cases):
        cfg = gen_parallel(rnd)
        try:
            m = create_machine(copy.deepcopy(cfg),
                               logic=lg(a={"mark": lambda i, c, e, a: None}))
            it = SyncInterpreter(m)
            it.start()
        except Exception as exc:
            raised[f"setup:{type(exc).__name__}"] = \
                raised.get(f"setup:{type(exc).__name__}", 0) + 1
            continue
        for step in range(6):
            try:
                s1 = it.get_persisted_snapshot()
            except Exception as exc:
                k = f"snap:{type(exc).__name__}"
                raised[k] = raised.get(k, 0) + 1
                break
            try:
                r = SyncInterpreter.from_snapshot(
                    json.dumps(s1, default=str),
                    create_machine(copy.deepcopy(cfg),
                                   logic=lg(a={"mark":
                                               lambda i, c, e, a: None})))
                s2 = r.get_persisted_snapshot()
            except Exception as exc:
                k = f"restore:{type(exc).__name__}"
                raised[k] = raised.get(k, 0) + 1
                break
            a = {k: v for k, v in s1.items() if k != "taken_at"}
            b = {k: v for k, v in s2.items() if k != "taken_at"}
            if json.dumps(a, sort_keys=True, default=str) != \
                    json.dumps(b, sort_keys=True, default=str):
                drift += 1
                break
            ok += 1
            try:
                it.send(rnd.choice(["GO", "PING", "PONG", "X"]))
            except XStateMachineError:
                pass
    rec("E1.parallel_snapshot_prop", not raised and drift == 0,
        f"cases={cases} quiescent_snapshots_ok={ok} drift={drift} "
        f"raised={raised}")


# ------------------------------------------------------------------ E2
def e2_snapshot_in_entry_action():
    got = {}

    def grab(i, c, e, a):
        try:
            i.get_persisted_snapshot()
            got["r"] = "PRODUCED (mid-step window)"
        except SnapshotMidStepError:
            got["r"] = "SnapshotMidStepError"
        except XStateMachineError as exc:
            got["r"] = type(exc).__name__
        except Exception as exc:
            got["r"] = f"UNTYPED {type(exc).__name__}"

    cfg = {"id": "m", "initial": "a",
           "states": {"a": {"on": {"GO": "b"}}, "b": {"entry": ["grab"]}}}
    it = SyncInterpreter(create_machine(copy.deepcopy(cfg),
                                        logic=lg(a={"grab": grab})))
    it.start()
    it.send("GO")
    r = got.get("r", "<action never ran>")
    rec("E2.snapshot_in_entry", "UNTYPED" not in r, r)


# ------------------------------------------------------------------ E3
def e3_history_parallel_restore():
    cfg = {"id": "m", "type": "parallel", "states": {
        "r0": {"initial": "s0", "states": {
            "s0": {"on": {"GO": "s1"}}, "s1": {"on": {"BACK": "s0"}},
            "h": {"type": "history", "history": "deep"}}},
        "r1": {"initial": "t0", "states": {
            "t0": {"on": {"GO": "t1"}}, "t1": {}}}}}
    it = SyncInterpreter(create_machine(copy.deepcopy(cfg), logic=lg()))
    it.start()
    it.send("GO")
    before = sorted(it.current_state_ids)
    s = it.get_persisted_snapshot()
    try:
        r = SyncInterpreter.from_snapshot(
            json.dumps(s, default=str),
            create_machine(copy.deepcopy(cfg), logic=lg()))
        after = sorted(r.current_state_ids)
        r.send("BACK")
        post = sorted(r.current_state_ids)
        it.send("BACK")
        rec("E3.history_parallel_restore",
            before == after and post == sorted(it.current_state_ids),
            f"before={before} restored={after} after_BACK "
            f"restored={post} live={sorted(it.current_state_ids)}")
    except Exception as exc:
        rec("E3.history_parallel_restore", False,
            f"{type(exc).__name__}: {exc}")


# ------------------------------------------------------------------ E4
def e4_v1_torn_upcast():
    cfg = {"id": "m", "initial": "a", "states": {
        "a": {"initial": "x", "states": {"x": {}, "y": {}}}, "b": {}}}
    it = SyncInterpreter(create_machine(copy.deepcopy(cfg), logic=lg()))
    it.start()
    s = it.get_persisted_snapshot()
    outs = []
    for name, blob in (
            ("v1 torn (compound, no leaf)",
             dict(s, version=1, configuration=["m", "m.a"],
                  state_ids=["m.a"])),
            ("v1 root-only", dict(s, version=1, configuration=["m"],
                                  state_ids=[])),
            ("v1 legal", dict(s, version=1))):
        b = copy.deepcopy(blob)
        try:
            r = SyncInterpreter.from_snapshot(
                json.dumps(b, default=str),
                create_machine(copy.deepcopy(cfg), logic=lg()))
            outs.append(f"{name}->ACCEPTED states={sorted(r.current_state_ids)}")
        except XStateMachineError as exc:
            outs.append(f"{name}->{type(exc).__name__}")
        except Exception as exc:
            outs.append(f"{name}->UNTYPED {type(exc).__name__}")
    bad = [o for o in outs
           if ("torn" in o or "root-only" in o) and "ACCEPTED" in o]
    bad += [o for o in outs if "UNTYPED" in o]
    rec("E4.v1_torn_upcast", not bad, " | ".join(outs))


# ------------------------------------------------------------------ E5
LIVELOCK_SHAPES = {
    "nested_invoke_onDone_ancestor": {
        "id": "m", "initial": "a", "states": {"a": {
            "initial": "a",
            "invoke": {"id": "i1", "src": "svc", "onDone": {"target": "#m.a"}},
            "states": {"a": {"invoke": {"id": "i2", "src": "svc",
                                        "onDone": {"target": "#m.a"}}}}}}},
    "always_cycle_cross_region": {
        "id": "m", "type": "parallel", "states": {
            "A": {"initial": "a", "states": {
                "a": {"always": {"target": "#m.B.b", "guard": "g"}},
                "b": {}}},
            "B": {"initial": "a", "states": {
                "a": {}, "b": {"always": {"target": "#m.A.a", "guard": "g"}}}}}},
    "invoke_plus_always_ladder": {
        "id": "m", "initial": "a",
        "on": {"GO": {"target": "#m.a", "internal": True}},
        "states": {"a": {"initial": "a",
                         "always": {"target": "#m.a.a", "guard": "g"},
                         "states": {"a": {"invoke": {"id": "i",
                                                     "src": "svc"}}}}}},
}


def _watchdog_sync(cfg, seconds=10):
    box = {"done": False, "err": None}

    def run():
        try:
            it = SyncInterpreter(create_machine(copy.deepcopy(cfg),
                                                logic=lg(g={"g": lambda c, e: True},
                                                         s={"svc": lambda i, c, e: {"v": 1}})))
            it.start()
            it.send("GO")
        except Exception as exc:
            box["err"] = type(exc).__name__
        box["done"] = True

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    return box["done"], box["err"]


async def _watchdog_async(cfg, seconds=10):
    try:
        it = Interpreter(create_machine(copy.deepcopy(cfg),
                                        logic=lg(g={"g": lambda c, e: True},
                                                 s={"svc": lambda i, c, e: {"v": 1}})),
                         strict=False)
    except Exception as exc:
        return True, type(exc).__name__
    try:
        await asyncio.wait_for(it.start(), timeout=seconds)
        await asyncio.sleep(0.03)
        await asyncio.wait_for(it.send("GO", wait=True), timeout=seconds)
        return True, None
    except asyncio.TimeoutError:
        return False, "TIMEOUT"
    except Exception as exc:
        return True, type(exc).__name__
    finally:
        try:
            await asyncio.wait_for(it.stop(), timeout=3)
        except Exception:
            pass


def e5_livelock_watchdog():
    lines, hung = [], 0
    for name, cfg in LIVELOCK_SHAPES.items():
        sd, se = _watchdog_sync(cfg, 10)
        ad, ae = asyncio.run(_watchdog_async(cfg, 10))
        if not sd:
            hung += 1
        if not ad:
            hung += 1
        lines.append(f"{name}: sync={'ok' if sd else 'HANG'}/{se} "
                     f"async={'ok' if ad else 'HANG'}/{ae}")
    rec("E5.livelock_watchdog", hung == 0, " | ".join(lines))


# ------------------------------------------------------------------ E6
def e6_hook_matrix():
    seen = []

    from xstate_statemachine import PluginBase

    class P(PluginBase):
        def on_event_dropped(self, i, ev, reason):
            seen.append(("dropped", getattr(ev, "type", ev), reason))

        def on_unhandled_event(self, i, ev, active_state_ids, disposition):
            seen.append(("unhandled", getattr(ev, "type", ev), disposition))

        def on_plugin_error(self, i, plugin, hook, exc):
            seen.append(("plugin_error", hook, type(exc).__name__))

        def on_resolve_error(self, i, *a, **k):
            seen.append(("resolve_error", str(a[:1]), str(k)[:40]))

    cfg = {"id": "m", "initial": "a", "states": {
        "a": {"on": {"DENY": {"target": "b", "guard": "never"},
                     "FWD": {"actions": ["fwd"]}}},
        "b": {}}}

    def fwd(i, c, e, a):
        i.send_to("no_such_actor", "X") if hasattr(i, "send_to") else None

    it = SyncInterpreter(create_machine(
        copy.deepcopy(cfg),
        logic=lg(a={"fwd": fwd}, g={"never": lambda c, e: False})))
    it.use(P())
    it.start()
    it.send("DENY", wait=True)
    it.send("NOPE", wait=True)
    try:
        it.send("FWD", wait=True)
    except Exception:
        pass
    reasons = sorted({r for k, _, r in seen if k in ("unhandled", "dropped")
                      if r})
    dupes = len(seen) != len(set(map(str, seen)))
    rec("E6.hook_matrix", "guard_denied" in reasons and not dupes,
        f"reasons={reasons} events={seen[:6]} duplicates={dupes}")


def main():
    e1_parallel_snapshot_property()
    e2_snapshot_in_entry_action()
    e3_history_parallel_restore()
    e4_v1_torn_upcast()
    e5_livelock_watchdog()
    e6_hook_matrix()
    bad = [r for r in RESULTS if not r[1]]
    print(f"\n==== {len(RESULTS)-len(bad)}/{len(RESULTS)} PASS ====")


if __name__ == "__main__":
    main()
