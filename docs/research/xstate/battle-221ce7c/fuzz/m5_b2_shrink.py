"""m5 — automatic shrinker for the F2 B2-illegal-configuration class.

Takes the saved repro (config + recorded event script) and greedily deletes
state-chart substructure while the oracle (a compound node left with zero
active children on a running machine) still fires. Prints the minimal
config it can reach plus the exact event that tears the configuration.
"""
from __future__ import annotations
import asyncio, copy, json, os, sys, logging
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, Interpreter, XStateMachineError
from m3_b2_replay import logic

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.join(HERE, "out", "b2_repro.json")
OUT = os.path.join(HERE, "out", "b2_min.json")


def illegal(interp) -> str:
    active = set(interp._active_state_nodes)
    if interp.status != "running" or not active:
        return ""
    for node in active:
        kids = getattr(node, "states", None)
        if not kids:
            continue
        ak = [c for c in kids.values() if c in active]
        if getattr(node, "type", "") == "parallel":
            if len(ak) != len(kids):
                return f"parallel {node.id}: {len(ak)}/{len(kids)} regions"
        elif len(ak) != 1:
            return f"compound {node.id}: {len(ak)} active children"
    return ""


async def trial(cfg, events):
    """Returns (event, reason) on the first illegal configuration."""
    try:
        m = create_machine(copy.deepcopy(cfg), logic=logic())
    except Exception:
        return None
    it = Interpreter(m, strict=False)
    try:
        await asyncio.wait_for(it.start(), timeout=5)
    except Exception:
        return None
    try:
        r = illegal(it)
        if r:
            return ("<start>", r)
        for ev in events:
            try:
                await asyncio.wait_for(it.send(ev, wait=True), timeout=5)
            except XStateMachineError:
                pass
            except Exception:
                return None
            r = illegal(it)
            if r:
                return (ev, r)
    finally:
        try:
            await asyncio.wait_for(it.stop(), timeout=5)
        except Exception:
            pass
    return None


def walk_paths(cfg, prefix=()):
    """Yields paths to every `states` entry, deepest last."""
    states = cfg.get("states")
    if not isinstance(states, dict):
        return
    for k in list(states):
        yield prefix + (k,)
        yield from walk_paths(states[k], prefix + (k,))


def get_node(cfg, path):
    n = cfg
    for p in path:
        n = n["states"][p]
    return n


def drop(cfg, path):
    c = copy.deepcopy(cfg)
    parent = c
    for p in path[:-1]:
        parent = parent["states"][p]
    parent["states"].pop(path[-1], None)
    if not parent["states"]:
        return None
    if parent.get("initial") == path[-1]:
        parent["initial"] = next(iter(parent["states"]))
    return c


KEYS = ["entry", "exit", "after", "always", "invoke", "on", "output"]


def main(loops=4):
    rep = json.load(open(REPRO, encoding="utf-8"))
    cfg, events = rep["config"], rep.get("events") or ["GO"]
    events = [e for e in events if isinstance(e, str)] or ["GO"]
    base = asyncio.run(trial(cfg, events))
    print("baseline:", base, flush=True)
    if not base:
        print("repro does not reproduce as saved (see m4) -- nothing to shrink")
        return 1
    for _ in range(loops):
        changed = False
        for path in sorted(walk_paths(cfg), key=len, reverse=True):
            cand = drop(cfg, path)
            if cand is None:
                continue
            if asyncio.run(trial(cand, events)):
                cfg, changed = cand, True
        for path in [()] + list(walk_paths(cfg)):
            node = get_node(cfg, path)
            for k in KEYS:
                if k not in node:
                    continue
                saved = node.pop(k)
                if asyncio.run(trial(cfg, events)):
                    changed = True
                else:
                    node[k] = saved
        if not changed:
            break
    final = asyncio.run(trial(cfg, events))
    print("minimal reason:", final, flush=True)
    print(json.dumps(cfg, indent=1)[:2500], flush=True)
    json.dump({"config": cfg, "events": events, "reason": final},
              open(OUT, "w", encoding="utf-8"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
