"""D6-fuzz: shrink of F2's B2-illegal-configuration class on cec108b.

A compound state with ZERO active children after an event. The generated
case combined: an `always` from m.a.a back to its own ancestor #m.a (a
self-re-entry cycle) plus an invoke with onError. We ablate to find the
minimum shape and report the configuration legality of the resulting
machine on BOTH engines.
"""
from __future__ import annotations
import asyncio, copy, json, logging, sys
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, Interpreter, SyncInterpreter


def legality(interp) -> str:
    active = set(interp._active_state_nodes)
    problems = []
    stack = [interp.machine]
    while stack:
        n = stack.pop()
        kids = getattr(n, "states", None)
        if not kids:
            continue
        if n is not interp.machine and n not in active:
            continue
        ak = [c for c in kids.values() if c in active]
        if getattr(n, "type", "") == "parallel":
            if len(ak) != len(kids):
                problems.append(f"parallel {n.id}: {len(ak)}/{len(kids)}")
        else:
            if len(ak) != 1:
                problems.append(f"compound {n.id}: {len(ak)} active children")
        stack.extend(ak)
    return "; ".join(problems) or "LEGAL"


LOGIC = {
    "actions": {"act_a": lambda i, c, e, a: None},
    "guards": {"guard_true": lambda c, e: True},
    "services": {"svc_fail": lambda i, c, e: (_ for _ in ()).throw(RuntimeError("boom"))},
}


class L:
    def __init__(self):
        for k, v in LOGIC["actions"].items():
            setattr(self, k, v)
        for k, v in LOGIC["guards"].items():
            setattr(self, k, v)
        for k, v in LOGIC["services"].items():
            setattr(self, k, v)


def build(cfg, **kw):
    from xstate_statemachine import MachineLogic
    ml = MachineLogic(actions=dict(LOGIC["actions"]), guards=dict(LOGIC["guards"]),
                      services=dict(LOGIC["services"]))
    return create_machine(copy.deepcopy(cfg), logic=ml, **kw)


# ---- candidate shapes -------------------------------------------------
SHAPES = {}

# S1: always from a grandchild back to its own compound ancestor
SHAPES["S1_always_to_ancestor"] = {
    "id": "m", "initial": "a",
    "states": {
        "a": {"initial": "a", "states": {
            "a": {"always": {"target": "#m.a", "guard": "guard_true"},
                  "on": {"GO": {"target": "#m.a.b"}}},
            "b": {},
        }},
    },
}

# S2: same + a failing invoke on the ancestor
SHAPES["S2_always_to_ancestor_plus_invoke"] = {
    "id": "m", "initial": "a",
    "states": {
        "a": {"initial": "a",
              "invoke": {"id": "i", "src": "svc_fail", "onError": "#m.a.b"},
              "states": {
                  "a": {"always": {"target": "#m.a", "guard": "guard_true"},
                        "on": {"GO": {"target": "#m.a.b"}}},
                  "b": {},
              }},
    },
}

# S3: invoke onError targeting a *sibling subtree* leaf while an always cycles
SHAPES["S3_invoke_onError_crossbranch"] = {
    "id": "m", "initial": "a",
    "states": {
        "a": {"initial": "a",
              "invoke": {"id": "i", "src": "svc_fail", "onError": "#m.a.c.a"},
              "states": {
                  "a": {"always": {"target": "#m.a", "guard": "guard_true"},
                        "on": {"GO": {"target": "#m.a.b"}}},
                  "b": {},
                  "c": {"initial": "a", "states": {"a": {}}},
              }},
    },
}


def run_sync(name, cfg):
    try:
        m = build(cfg)
    except Exception as exc:
        return f"{name:38s} sync  BUILD-REJECT {type(exc).__name__}"
    it = SyncInterpreter(m)
    try:
        it.start()
    except Exception as exc:
        return f"{name:38s} sync  START-RAISE {type(exc).__name__}"
    pre = legality(it)
    try:
        it.send("GO")
    except Exception as exc:
        return (f"{name:38s} sync  start_legal={pre!r} "
                f"send-raise {type(exc).__name__}")
    return (f"{name:38s} sync  start={pre!r} after_GO={legality(it)!r} "
            f"states={sorted(it.current_state_ids)} status={it.status} "
            f"ok={getattr(it, 'last_transition_ok', None)} "
            f"err={type(getattr(it, 'last_error', None)).__name__}")


async def run_async(name, cfg):
    try:
        m = build(cfg)
    except Exception as exc:
        return f"{name:38s} async BUILD-REJECT {type(exc).__name__}"
    it = Interpreter(m)
    try:
        await asyncio.wait_for(it.start(), timeout=8)
    except Exception as exc:
        return f"{name:38s} async START {type(exc).__name__}"
    pre = legality(it)
    try:
        await asyncio.wait_for(it.send("GO"), timeout=8)
    except Exception as exc:
        out = (f"{name:38s} async start={pre!r} send-raise "
               f"{type(exc).__name__}")
        await _stop(it)
        return out
    out = (f"{name:38s} async start={pre!r} after_GO={legality(it)!r} "
           f"states={sorted(it.current_state_ids)} status={it.status}")
    await _stop(it)
    return out


async def _stop(it):
    try:
        await asyncio.wait_for(it.stop(), timeout=5)
    except Exception:
        pass


def main():
    for name, cfg in SHAPES.items():
        print(run_sync(name, cfg), flush=True)
        print(asyncio.run(run_async(name, cfg)), flush=True)
        print(flush=True)


if __name__ == "__main__":
    main()
