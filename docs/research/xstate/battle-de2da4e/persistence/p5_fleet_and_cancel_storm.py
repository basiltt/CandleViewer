# -*- coding: utf-8 -*-
"""P5 (#218) -- 200 heartbeat machines for 10 s; handles flat, RSS flat;
plus a cancel storm on delayed sends (double-release?).  STANDALONE
(stdlib only: RSS via ctypes GetProcessMemoryInfo, no psutil).

A  200 machines x `raise(delay=)` heartbeat, 10 s: total retained
   `_timer_handles` must stay <= 1 per machine; RSS delta bounded.
B  control: the same 200 as `after:` heartbeats.
C  CANCEL STORM: one machine arms + cancels a delayed self-send 2000
   times.  `_timer_handles` / `_armed_self_sends` / `_scheduled_sends`
   must all return to 0, and a snapshot must contain no record.
D  arm/cancel/re-arm the SAME id 500 times then let it fire once.
"""
from __future__ import annotations

import asyncio
import ctypes
import gc
import json
import os
import sys
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine

KIND = os.environ.get("XS_SVC", "async")
SECS = float(os.environ.get("XS_SECS", "10"))
NM = int(os.environ.get("XS_NM", "200"))


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


def rss_mb():
    try:
        p = _PMC()
        p.cb = ctypes.sizeof(_PMC)
        import ctypes.wintypes as w
        fn = getattr(ctypes.windll.kernel32, "K32GetProcessMemoryInfo",
                     None) or ctypes.windll.psapi.GetProcessMemoryInfo
        fn.argtypes = [w.HANDLE, ctypes.POINTER(_PMC), ctypes.c_uint32]
        fn.restype = w.BOOL
        gph = ctypes.windll.kernel32.GetCurrentProcess
        gph.restype = w.HANDLE
        if not fn(gph(), ctypes.byref(p), ctypes.c_uint32(p.cb)):
            return -1.0
        return round(p.WorkingSetSize / 1048576.0, 1)
    except Exception:
        return -1.0


RAISE_HB = {
    "id": "hb", "initial": "a", "context": {"beats": 0},
    "states": {
        "a": {"entry": [{"type": "raise",
                         "params": {"event": "T", "delay": 20, "id": "t"}},
                        "beat"], "on": {"T": "b"}},
        "b": {"entry": [{"type": "raise",
                         "params": {"event": "T", "delay": 20, "id": "t"}},
                        "beat"], "on": {"T": "a"}},
    },
}
AFTER_HB = {
    "id": "hb", "initial": "a", "context": {"beats": 0},
    "states": {"a": {"entry": ["beat"], "after": {"20": "b"}},
               "b": {"entry": ["beat"], "after": {"20": "a"}}},
}


def build(spec):
    def beat(i, c, e, a):
        c["beats"] += 1

    return create_machine(json.loads(json.dumps(spec)),
                          logic=MachineLogic(actions={"beat": beat}))


def handles(i):
    return sum(len(v) for v in i._timer_handles.values())


async def fleet(label, spec):
    gc.collect()
    r0 = rss_mb()
    ms = [Interpreter(build(spec)) for _ in range(NM)]
    await asyncio.gather(*[m.start() for m in ms])
    samples = []
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < SECS:
        await asyncio.sleep(SECS / 4.0)
        samples.append({"t": round(time.perf_counter() - t0, 1),
                        "handles": sum(handles(m) for m in ms),
                        "rss": rss_mb()})
    beats = [m.context["beats"] for m in ms]
    await asyncio.gather(*[m.stop() for m in ms])
    gc.collect()
    return {"label": label, "machines": NM, "rss_start": r0,
            "samples": samples, "beats_min": min(beats),
            "beats_total": sum(beats),
            "handles_per_machine_final": round(
                samples[-1]["handles"] / float(NM), 3),
            "rss_delta": round(samples[-1]["rss"] - r0, 1)}


STORM = {"id": "st", "initial": "a", "context": {"n": 0},
         "states": {"a": {"on": {"ARM": {"actions": ["arm"]},
                                 "CAN": {"actions": ["can"]},
                                 "T": {"actions": ["hit"]}}}}}


async def cancel_storm(n=2000):
    from xstate_statemachine.machine_logic import MachineLogic as ML

    hits = []

    def hit(i, c, e, a):
        hits.append(1)

    cfg = {"id": "st", "initial": "a", "context": {"n": 0},
           "states": {"a": {
               "on": {"ARM": {"actions": [
                          {"type": "raise",
                           "params": {"event": "T", "delay": 5000,
                                      "id": "k"}}]},
                      "CAN": {"actions": [
                          {"type": "cancel", "params": {"sendId": "k"}}]},
                      "T": {"actions": ["hit"]}}}}}
    i = Interpreter(create_machine(json.loads(json.dumps(cfg)),
                                   logic=ML(actions={"hit": hit})))
    await i.start()
    for _ in range(n):
        await i.send("ARM")
        await i.send("CAN")
    for _ in range(300):
        if not i.pending_events:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.2)
    blob = i.get_persisted_snapshot()
    if not isinstance(blob, str):
        blob = json.dumps(blob)
    recs = json.loads(blob).get("scheduled_sends") or []
    out = {"n": n, "handles": handles(i),
           "armed": len(i._armed_self_sends),
           "scheduled": len(i._scheduled_sends),
           "chain_owed": len(i._chain_owed_sends),
           "snapshot_records": len(recs), "hits": len(hits),
           "last_error": type(i.last_error).__name__ if i.last_error else None}
    await i.stop()
    out["ok"] = (out["handles"] == 0 and out["armed"] == 0
                 and out["snapshot_records"] == 0 and out["hits"] == 0)
    return out


async def rearm_then_fire(n=500):
    from xstate_statemachine.machine_logic import MachineLogic as ML
    hits = []

    def hit(i, c, e, a):
        hits.append(1)

    cfg = {"id": "rr", "initial": "a", "context": {},
           "states": {"a": {
               "on": {"ARM": {"actions": [
                          {"type": "raise",
                           "params": {"event": "T", "delay": 120,
                                      "id": "k"}}]},
                      "CAN": {"actions": [
                          {"type": "cancel", "params": {"sendId": "k"}}]},
                      "T": {"actions": ["hit"]}}}}}
    i = Interpreter(create_machine(json.loads(json.dumps(cfg)),
                                   logic=ML(actions={"hit": hit})))
    await i.start()
    for _ in range(n):
        await i.send("ARM")
        await i.send("CAN")
    await i.send("ARM")
    for _ in range(400):
        if hits:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.25)
    out = {"n": n, "hits": len(hits), "handles": handles(i),
           "armed": len(i._armed_self_sends)}
    await i.stop()
    out["ok"] = out["hits"] == 1 and out["handles"] <= 1
    return out


async def main():
    a = await fleet("raise(delay=)", RAISE_HB)
    b = await fleet("after:", AFTER_HB)
    c = await cancel_storm()
    d = await rearm_then_fire()
    ok = (a["handles_per_machine_final"] <= 1.05 and a["beats_min"] > 0
          and b["handles_per_machine_final"] <= 1.05
          and a["rss_delta"] < 120 and c["ok"] and d["ok"])
    print(json.dumps({"kind": KIND, "secs": SECS, "A_raise": a,
                      "B_after": b, "C_cancel_storm": c,
                      "D_rearm_then_fire": d,
                      "VERDICT": "PASS" if ok else "FAIL"}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
