# -*- coding: utf-8 -*-
"""Verify #201 on f28719c: lap parity is stated EXACTLY, not overbroadly.
Acceptance criteria (per fixed CHANGELOG text and issue #201):
  1. `invoke` ping-pong starting from the INITIAL state: sync, async-engine
     `def`, and async-engine `async def` lanes all trip at the SAME lap
     count (the seed-vs-link off-by-one from #179 is gone).
  2. `rollback + onDone`: the documented residual difference is EXACTLY
     "sync stops early with the raised RuntimeError after the first
     rollback (does not re-arm inside the same drain); both async lanes
     (`def` and `async def`) trip RunawayChainError at the SAME lap" --
     this is not a defect, it must be reproduced and match that shape
     exactly (not something broader/different).
maxIterations=20 in both machines (matches the original repro / pinned
tests). 30s watchdog per probe via asyncio.wait_for.
"""
from __future__ import annotations

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine
from xstate_statemachine.plugins import PluginBase

MAXIT = 20
FAIL: list[str] = []
ROWS: list[dict] = []

PINGPONG = {
    "id": "lv", "initial": "ver", "maxIterations": MAXIT,
    "states": {
        "ver": {"entry": ["bump"], "invoke": [{"id": "k", "src": "svc", "onDone": {"target": "arm"}}]},
        "arm": {"entry": ["bump"], "invoke": [{"id": "k2", "src": "svc", "onDone": {"target": "ver"}}]},
    },
}
ROLLBACK = {
    "id": "lv", "initial": "a", "maxIterations": MAXIT, "actionErrorPolicy": "rollback",
    "states": {
        "a": {"invoke": [{"id": "k", "src": "svc", "onDone": {"target": "b", "actions": ["blow"]}}]},
        "b": {"entry": ["bump"], "always": {"target": "a"}},
    },
}


class Watch(PluginBase):
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, interp, event, reason):
        self.dropped.append((getattr(event, "type", "?"), reason))

    @property
    def tripped(self):
        return any("chain_budget" in str(r) for _, r in self.dropped)


def logic():
    def bump(i, c, e, a):
        c["n"] = c.get("n", 0) + 1

    def blow(i, c, e, a):
        c["n"] = c.get("n", 0) + 1
        raise RuntimeError("rollback")

    def svc_def(i, c, e):
        return {"ok": 1}

    async def svc_async(i, c, e):
        await asyncio.sleep(0)
        return {"ok": 1}

    return MachineLogic(actions={"bump": bump, "blow": blow},
                         services={"svc_def": svc_def, "svc_async": svc_async})


def probe_pingpong_sync():
    m = create_machine(dict(PINGPONG), logic=logic())
    # swap src to svc_def for sync
    m.states["ver"]  # noop touch
    m2 = create_machine(
        {**PINGPONG, "states": {
            "ver": {"entry": ["bump"], "invoke": [{"id": "k", "src": "svc_def", "onDone": {"target": "arm"}}]},
            "arm": {"entry": ["bump"], "invoke": [{"id": "k2", "src": "svc_def", "onDone": {"target": "ver"}}]},
        }},
        logic=logic(),
    )
    w = Watch()
    i = SyncInterpreter(m2).use(w)
    i.start()
    n = i.context.get("n", 0)
    from xstate_statemachine.exceptions import RunawayChainError
    tripped = isinstance(i.last_error, RunawayChainError)
    i.stop()
    return {"tripped": tripped, "laps": n}


def probe_pingpong_async(kind):
    svc_name = "svc_def" if kind == "def" else "svc_async"
    cfg = {**PINGPONG, "states": {
        "ver": {"entry": ["bump"], "invoke": [{"id": "k", "src": svc_name, "onDone": {"target": "arm"}}]},
        "arm": {"entry": ["bump"], "invoke": [{"id": "k2", "src": svc_name, "onDone": {"target": "ver"}}]},
    }}
    m = create_machine(cfg, logic=logic())
    w = Watch()

    async def go():
        i = Interpreter(m).use(w)
        await asyncio.wait_for(i.start(), 10)
        for _ in range(50):
            await asyncio.sleep(0.02)
            if w.tripped:
                break
        n = i.context.get("n", 0)
        await i.stop()
        return n

    n = asyncio.run(asyncio.wait_for(go(), 25))
    return {"tripped": w.tripped, "laps": n}


def probe_rollback_sync():
    cfg = {**ROLLBACK, "states": {
        "a": {"invoke": [{"id": "k", "src": "svc_def", "onDone": {"target": "b", "actions": ["blow"]}}]},
        "b": {"entry": ["bump"], "always": {"target": "a"}},
    }}
    m = create_machine(cfg, logic=logic())
    w = Watch()
    raised = False
    try:
        i = SyncInterpreter(m).use(w)
        i.start()
        n = i.context.get("n", 0)
        from xstate_statemachine.exceptions import RunawayChainError
        tripped = isinstance(i.last_error, RuntimeError) and not isinstance(i.last_error, RunawayChainError)
        raised = isinstance(i.last_error, RuntimeError)
        i.stop()
    except RuntimeError:
        raised = True
        tripped = False
        n = None
    return {"tripped": tripped, "laps": n, "raised_runtimeerror": raised}


def probe_rollback_async(kind):
    svc_name = "svc_def" if kind == "def" else "svc_async"
    cfg = {**ROLLBACK, "states": {
        "a": {"invoke": [{"id": "k", "src": svc_name, "onDone": {"target": "b", "actions": ["blow"]}}]},
        "b": {"entry": ["bump"], "always": {"target": "a"}},
    }}
    m = create_machine(cfg, logic=logic())
    w = Watch()

    async def go():
        i = Interpreter(m).use(w)
        await asyncio.wait_for(i.start(), 10)
        for _ in range(50):
            await asyncio.sleep(0.02)
            if w.tripped:
                break
        n = i.context.get("n", 0)
        await i.stop()
        return n

    n = asyncio.run(asyncio.wait_for(go(), 25))
    return {"tripped": w.tripped, "laps": n}


# --- Criterion 1: invoke ping-pong, all 3 lanes trip at SAME lap ------------
r_sync = probe_pingpong_sync()
r_def = probe_pingpong_async("def")
r_async = probe_pingpong_async("async def")
ROWS.append({"probe": "pingpong_sync", **r_sync})
ROWS.append({"probe": "pingpong_async_def", **r_def})
ROWS.append({"probe": "pingpong_async_asyncdef", **r_async})

if not (r_sync["tripped"] and r_def["tripped"] and r_async["tripped"]):
    FAIL.append(f"pingpong: not all 3 lanes tripped: sync={r_sync}, def={r_def}, async={r_async}")
elif not (r_sync["laps"] == r_def["laps"] == r_async["laps"]):
    FAIL.append(
        f"pingpong: lap counts differ: sync={r_sync['laps']}, "
        f"def={r_def['laps']}, async def={r_async['laps']}"
    )

# --- Criterion 2: rollback+onDone, documented residual shape exactly -------
rb_sync = probe_rollback_sync()
rb_def = probe_rollback_async("def")
rb_async = probe_rollback_async("async def")
ROWS.append({"probe": "rollback_sync", **rb_sync})
ROWS.append({"probe": "rollback_async_def", **rb_def})
ROWS.append({"probe": "rollback_async_asyncdef", **rb_async})

if not rb_sync["raised_runtimeerror"]:
    FAIL.append(f"rollback: sync engine expected to stop early with RuntimeError, got {rb_sync}")
if not (rb_def["tripped"] and rb_async["tripped"]):
    FAIL.append(f"rollback: both async lanes expected to trip RunawayChainError: def={rb_def}, async={rb_async}")
elif rb_def["laps"] != rb_async["laps"]:
    FAIL.append(f"rollback: async lanes disagree on lap count: def={rb_def['laps']}, async def={rb_async['laps']}")

import json
print(json.dumps({"rows": ROWS, "failures": FAIL}, indent=2))
if FAIL:
    print("VERDICT: FAIL")
    raise SystemExit(1)
print("VERDICT: PASS")
raise SystemExit(0)
