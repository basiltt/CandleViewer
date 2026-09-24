"""H. Single-core refactor: Interpreter vs SyncInterpreter determinism parity.

Drives ONE machine -- nested + parallel + guards + always + entry/exit +
internal raise + after-timer -- through BOTH engines with an identical
event sequence, recording a full trace of every action fired, every
transition taken and the context after each event, then diffing.

H1  action/transition trace identical
H1b the same trace with the synthetic INIT transition filtered out
    (isolates the one divergence: see H7)
H2  context after every event identical
H3  final configuration identical
H4  repeat the async run: self-determinism (same engine, twice)
H5  the same for a machine with `onUnhandled: defer`
H6  the same for a machine with `actionErrorPolicy: rollback` + a raising action
H7  ISOLATED: does `on_transition` fire for the initial entry done by
    `start()`? The sync engine emits one; the async engine does not.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Probe  # noqa: E402

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

warnings.simplefilter("ignore", DeprecationWarning)
P = Probe("H — engine determinism parity")

CFG = {
    "id": "par",
    "initial": "boot",
    "context": {"n": 0, "trace": [], "armed": False},
    "states": {
        "boot": {
            "entry": ["mark"],
            "on": {"START": "live"},
        },
        "live": {
            "type": "parallel",
            "entry": ["mark"],
            "exit": ["mark"],
            "states": {
                "orders": {
                    "initial": "idle",
                    "states": {
                        "idle": {
                            "entry": ["mark"],
                            "on": {
                                "SUBMIT": {"target": "open", "actions": ["mark"]},
                            },
                        },
                        "open": {
                            "entry": ["mark"],
                            "exit": ["mark"],
                            "on": {
                                "FILL": {"actions": ["bump", "mark"]},
                                "ARM": {"actions": ["arm"]},
                                "CLOSE": {"target": "shut", "actions": ["mark"]},
                            },
                        },
                        "shut": {
                            "entry": ["mark"],
                            "always": [{"target": "idle", "guard": "is_armed"}],
                        },
                    },
                },
                "risk": {
                    "initial": "ok",
                    "states": {
                        "ok": {
                            "entry": ["mark"],
                            "on": {
                                "TRIP": {
                                    "target": "halted",
                                    "actions": [
                                        "mark",
                                        {
                                            "type": "raise",
                                            "params": {"event": {"type": "ECHO"}},
                                        },
                                    ],
                                }
                            },
                        },
                        "halted": {
                            "entry": ["mark"],
                            "on": {"ECHO": {"actions": ["mark"]}, "RESET": "ok"},
                        },
                    },
                },
            },
            "on": {"KILL": "boot"},
        },
    },
}

SEQUENCE = [
    "START",
    "SUBMIT",
    "FILL",
    "FILL",
    "TRIP",
    "ARM",
    "CLOSE",
    "RESET",
    "UNKNOWN_EVENT",
    "KILL",
    "START",
]


class Tracer(PluginBase):
    def __init__(self, trace):
        self.trace = trace

    def on_transition(self, interp, before, after, transition):
        self.trace.append(
            (
                "T",
                transition.source.id,
                transition.event,
                tuple(sorted(s.id for s in after)),
            )
        )


def build(trace, policy=None, unhandled=None, boom=False):
    def mark(i, c, e, a):
        trace.append(("A", "mark", e.type))

    def bump(i, c, e, a):
        c["n"] += 1
        trace.append(("A", "bump", e.type, c["n"]))

    def arm(i, c, e, a):
        c["armed"] = True
        trace.append(("A", "arm", e.type))

    def blow(i, c, e, a):
        trace.append(("A", "blow", e.type))
        raise RuntimeError("boom")

    cfg = json.loads(json.dumps(CFG))
    if policy:
        cfg["actionErrorPolicy"] = policy
    if unhandled:
        cfg["onUnhandled"] = unhandled
    if boom:
        cfg["states"]["live"]["states"]["orders"]["states"]["open"]["on"]["FILL"][
            "actions"
        ] = ["bump", "blow"]
    return create_machine(
        cfg,
        logic=MachineLogic(
            actions={"mark": mark, "bump": bump, "arm": arm, "blow": blow},
            guards={"is_armed": lambda c, e: bool(c.get("armed"))},
        ),
    )


async def run_async(**kw):
    trace, ctxs = [], []
    m = build(trace, **kw)
    i = Interpreter(m)
    i.use(Tracer(trace))
    await i.start()
    await asyncio.sleep(0.02)
    for ev in SEQUENCE:
        await i.send(ev)
        await asyncio.sleep(0.03)
        ctxs.append({k: v for k, v in i.context.items() if k != "trace"})
    final = sorted(i.current_state_ids)
    await i.stop()
    return trace, ctxs, final


def run_sync(**kw):
    trace, ctxs = [], []
    m = build(trace, **kw)
    i = SyncInterpreter(m)
    i.use(Tracer(trace))
    i.start()
    for ev in SEQUENCE:
        i.send(ev)
        ctxs.append({k: v for k, v in i.context.items() if k != "trace"})
    final = sorted(i.current_state_ids)
    i.stop()
    return trace, ctxs, final


INIT_EVENT = "___xstate_statemachine_init___"


def strip_init_transition(trace):
    """Drop the synthetic init `on_transition` the sync engine emits."""
    return [x for x in trace if not (x[0] == "T" and x[2] == INIT_EVENT)]


def _first_diff(a, b):
    for idx, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return f"index {idx}: async={x!r} sync={y!r}"
    if len(a) != len(b):
        return f"length {len(a)} vs {len(b)}; tail={a[len(b):] or b[len(a):]}"
    return "identical"


async def parity(label, **kw):
    at, ac, af = await run_async(**kw)
    st, sc, sf = run_sync(**kw)
    fat, fst = strip_init_transition(at), strip_init_transition(st)
    return {
        "trace": (at == st, _first_diff(at, st), len(at), len(st)),
        "trace_no_init": (fat == fst, _first_diff(fat, fst), len(fat)),
        "ctx": (ac == sc, _first_diff(ac, sc)),
        "final": (af == sf, f"async={af} sync={sf}"),
    }


async def main():
    base = await parity("base")
    P.check("H1", "action/transition trace parity", base["trace"][0],
            f"async_len={base['trace'][2]} sync_len={base['trace'][3]}; {base['trace'][1]}")
    P.check(
        "H1b",
        "trace parity minus the init hook",
        base["trace_no_init"][0],
        f"{base['trace_no_init'][2]} entries compared; {base['trace_no_init'][1]}",
    )
    P.check("H2", "per-event context parity", base["ctx"][0], base["ctx"][1])
    P.check("H3", "final configuration parity", base["final"][0], base["final"][1])

    a1, c1, f1 = await run_async()
    a2, c2, f2 = await run_async()
    P.check("H4", "async self-determinism", a1 == a2 and c1 == c2 and f1 == f2,
            _first_diff(a1, a2))

    d = await parity("defer", unhandled="defer")
    P.check("H5", "parity with onUnhandled=defer",
            d["trace_no_init"][0] and d["ctx"][0] and d["final"][0],
            f"trace(minus init): {d['trace_no_init'][1]}; ctx: {d['ctx'][1]}; "
            f"final: {d['final'][1]}")

    r = await parity("rollback", policy="rollback", boom=True)
    P.check("H6", "parity with rollback + raising action",
            r["trace_no_init"][0] and r["ctx"][0] and r["final"][0],
            f"trace(minus init): {r['trace_no_init'][1]}; ctx: {r['ctx'][1]}; "
            f"final: {r['final'][1]}")

    # H7: the single isolated divergence.
    at, _, _ = await run_async()
    st, _, _ = run_sync()
    a_init = [x for x in at if x[0] == "T" and x[2] == INIT_EVENT]
    s_init = [x for x in st if x[0] == "T" and x[2] == INIT_EVENT]
    P.check(
        "H7",
        "on_transition fires for start() entry",
        len(a_init) == len(s_init),
        f"async emitted {len(a_init)} init on_transition hook(s), "
        f"sync emitted {len(s_init)}: {s_init}",
    )
    P.report()


if __name__ == "__main__":
    asyncio.run(main())
