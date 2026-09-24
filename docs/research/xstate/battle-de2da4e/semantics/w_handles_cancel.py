"""SEMANTICS @ de2da4e -- #218 handle reclamation at scale + cancel storms.

W1  200 heartbeat machines (100 `def` + 100 `async def`) x 10 s of
    raise(delay=) beats: retained timer handles must stay FLAT (<=1 per
    machine, per #218) and RSS must stay flat.  RSS via stdlib only
    (ctypes / GetProcessMemoryInfo) -- no psutil.
W2  Cancel storm: arm and cancel a delayed self-send by id thousands of
    times -- no double-release, no negative/duplicate handle accounting,
    no leak, on BOTH engines.
W3  Interleaved fire-vs-cancel race: cancel a send at the exact moment it
    is due, 500 rounds -- must never raise, never double-fire.

Standalone: stdlib + xstate_statemachine only, every helper inlined.
"""
from __future__ import annotations

import asyncio, ctypes, json, logging, os, sys, traceback
from typing import Any, Callable, Dict, List

from xstate_statemachine import (
    Interpreter, MachineLogic, SyncInterpreter, create_machine,
)

logging.disable(logging.CRITICAL)
_REG: List[Dict[str, Any]] = []
SECS = float(os.environ.get("W1_SECONDS", "10"))
N_PER_KIND = int(os.environ.get("W1_MACHINES", "100"))


def attack(aid: str, title: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        _REG.append({"id": aid, "title": title, "fn": fn})
        return fn
    return deco


# --- RSS without psutil (Windows PROCESS_MEMORY_COUNTERS; else /proc) ---
class _PMC(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_uint32), ("PageFaultCount", ctypes.c_uint32),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def rss_mb() -> float:
    if sys.platform == "win32":
        p = _PMC()
        p.cb = ctypes.sizeof(_PMC)
        h = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.psapi.GetProcessMemoryInfo(
                h, ctypes.byref(p), p.cb):
            return p.WorkingSetSize / 1e6
        return -1.0
    try:
        with open("/proc/self/statm", encoding="utf-8") as fh:
            return int(fh.read().split()[1]) * 4096 / 1e6
    except Exception:  # noqa: BLE001
        return -1.0


def handles(i: Any) -> int:
    """Total retained clock handles across every owner key."""
    th = getattr(i, "_timer_handles", {}) or {}
    return sum(len(v) for v in th.values())


HB = {
    "id": "h", "initial": "a", "maxIterations": 30,
    "states": {
        "a": {"entry": ["beat", {"type": "raise",
                                 "params": {"event": "T", "delay": 10}}],
              "on": {"T": "b"}},
        "b": {"entry": ["beat", {"type": "raise",
                                 "params": {"event": "T", "delay": 10}}],
              "on": {"T": "a"}},
    },
}


@attack("W1", "200 raise(delay=) heartbeat machines x 10 s: retained timer "
              "handles FLAT (#218) and RSS flat -- both action kinds")
async def w1() -> Dict[str, Any]:
    interps: List[Any] = []
    counts: List[Dict[str, int]] = []
    for kind in ("plain", "async"):
        for k in range(N_PER_KIND):
            box = {"n": 0}
            counts.append(box)
            if kind == "async":
                async def beat(i, c, e, a, _b=box):  # noqa: ANN001
                    _b["n"] += 1
            else:
                def beat(i, c, e, a, _b=box):  # noqa: ANN001
                    _b["n"] += 1
            cfg = json.loads(json.dumps(HB))
            cfg["id"] = f"h{kind}{k}"
            interps.append(Interpreter(create_machine(
                cfg, logic=MachineLogic(actions={"beat": beat}))))
    await asyncio.gather(*[i.start() for i in interps])
    rss0 = rss_mb()
    samples: List[Dict[str, Any]] = []
    for t in range(int(SECS)):
        await asyncio.sleep(1.0)
        samples.append({"t": t + 1, "beats": sum(b["n"] for b in counts),
                        "handles": sum(handles(i) for i in interps),
                        "rss_delta_mb": round(rss_mb() - rss0, 2)})
    beats = sum(b["n"] for b in counts)
    h_end = sum(handles(i) for i in interps)
    h_max = max(handles(i) for i in interps)
    alive = sum(1 for b in counts if b["n"] > 0)
    rss_delta = rss_mb() - rss0
    await asyncio.gather(*[i.stop() for i in interps])
    n = len(interps)
    return {"ok": h_max <= 1 and h_end <= n and rss_delta < 50
            and alive == n,
            "machines": n, "beats": beats, "beats_per_machine": beats // n,
            "handles_end": h_end, "handles_max_per_machine": h_max,
            "alive": alive, "rss_delta_mb": round(rss_delta, 2),
            "samples": samples}


CANCEL = {
    "id": "cz", "initial": "a", "maxIterations": 200,
    "states": {
        "a": {"on": {
            "ARM": {"actions": [{"type": "raise",
                                 "params": {"event": "Z", "delay": 5000,
                                            "id": "S"}}]},
            "CANCEL": {"actions": [{"type": "cancel",
                                    "params": {"sendId": "S"}}]},
            "Z": "fired"}},
        "fired": {},
    },
}


@attack("W2", "Cancel storm: 3000 arm/cancel cycles on one send id -- no "
              "double-release, no handle growth, both engines")
async def w2() -> Dict[str, Any]:
    cells: Dict[str, Any] = {}
    n = 3000
    # async engine
    i = Interpreter(create_machine(json.loads(json.dumps(CANCEL)),
                                   logic=MachineLogic()))
    await i.start()
    err = None
    try:
        for _ in range(n):
            await i.send("ARM")
            await i.send("CANCEL")
        # 🧪 POLL TO CONVERGENCE: a fixed 0.2 s settle left the final
        #    ARM/CANCEL pair still in the inbox and reported a phantom
        #    "1 armed" residue. Drain until the armed set is empty.
        for _ in range(100):
            await asyncio.sleep(0.02)
            if not getattr(i, "_armed_self_sends", {}):
                break
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
    cells["async"] = {"handles": handles(i), "err": err,
                      "state": sorted(i.current_state_ids),
                      "armed": len(getattr(i, "_armed_self_sends", {}) or {}),
                      "scheduled": len(getattr(i, "_scheduled_sends", {})
                                       or {})}
    await i.stop()
    # sync engine
    j = SyncInterpreter(create_machine(json.loads(json.dumps(CANCEL)),
                                       logic=MachineLogic()))
    j.start()
    err2 = None
    try:
        for _ in range(n):
            j.send("ARM")
            j.send("CANCEL")
    except Exception as exc:  # noqa: BLE001
        err2 = f"{type(exc).__name__}: {exc}"
    cells["sync"] = {"handles": handles(j), "err": err2,
                     "state": sorted(j.current_state_ids),
                     "armed": len(getattr(j, "_armed_self_sends", {}) or {}),
                     "scheduled": len(getattr(j, "_scheduled_sends", {})
                                      or {})}
    j.stop()
    ok = all(c["err"] is None and c["handles"] <= 1 and c["armed"] == 0
             and c["state"] == ["cz.a"] for c in cells.values())
    return {"ok": ok, "cycles": n, "cells": cells}


RACE = {
    "id": "rc", "initial": "a", "maxIterations": 200,
    "states": {
        "a": {"on": {
            "ARM": {"actions": [{"type": "raise",
                                 "params": {"event": "Z", "delay": 1,
                                            "id": "S"}}]},
            "CANCEL": {"actions": [{"type": "cancel",
                                    "params": {"sendId": "S"}}]},
            "Z": {"actions": ["hit"]}}},
    },
}


@attack("W3", "Fire-vs-cancel race: cancel a 1 ms send at its due instant, "
              "500 rounds -- no exception, no double-fire, no handle leak")
async def w3() -> Dict[str, Any]:
    hits = {"n": 0}

    def hit(i, c, e, a):  # noqa: ANN001
        hits["n"] += 1

    i = Interpreter(create_machine(json.loads(json.dumps(RACE)),
                                   logic=MachineLogic(actions={"hit": hit})))
    await i.start()
    err = None
    rounds = 500
    try:
        for _ in range(rounds):
            await i.send("ARM")
            await asyncio.sleep(0.001)
            await i.send("CANCEL")
        await asyncio.sleep(0.2)
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
    out = {"hits": hits["n"], "handles": handles(i), "err": err,
           "armed": len(getattr(i, "_armed_self_sends", {}) or {}),
           "last_error": type(i.last_error).__name__,
           "chain_trips": i.chain_trips}
    await i.stop()
    return {"ok": err is None and out["handles"] <= 1 and out["armed"] == 0
            and out["hits"] <= rounds, "rounds": rounds, "detail": out}


def main(group: str) -> None:
    out, npass = [], 0
    for a in _REG:
        rec: Dict[str, Any] = {"id": a["id"], "title": a["title"]}
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
        print(f"[{rec['status']:5}] {rec['id']:3} {a['title'][:84]}", flush=True)
        print("        -> " + json.dumps(rec["detail"], default=str)[:2200])
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{group}.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(f"\n{group}: {npass}/{len(out)} PASS")
    sys.exit(0 if npass == len(out) else 1)


if __name__ == "__main__":
    main("w_handles_cancel")
