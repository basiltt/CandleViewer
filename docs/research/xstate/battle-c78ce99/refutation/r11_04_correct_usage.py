# -*- coding: utf-8 -*-
"""R11-04 refutation: can CORRECT usage bound `_timer_handles` growth?
STANDALONE (stdlib + xstate_statemachine). Neutral cwd.

Variants tried, all the documented/obvious "do it right" postures:
  A  id-reusing heartbeat (supersede semantics)        -- repro's shape
  B  no id at all
  C  long period (250 ms) -- is it a rate artefact?
  D  self-loop in ONE state (never exits) vs. two-state ping-pong
  E  explicit `cancel` of the id before re-arming
Control: `after:` heartbeat.
Both engines; both def and async def action flavours.
"""
from __future__ import annotations
import asyncio, gc, json, sys, time
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine

def raise_cfg(*, use_id, period, one_state, cancel_first):
    arm = {"type": "raise", "params": {"event": "T", "delay": period}}
    if use_id:
        arm["params"]["id"] = "t"
    entry = ([{"type": "cancel", "params": {"sendId": "t"}}] if cancel_first else []) + [arm, "beat"]
    if one_state:
        return {"id": "hb", "initial": "a", "context": {"beats": 0},
                "states": {"a": {"entry": entry, "on": {"T": "a"}}}}
    return {"id": "hb", "initial": "a", "context": {"beats": 0},
            "states": {"a": {"entry": entry, "on": {"T": "b"}},
                       "b": {"entry": entry, "on": {"T": "a"}}}}

AFTER_CFG = {"id": "hb", "initial": "a", "context": {"beats": 0},
             "states": {"a": {"entry": ["beat"], "after": {"10": "b"}},
                        "b": {"entry": ["beat"], "after": {"10": "a"}}}}

def logic(flavour):
    if flavour == "async":
        async def beat(i, c, e, a): c["beats"] += 1
    else:
        def beat(i, c, e, a): c["beats"] += 1
    return MachineLogic(actions={"beat": beat})

def probe(i):
    hs = i._timer_handles.get(i.id, [])
    fired = sum(1 for h in hs if getattr(h, "_cancelled", False) or getattr(h, "_callback", 1) is None)
    return len(hs), fired

async def run_async(cfg, flavour, secs):
    i = Interpreter(create_machine(cfg, logic=logic(flavour)))
    await i.start(); await asyncio.sleep(secs)
    n, fired = probe(i); beats = i.context["beats"]
    await i.stop(); gc.collect()
    return {"beats": beats, "handles": n, "dead_handles": fired,
            "per_beat": round(n / max(beats, 1), 3)}

def run_sync(cfg, flavour, secs):
    i = SyncInterpreter(create_machine(cfg, logic=logic(flavour)))
    i.start(); t0 = time.time()
    while time.time() - t0 < secs:
        time.sleep(0.004); i.send("NOOP")
    n, fired = probe(i); beats = i.context["beats"]
    i.stop()
    return {"beats": beats, "handles": n, "dead_handles": fired,
            "per_beat": round(n / max(beats, 1), 3)}

async def main():
    secs = 6.0
    cases = {
        "A id+pingpong": raise_cfg(use_id=True, period=10, one_state=False, cancel_first=False),
        "B noid+pingpong": raise_cfg(use_id=False, period=10, one_state=False, cancel_first=False),
        "C id+250ms": raise_cfg(use_id=True, period=250, one_state=False, cancel_first=False),
        "D id+selfloop": raise_cfg(use_id=True, period=10, one_state=True, cancel_first=False),
        "E cancel+rearm": raise_cfg(use_id=True, period=10, one_state=False, cancel_first=True),
        "CTRL after:10": AFTER_CFG,
    }
    out = {}
    for name, cfg in cases.items():
        for fl in ("plain", "async"):
            out[f"{name}/{fl}"] = await run_async(cfg, fl, secs)
    for name in ("A id+pingpong", "CTRL after:10"):
        for fl in ("plain", "async"):
            try:
                out[f"SYNC {name}/{fl}"] = run_sync(cases[name], fl, 4.0)
            except Exception as exc:
                out[f"SYNC {name}/{fl}"] = {"error": repr(exc)[:120]}
    print(json.dumps(out, indent=1))

asyncio.run(main())
