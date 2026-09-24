"""m7 — timing probe for the torn configuration seen in F2.

The captured case's torn snapshot was `active=['m','m.a','m.a.a']` with
`state_ids=[]` on the async engine: the compound `m.a.a` active with no
child. `m.a.a` carries `after: {19: "#m.a.a"}` — a self-targeting delayed
transition — and `maxIterations: 1`. Hypothesis: the `after` re-entry into
the *compound itself* costs one microstep, and the budget (1) stops the
macrostep before the initial child is entered, leaving the compound bare.

This probe drives that config with sleeps that straddle the 19 ms deadline
and samples legality on a fine grid.
"""
from __future__ import annotations
import asyncio, copy, json, logging, os, sys
logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    create_machine, Interpreter, SyncInterpreter, XStateMachineError,
)
from m3_b2_replay import logic

HERE = os.path.dirname(os.path.abspath(__file__))
CAP = os.path.join(HERE, "out", "b2_cap.json")


def torn(it):
    act = set(it._active_state_nodes)
    t = sorted(n.id for n in act
               if getattr(n, "states", None)
               and len([c for c in n.states.values() if c in act]) != 1)
    ids = sorted(it.current_state_ids)
    if t:
        return (f"torn={t} state_ids={ids} status={it.status} "
                f"ok={getattr(it, 'last_transition_ok', None)} "
                f"err={type(getattr(it, 'last_error', None)).__name__}")
    if it.status == "running" and not ids:
        return f"inert state_ids=[] status=running"
    return ""


async def probe_async(cfg, sleeps, events):
    m = create_machine(copy.deepcopy(cfg), logic=logic())
    it = Interpreter(m, strict=False)
    found = ""
    try:
        await asyncio.wait_for(it.start(), timeout=8)
        found = torn(it)
        for s in sleeps:
            if found:
                break
            await asyncio.sleep(s)
            found = torn(it)
            if found:
                break
            for ev in events:
                try:
                    await asyncio.wait_for(it.send(ev, wait=True), timeout=8)
                except Exception:
                    pass
                found = torn(it)
                if found:
                    break
    except Exception as exc:
        found = found or f"<harness {type(exc).__name__}>"
    finally:
        try:
            await asyncio.wait_for(it.stop(), timeout=5)
        except Exception:
            pass
    return found


def probe_sync(cfg, events, pumps=6):
    it = SyncInterpreter(create_machine(copy.deepcopy(cfg), logic=logic()))
    try:
        it.start()
    except Exception as exc:
        return f"<start {type(exc).__name__}>"
    r = torn(it)
    if r:
        return r
    import time
    for _ in range(pumps):
        time.sleep(0.021)
        for ev in events:
            try:
                it.send(ev)
            except Exception:
                pass
            r = torn(it)
            if r:
                return r
    return ""


def snapshot_outcome(cfg):
    """Best-effort: when torn, can the state still be persisted?"""
    return ""


def main(trials=25):
    cap = json.load(open(CAP, encoding="utf-8"))
    cfg = cap["repro"]["config"]
    events = [e for e in cap["repro"]["events"] if isinstance(e, str)]
    grids = {
        "pre-deadline": [0.0, 0.005, 0.005],
        "straddle": [0.018, 0.001, 0.001, 0.001],
        "post": [0.025, 0.025],
        "repeat": [0.019] * 5,
    }
    hits = {}
    for name, sleeps in grids.items():
        n = 0
        sample = ""
        for _ in range(trials):
            r = asyncio.run(probe_async(cfg, sleeps, events))
            if r:
                n += 1
                sample = sample or r
        hits[name] = (n, sample)
        print(f"  async grid={name:14s} {n}/{trials}  {sample}", flush=True)
    sn = 0
    ssample = ""
    for _ in range(trials):
        r = probe_sync(cfg, events)
        if r:
            sn += 1
            ssample = ssample or r
    print(f"  sync  pumped        {sn}/{trials}  {ssample}", flush=True)
    total = sum(v[0] for v in hits.values()) + sn
    print("TOTAL torn/inert observations:", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
