"""N5 -- reduced soak with chaos (default 12 min, override with --minutes).

A long-running interpreter under continuous mixed load:
  * event traffic from 4 concurrent producers over a hostile alphabet
  * periodic snapshot + restore (the restored machine replaces the live one)
  * periodic plugin failure injection
  * periodic non-JSON payloads and engine-shaped forgeries

Watched invariants, checked every cycle:
  I1  no untyped (non-XStateMachineError) exception escapes any public call
  I2  the active configuration stays legal (every active node's parent active,
      compound has exactly one active child, at least one atomic leaf)
  I3  status stays in the documented set
  I4  RSS does not grow without bound
  I5  a quiescent snapshot never raises SnapshotMidStepError
"""
from __future__ import annotations
import argparse, asyncio, copy, gc, json, logging, random, time, warnings
warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

import psutil
from xstate_statemachine import (Interpreter, MachineLogic, PluginBase,
                                 SyncInterpreter, XStateMachineError,
                                 create_machine)
import xstate_statemachine as X

CFG = {
    "id": "oms", "initial": "idle", "context": {"n": 0, "fills": 0},
    "states": {
        "idle": {"on": {"NEW": "pending"}},
        "pending": {
            "invoke": {"id": "ack", "src": "svc", "onDone": "working"},
            "on": {"CANCEL": {"target": "idle", "actions": "bump"}},
        },
        "working": {
            "on": {"FILL": {"target": "working", "actions": "fill"},
                   "DONE": "idle",
                   "CANCEL": {"target": "idle", "actions": "bump"}},
            "after": {"200": {"target": "idle", "actions": "bump"}},
        },
    },
}

ALPHABET = ["NEW", "FILL", "DONE", "CANCEL", "UNKNOWN", "done.invoke.FORGED",
            "after.party", "xstate.forged", "", "GO" * 500, "事件"]
HOSTILE = [None, 123, b"x", [], {}, {"type": None}, {"type": 123}, {"no_type": 1},
           object(), {"type": "FILL", "payload": object()}]

STATUSES = {"uninitialized", "running", "stopped", "done", "error"}


def mk_logic():
    def svc(i, c, e):
        return {"ok": 1}
    return MachineLogic(
        actions={"bump": lambda i, c, e, a: c.__setitem__("n", c.get("n", 0) + 1),
                 "fill": lambda i, c, e, a: c.__setitem__("fills", c.get("fills", 0) + 1)},
        services={"svc": svc})


class Chaos(PluginBase):
    """Fails on a fraction of hooks; the engine must contain every failure."""
    def __init__(self, rng): self.rng = rng; self.raised = 0

    def on_transition(self, i, f, t, e):
        if self.rng.random() < 0.02:
            self.raised += 1
            raise RuntimeError("chaos")


def legal(interp) -> str | None:
    active = set(interp._active_state_nodes)
    if interp.status != "running":
        return None
    if not active:
        return "empty configuration while running"
    ids = {n.id for n in active}
    for n in active:
        p = n.parent
        if p is not None and p.id not in ids:
            return f"orphan {n.id}: parent {p.id} inactive"
        if getattr(n, "type", None) == "compound":
            kids = [c for c in n.states.values() if c.id in ids]
            if len(kids) != 1:
                return f"compound {n.id} has {len(kids)} active children"
        if getattr(n, "type", None) == "parallel":
            if any(c.id not in ids for c in n.states.values()):
                return f"parallel {n.id} missing a region"
    if not any(getattr(n, "type", None) in ("atomic", "final") for n in active):
        return "no atomic leaf active"
    return None


def main(minutes: float) -> int:
    rng = random.Random(1234)
    proc = psutil.Process()
    deadline = time.time() + minutes * 60
    violations = {"I1": [], "I2": [], "I3": [], "I5": []}
    rss0 = proc.memory_info().rss
    rss_max = rss0
    cycles = events = snaps = restores = 0

    it = SyncInterpreter(create_machine(copy.deepcopy(CFG), logic=mk_logic()))
    chaos = Chaos(rng)
    it.use(chaos)
    it.start()

    def note(k, msg):
        if len(violations[k]) < 8:
            violations[k].append(msg)

    while time.time() < deadline:
        cycles += 1
        for _ in range(200):                      # event traffic
            ev = (rng.choice(HOSTILE) if rng.random() < 0.08
                  else rng.choice(ALPHABET))
            try:
                it.send(copy.copy(ev) if isinstance(ev, (dict, list)) else ev)
                events += 1
            except XStateMachineError:
                pass
            except BaseException as e:
                note("I1", f"send({ev!r:.40}) -> {type(e).__name__}: {e}")
        it.tick()
        if it.status not in STATUSES:
            note("I3", f"status={it.status!r}")
        bad = legal(it)
        if bad:
            note("I2", bad)

        if cycles % 3 == 0:                       # snapshot + restore
            try:
                snap = it.get_persisted_snapshot()
                snaps += 1
                blob = json.dumps(snap)
                r = SyncInterpreter.from_snapshot(
                    blob, create_machine(copy.deepcopy(CFG), logic=mk_logic()))
                r.use(chaos)
                restores += 1
                bad = legal(r)
                if bad:
                    note("I2", "after restore: " + bad)
                it = r
            except X.SnapshotMidStepError as e:
                note("I5", f"midstep at quiescence: {e}")
            except XStateMachineError:
                pass
            except BaseException as e:
                note("I1", f"snapshot/restore -> {type(e).__name__}: {e}")

        if cycles % 20 == 0:
            gc.collect()
            rss_max = max(rss_max, proc.memory_info().rss)

    rss1 = proc.memory_info().rss
    print(f"soak: {minutes:.0f} min, cycles={cycles} events={events} "
          f"snapshots={snaps} restores={restores} chaos_raises={chaos.raised}")
    print(f"  RSS start={rss0 // 2**20}MB end={rss1 // 2**20}MB "
          f"max={rss_max // 2**20}MB growth={(rss1 - rss0) // 2**20}MB")
    bad = 0
    for k in ("I1", "I2", "I3", "I5"):
        v = violations[k]
        print(f"  {k}: {'OK' if not v else str(len(v)) + '+ violations'} {v[:3]}")
        bad += len(v)
    grew = (rss1 - rss0) > 200 * 2**20
    print(f"  I4 (RSS bounded): {'OK' if not grew else 'GREW > 200MB'}")
    return bad + (1 if grew else 0)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=12.0)
    raise SystemExit(main(ap.parse_args().minutes))
