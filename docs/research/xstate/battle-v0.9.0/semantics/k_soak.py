"""SEMANTICS @ v0.9.0 -- soak: 200 machines, both kinds, action-spawned
workers outliving their actions, raise(delay=) heartbeats, external priority
traffic, and chaos v3 snapshot/restore WITH plugins= every 2 s.

Invariants: heartbeats flat, chain_trips stable at 0, 0 dropped external,
no RuntimeWarning noise (#232), RSS bounded, timer handles <= 1 per machine.

SOAK_SECONDS (default 120), SOAK_MACHINES per kind (default 100).
Standalone: stdlib + xstate_statemachine only.
"""
from __future__ import annotations

import asyncio
import gc
import json
import logging
import os
import sys
import warnings
from typing import Any, Dict, List

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase

logging.disable(logging.CRITICAL)
SECS = float(os.environ.get("SOAK_SECONDS", "120"))
N = int(os.environ.get("SOAK_MACHINES", "100"))


def _rss_mb() -> float:
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        psapi = ctypes.WinDLL("psapi")
        k32 = ctypes.WinDLL("kernel32")
        # 🧷 declare the prototypes: GetCurrentProcess() returns a HANDLE
        #    (64-bit), and ctypes truncates it to int without this.
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        p = PMC()
        p.cb = ctypes.sizeof(PMC)
        ok = psapi.GetProcessMemoryInfo(
            k32.GetCurrentProcess(), ctypes.byref(p), ctypes.sizeof(PMC)
        )
        if not ok:
            return -1.0
        return float(p.WorkingSetSize) / 1048576.0
    except Exception:  # noqa: BLE001
        return -1.0


_R = {"type": "raise", "params": {"event": "B", "delay": 20}}
CFG = {
    "id": "s",
    "initial": "a",
    "maxIterations": 40,
    "states": {
        "a": {
            "entry": [_R, "spawn"],
            "on": {"B": "b", "EXT": {"actions": []}, "W": {"actions": []}},
        },
        "b": {
            "entry": [dict(_R), "spawn"],
            "on": {"B": "a", "EXT": {"actions": []}, "W": {"actions": []}},
        },
    },
}


class Cnt(PluginBase):
    def __init__(self) -> None:
        self.beats = 0
        self.ext = 0
        self.dropped = 0
        self.trips = 0

    def on_event_received(self, i, event):  # noqa: ANN001
        t = getattr(event, "type", "")
        if t == "B":
            self.beats += 1
        elif t == "EXT":
            self.ext += 1

    def on_event_dropped(self, i, e, r):  # noqa: ANN001
        self.dropped += 1

    def on_chain_budget_exceeded(self, i, err, ev):  # noqa: ANN001
        self.trips += 1


async def main() -> None:
    warnings.simplefilter("always", RuntimeWarning)
    seen: List[str] = []
    old_show = warnings.showwarning

    def _show(msg, cat, *a, **kw):  # noqa: ANN001
        if cat is RuntimeWarning:
            seen.append(str(msg)[:110])

    warnings.showwarning = _show  # type: ignore[assignment]

    holders: List[Any] = []
    machines, counters = [], []

    async def worker(i: Any) -> None:
        await asyncio.sleep(0.03)
        try:
            i.send("W")
        except Exception:  # noqa: BLE001
            pass

    for kind in ("async", "plain"):
        for _ in range(N):
            if kind == "async":

                async def spawn(i, c, e, a):  # noqa: ANN001
                    t = asyncio.ensure_future(worker(i))
                    holders.append(t)
                    t.add_done_callback(
                        lambda f: holders.remove(f) if f in holders else None
                    )
            else:

                def spawn(i, c, e, a):  # noqa: ANN001
                    t = asyncio.ensure_future(worker(i))
                    holders.append(t)
                    t.add_done_callback(
                        lambda f: holders.remove(f) if f in holders else None
                    )

            m = Interpreter(
                create_machine(json.loads(json.dumps(CFG)),
                               logic=MachineLogic(actions={"spawn": spawn}))
            )
            c = Cnt()
            m.use(c)
            m.kind = kind  # type: ignore[attr-defined]
            machines.append(m)
            counters.append(c)

    await asyncio.gather(*(m.start() for m in machines))
    gc.collect()
    rss0 = _rss_mb()
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    ext_sent = 0
    restores = {"ok": 0, "fail": 0, "with_sched": 0, "invalid_hook": 0}
    last_chaos = t0
    samples: List[Dict[str, Any]] = []

    class RObs(PluginBase):
        def __init__(self) -> None:
            self.n = 0

        def on_invalid_event(self, i, exc, event=None, **kw):  # noqa: ANN001
            self.n += 1

    while loop.time() - t0 < SECS:
        await asyncio.gather(
            *(m.send("EXT", priority=True) for m in machines),
            return_exceptions=True,
        )
        ext_sent += len(machines)
        await asyncio.sleep(0.02)
        if loop.time() - last_chaos >= 2.0:
            last_chaos = loop.time()
            for m in machines[::40]:
                try:
                    blob = json.dumps(m.get_persisted_snapshot())
                    o = RObs()
                    j = Interpreter.from_snapshot(
                        blob,
                        create_machine(json.loads(json.dumps(CFG)),
                                       logic=MachineLogic(
                                           actions={"spawn":
                                                    lambda *a: None})),
                        minimum_version=3, verify_machine_hash=False,
                        plugins=[o],
                    )
                    if json.loads(blob).get("scheduled_sends"):
                        restores["with_sched"] += 1
                    restores["invalid_hook"] += o.n
                    restores["ok"] += 1
                    try:
                        await j.stop()
                    except Exception:  # noqa: BLE001
                        pass
                except Exception:  # noqa: BLE001
                    restores["fail"] += 1
            gc.collect()
            samples.append(
                {
                    "t": round(loop.time() - t0, 1),
                    "rss": round(_rss_mb(), 1),
                    "beats": sum(c.beats for c in counters),
                    "handles": sum(
                        len(getattr(m, "_armed_self_sends", {}) or {})
                        for m in machines
                    ),
                    "alive": sum(
                        str(getattr(m, "status", "")) == "running"
                        for m in machines
                    ),
                }
            )

    gc.collect()
    rss1 = _rss_mb()
    beats = sum(c.beats for c in counters)
    ext_ok = sum(c.ext for c in counters)
    dropped = sum(c.dropped for c in counters)
    trips = sum(c.trips for c in counters)
    handles_max = max(
        len(getattr(m, "_armed_self_sends", {}) or {}) for m in machines
    )
    alive = sum(str(getattr(m, "status", "")) == "running" for m in machines)
    await asyncio.gather(*(m.stop() for m in machines),
                         return_exceptions=True)
    warnings.showwarning = old_show

    out = {
        "seconds": SECS,
        "machines": len(machines),
        "beats": beats,
        "external_sent": ext_sent,
        "external_received": ext_ok,
        "external_dropped": ext_sent - ext_ok,
        "hook_dropped": dropped,
        "chain_trips": trips,
        "handles_max_per_machine": handles_max,
        "alive_at_end": alive,
        "rss_mb": {"start": round(rss0, 1), "end": round(rss1, 1),
                   "delta": round(rss1 - rss0, 1)},
        "chaos_restores": restores,
        "runtime_warnings": {"n": len(seen), "sample": seen[:3]},
        "samples": samples[-8:],
    }
    out["ok"] = (
        alive == len(machines)
        and trips == 0
        and out["external_dropped"] == 0
        and handles_max <= 1
        and len(seen) == 0
        and restores["fail"] == 0
    )
    print(json.dumps(out, indent=1))
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "k_soak.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print("\nk_soak: " + ("PASS" if out["ok"] else "FAIL"))
    sys.exit(0 if out["ok"] else 1)


if __name__ == "__main__":
    asyncio.run(main())
