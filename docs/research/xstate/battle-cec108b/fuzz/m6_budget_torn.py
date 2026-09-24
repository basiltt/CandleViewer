"""m6 — D6-fuzz-1 minimal repro: a chain-budget trip leaves a TORN
configuration (a compound node active with zero active children), and the
machine reports `state_ids == []`, `status == "running"` and
`last_transition_ok == True`.

Derived from out/b2_cap.json (F2 async, maxIterations=1). The essential
shape is a chain of `always` transitions that descends one level per
microstep, so a low `maxIterations` stops the descent *between* entering a
compound node and entering its initial child.
"""
from __future__ import annotations
import asyncio, copy, json, logging, os, sys
logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    create_machine, MachineLogic, Interpreter, SyncInterpreter,
    XStateMachineError,
)

HERE = os.path.dirname(os.path.abspath(__file__))


def logic():
    return MachineLogic(
        actions={"act": lambda i, c, e, a: None},
        guards={"g": lambda c, e: True},
        services={"svc": lambda i, c, e: {"ok": 1}},
    )


# `always` ladder: m.a -> m.a.a -> m.a.a.a, one rung per microstep.
CFG = {
    "id": "m", "initial": "a",
    "on": {"GO": {"target": "#m.a", "internal": True}},
    "always": {"target": "#m.a.a", "guard": "g"},
    "states": {
        "a": {
            "initial": "a",
            "always": {"target": "#m.a.a.a", "guard": "g"},
            "states": {
                "a": {"initial": "a",
                      "states": {"a": {"type": "final"},
                                 "b": {"type": "final"}}},
                "b": {},
            },
        },
    },
}


def probe(interp, label):
    active = sorted(n.id for n in interp._active_state_nodes)
    ids = sorted(interp.current_state_ids)
    torn = []
    act = set(interp._active_state_nodes)
    for n in act:
        kids = getattr(n, "states", None)
        if kids and len([c for c in kids.values() if c in act]) != 1:
            torn.append(n.id)
    print(f"  {label:22s} active={active} state_ids={ids} "
          f"status={interp.status} ok={getattr(interp,'last_transition_ok',None)} "
          f"err={type(getattr(interp,'last_error',None)).__name__} torn={torn}",
          flush=True)
    return bool(torn) or (interp.status == "running" and not ids)


def snapshot_probe(interp, cls):
    try:
        s = interp.get_persisted_snapshot()
        out = f"snapshot PRODUCED state_ids={s.get('state_ids')}"
        try:
            cls.from_snapshot(s, create_machine(copy.deepcopy(CFG),
                                                logic=logic(),
                                                ))
            out += " restore=ACCEPTED"
        except XStateMachineError as exc:
            out += f" restore={type(exc).__name__}"
        except Exception as exc:
            out += f" restore=UNTYPED {type(exc).__name__}"
    except XStateMachineError as exc:
        out = f"snapshot refused {type(exc).__name__}"
    except Exception as exc:
        out = f"snapshot UNTYPED {type(exc).__name__}"
    print(f"    {out}", flush=True)


def run_sync(mi):
    cfg = copy.deepcopy(CFG)
    cfg["maxIterations"] = mi
    it = SyncInterpreter(create_machine(cfg, logic=logic()))
    try:
        it.start()
    except Exception as exc:
        print(f"  sync  maxIterations={mi}: start raised "
              f"{type(exc).__name__}", flush=True)
        return False
    bad = probe(it, f"sync mi={mi} start")
    if bad:
        snapshot_probe(it, SyncInterpreter)
        try:
            it.send("GO")
            probe(it, f"sync mi={mi} after GO")
        except Exception as exc:
            print(f"    send raised {type(exc).__name__}")
    return bad


async def run_async(mi):
    cfg = copy.deepcopy(CFG)
    cfg["maxIterations"] = mi
    it = Interpreter(create_machine(cfg, logic=logic()), strict=False)
    try:
        await asyncio.wait_for(it.start(), timeout=8)
    except Exception as exc:
        print(f"  async maxIterations={mi}: start raised "
              f"{type(exc).__name__}", flush=True)
        return False
    bad = probe(it, f"async mi={mi} start")
    if bad:
        snapshot_probe(it, Interpreter)
        try:
            await asyncio.wait_for(it.send("GO", wait=True), timeout=8)
            probe(it, f"async mi={mi} after GO")
        except Exception as exc:
            print(f"    send raised {type(exc).__name__}")
    try:
        await asyncio.wait_for(it.stop(), timeout=5)
    except Exception:
        pass
    return bad


def replay_captured():
    """Replay the exact F2 case captured in out/b2_cap.json."""
    path = os.path.join(HERE, "out", "b2_cap.json")
    if not os.path.exists(path):
        print("no b2_cap.json; skipping captured replay")
        return []
    cap = json.load(open(path, encoding="utf-8"))
    cfg = cap["repro"]["config"]
    events = [e for e in cap["repro"]["events"] if isinstance(e, str)]
    print(f"== captured F2 case: events={events} "
          f"maxIterations={cfg.get('maxIterations')} ==", flush=True)
    hits = []
    for trial in range(30):
        for engine in ("async", "sync"):
            bad = _replay_one(cfg, events, engine, trial)
            if bad:
                hits.append((engine, trial, bad))
    print(f"captured replay: {len(hits)}/60 torn", flush=True)
    for h in hits[:4]:
        print("   ", h, flush=True)
    return hits


def _torn(it):
    act = set(it._active_state_nodes)
    t = [n.id for n in act
         if getattr(n, "states", None)
         and len([c for c in n.states.values() if c in act]) != 1]
    if t:
        return (f"torn={sorted(t)} state_ids={sorted(it.current_state_ids)} "
                f"status={it.status} "
                f"ok={getattr(it, 'last_transition_ok', None)}")
    if it.status == "running" and not sorted(it.current_state_ids):
        return f"inert: state_ids=[] status=running"
    return ""


def _replay_one(cfg, events, engine, trial):
    try:
        m = create_machine(copy.deepcopy(cfg), logic=logic())
    except Exception:
        return ""
    if engine == "sync":
        it = SyncInterpreter(m)
        try:
            it.start()
        except Exception:
            return ""
        r = _torn(it)
        if r:
            return r
        for ev in events:
            try:
                it.send(ev)
            except Exception:
                pass
            r = _torn(it)
            if r:
                return r
        return ""
    return asyncio.run(_replay_async(m, events))


async def _replay_async(m, events):
    it = Interpreter(m, strict=False)
    try:
        await asyncio.wait_for(it.start(), timeout=8)
    except Exception:
        return ""
    try:
        r = _torn(it)
        if r:
            return r
        for ev in events:
            try:
                await asyncio.wait_for(it.send(ev, wait=True), timeout=8)
            except Exception:
                pass
            r = _torn(it)
            if r:
                return r
        return ""
    finally:
        try:
            await asyncio.wait_for(it.stop(), timeout=5)
        except Exception:
            pass


def main():
    hits = list(replay_captured())
    for mi in (1, 2, 3, 5, 20):
        if run_sync(mi):
            hits.append(("sync", mi))
        if asyncio.run(run_async(mi)):
            hits.append(("async", mi))
        print(flush=True)
    print("TORN/INERT at:", hits or "none")
    return 0 if not hits else 1


if __name__ == "__main__":
    sys.exit(main())
