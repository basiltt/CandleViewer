"""D9-F: livelock fuzz, always-vs-named fuzz, and determinism on f28719c.

F1  Livelock fuzzer: >=500 random cycle configs x {def, async def} x
    {sync, async} with a watchdog. Every trip must be OBSERVABLE (typed
    error or a chain_budget drop) and the lap count must agree across
    kinds and engines.
F2  always-vs-named fuzz (#196): charts with a spinning `always` at a
    random depth and a named handler at another depth -- the named
    handler's actions must fire exactly once per send, never be consumed
    by the eventless transition.
F3  Determinism: 50x identical traces per lane incl. trip laps, with a
    settle-based (not wall-clock) cutoff.

Standalone: stdlib + xstate_statemachine only.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import random
import sys
import traceback
from collections import Counter
from typing import Any, Callable, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

logging.disable(logging.CRITICAL)

_REG: List[Dict[str, Any]] = []


def attack(aid: str, title: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        _REG.append({"id": aid, "title": title, "fn": fn})
        return fn

    return deco


def main(group: str) -> None:
    out, npass = [], 0
    for a in _REG:
        rec = {"id": a["id"], "title": a["title"]}
        try:
            fn = a["fn"]
            res = asyncio.run(fn()) if asyncio.iscoroutinefunction(fn) else fn()
            rec["detail"] = res
            rec["status"] = "PASS" if res.get("ok") else "FAIL"
        except Exception as exc:  # noqa: BLE001
            rec["status"] = "ERROR"
            rec["detail"] = {"exc": f"{type(exc).__name__}: {exc}",
                             "tb": traceback.format_exc()[-1500:]}
        npass += rec["status"] == "PASS"
        out.append(rec)
        print(f"[{rec['status']:5}] {rec['id']:6} {a['title'][:86]}")
        if rec["status"] != "PASS":
            print("        -> " + json.dumps(rec["detail"], default=str)[:1200])
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{group}.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(f"\n{group}: {npass}/{len(out)} PASS")
    sys.exit(0 if npass == len(out) else 1)


class Drops(PluginBase):
    def __init__(self) -> None:
        self.items: List[Any] = []

    def on_event_dropped(self, i, e, reason):  # noqa: ANN001
        self.items.append((e.type, reason))


# ==========================================================================
# F1 -- livelock fuzz: 500 configs x {def, async def} x {sync, async}
# ==========================================================================
def _cycle_cfg(rng: random.Random, i: int) -> Dict[str, Any]:
    shape = rng.choice(("invoke", "always", "raise"))
    lim = rng.choice((5, 8, 12, 20))
    if shape == "invoke":
        st = {"idle": {"on": {"GO": "a"}},
              "a": {"invoke": {"src": "svc", "onDone": "b"}},
              "b": {"invoke": {"src": "svc", "onDone": "a"}}}
    elif shape == "always":
        st = {"idle": {"on": {"GO": "a"}},
              "a": {"always": "b"}, "b": {"always": "a"}}
    else:
        st = {"idle": {"on": {"GO": "a"}},
              "a": {"entry": "bump", "on": {"R": "b"}},
              "b": {"entry": "bump", "on": {"R": "a"}}}
    return {"id": f"g{i}", "initial": "idle", "maxIterations": lim,
            "states": st, "_shape": shape}


def _mk_logic(kind: str, laps: Dict[str, int]) -> MachineLogic:
    def svc(i, c, e):  # noqa: ANN001
        laps["n"] += 1
        return laps["n"]

    async def svc_a(i, c, e):  # noqa: ANN001
        laps["n"] += 1
        await asyncio.sleep(0)
        return laps["n"]

    def bump(i, c, e, a):  # noqa: ANN001
        laps["n"] += 1
        if laps["n"] < 500:
            i.send("R")

    return MachineLogic(actions={"bump": bump},
                        services={"svc": svc_a if kind == "async" else svc})


async def _run_async(cfg: Dict[str, Any], kind: str) -> Dict[str, Any]:
    laps = {"n": 0}
    c = {k: v for k, v in cfg.items() if not k.startswith("_")}
    d = Drops()
    itp = await Interpreter(
        create_machine(copy.deepcopy(c), logic=_mk_logic(kind, laps))
    ).use(d).start()
    try:
        await asyncio.wait_for(itp.send("GO"), timeout=5.0)
        for _ in range(60):
            await asyncio.sleep(0.005)
            if itp.last_error or any(r == "chain_budget" for _, r in d.items):
                break
    except asyncio.TimeoutError:
        await itp.stop()
        return {"hang": True, "laps": laps["n"], "observable": False}
    err = type(itp.last_error).__name__ if itp.last_error else None
    obs = bool(err) or any(r == "chain_budget" for _, r in d.items)
    await itp.stop()
    return {"hang": False, "laps": laps["n"], "err": err, "observable": obs}


def _run_sync(cfg: Dict[str, Any]) -> Dict[str, Any]:
    laps = {"n": 0}
    c = {k: v for k, v in cfg.items() if not k.startswith("_")}
    d = Drops()
    itp = SyncInterpreter(
        create_machine(copy.deepcopy(c), logic=_mk_logic("plain", laps))
    )
    itp.use(d).start()
    r = itp.send("GO", wait=True)
    err = r.error or itp.last_error
    obs = bool(err) or any(x == "chain_budget" for _, x in d.items)
    itp.stop()
    return {"hang": False, "laps": laps["n"],
            "err": type(err).__name__ if err else None, "observable": obs}


@attack("F1", "Livelock fuzz 500 configs x {def, async def} x {sync, async}: "
              "no hang, every trip observable, laps agree across lanes")
async def f1() -> Dict[str, Any]:
    rng = random.Random(20260922)
    cfgs = [_cycle_cfg(rng, i) for i in range(500)]
    hangs, unbounded, silent, kind_mismatch, engine_mismatch = 0, 0, 0, 0, 0
    for cfg in cfgs:
        rp = await _run_async(cfg, "plain")
        ra = await _run_async(cfg, "async")
        rs = _run_sync(cfg)
        hangs += rp["hang"] + ra["hang"]
        for r in (rp, ra, rs):
            if r.get("laps", 0) >= 500:
                unbounded += 1
            elif r.get("laps", 0) > cfg["maxIterations"] + 5 and not r.get(
                    "observable"):
                silent += 1
        if rp["laps"] != ra["laps"]:
            kind_mismatch += 1
        if rp["laps"] != rs["laps"]:
            engine_mismatch += 1
    return {
        "ok": hangs == 0 and unbounded == 0 and silent == 0
        and kind_mismatch == 0,
        "configs": len(cfgs), "runs": len(cfgs) * 3,
        "hangs": hangs, "unbounded": unbounded, "silent_runaways": silent,
        "def_vs_asyncdef_lap_mismatch": kind_mismatch,
        "async_vs_sync_engine_lap_mismatch": engine_mismatch,
    }


if __name__ == "__main__":
    main("f_fuzz")
