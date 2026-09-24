"""v2 (@de2da4e) -- STANDALONE. #218 timer handle accounting + cancel storms.

H1  200-beat heartbeat, BOTH engines, BOTH kinds: the interpreter-owned
    handle list must hold <= 1 handle at every sample, not grow per beat.
H2  Cancel storm: arm N delayed self-sends with ids, cancel them all,
    re-arm, cancel again x rounds. Handles must return to 0 and
    `_armed_self_sends` to 0 -- no double-release crash, no leak.
H3  Superseding send id: re-arm the SAME id 500 times (each supersedes
    the previous, which calls the previous `_cancel`) -- the classic
    double-release shape. Handles bounded, exactly one fire.
H4  Cancel AFTER fire (explicit double-release): fire a send, then invoke
    cancel(id) for it. Must be a no-op, not an exception or a negative
    accounting.
H5  200 heartbeat machines x 10 s, async engine: handle count flat and
    RSS flat (RSS via ctypes on Windows / resource elsewhere -- no psutil).

Run: python v2_timer_handles_and_cancel_storm.py   (exit 1 == defect)
"""

from __future__ import annotations

import asyncio
import gc
import json
import os
import sys
import threading
import time
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

FAILS: List[str] = []
OUT: Dict[str, Any] = {}


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {
        "probe": name,
        "py": ".".join(map(str, sys.version_info[:3])),
        **data,
    }
    txt = json.dumps(data, indent=2, default=str)
    with open(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".json"),
        "w",
    ) as fh:
        fh.write(txt)
    print(txt)


def rss_mb() -> float:
    """RSS without psutil: Windows PROCESS_MEMORY_COUNTERS, else resource."""
    if sys.platform == "win32":
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

        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        # 🧷 Without explicit restype/argtypes the HANDLE returned by
        #    GetCurrentProcess is truncated to int32 on win64 and the call
        #    silently fails, leaving WorkingSetSize == 0.
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.windll.psapi
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if not psapi.GetProcessMemoryInfo(
            k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb
        ):
            raise OSError(ctypes.get_last_error())
        return pmc.WorkingSetSize / 1e6
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def n_handles(i: Any) -> int:
    """Total live clock handles the interpreter is holding."""
    return sum(len(v) for v in getattr(i, "_timer_handles", {}).values())


def n_armed(i: Any) -> int:
    return len(getattr(i, "_armed_self_sends", {}))


# 💓 A heartbeat must EXIT its state each beat or the transition is
#    internal and `entry` never re-arms (CV-C51). Two-state hop.
def hb_cfg(mid: str, period_ms: int) -> Dict[str, Any]:
    raise_a = {"type": "raise", "params": {"event": "TICK", "delay": period_ms}}
    return {
        "id": mid,
        "initial": "a",
        "context": {"n": 0},
        "states": {
            "a": {"entry": [raise_a, "tick"], "on": {"TICK": "b"}},
            "b": {"entry": [raise_a, "tick"], "on": {"TICK": "a"}},
        },
    }


def hb_logic(kind: str) -> MachineLogic:
    if kind == "def":

        def tick(i, ctx, e, ad):  # noqa: ANN001
            ctx["n"] = ctx.get("n", 0) + 1

        return MachineLogic(actions={"tick": tick})

    async def atick(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    return MachineLogic(actions={"atick_unused": atick, "tick": atick})


async def h1_async(kind: str) -> Dict[str, Any]:
    """200 beats on the async engine; sample handles every poll."""
    i = Interpreter(create_machine(hb_cfg("v2h1", 2), logic=hb_logic(kind)))
    await i.start()
    peak = 0
    samples: List[int] = []
    deadline = time.perf_counter() + 20.0
    while i.context.get("n", 0) < 200 and time.perf_counter() < deadline:
        h = n_handles(i)
        peak = max(peak, h)
        samples.append(h)
        await asyncio.sleep(0.005)
    beats = i.context.get("n", 0)
    end = n_handles(i)
    await i.stop()
    row = {"engine": "async", "kind": kind, "beats": beats,
           "peak_handles": peak, "end_handles": end,
           "samples": len(samples), "max_sample": max(samples or [0])}
    if beats < 200:
        FAILS.append(f"H1/async/{kind}: only {beats} beats in 20s")
    if peak > 1:
        FAILS.append(f"H1/async/{kind}: peak_handles={peak} (>1, #218 leak)")
    return row


def h1_sync(kind: str) -> Dict[str, Any]:
    """Same on the sync engine.

    🧭 HARNESS NOTE: `SyncInterpreter.start()` RETURNS once the initial
    descent settles -- it owns no thread. The clock is advanced by
    `tick()`, so the beat is driven from this loop (the u8 shape), not by
    a background `start()` thread.
    """
    i = SyncInterpreter(create_machine(hb_cfg("v2h1s", 2),
                                       logic=hb_logic("def")))
    i.start()
    peak = 0
    samples: List[int] = []
    deadline = time.perf_counter() + 20.0
    while i.context.get("n", 0) < 200 and time.perf_counter() < deadline:
        h = n_handles(i)
        peak = max(peak, h)
        samples.append(h)
        i.tick()
        time.sleep(0.001)
    beats = i.context.get("n", 0)
    end = n_handles(i)
    try:
        i.stop()
    except Exception:  # noqa: BLE001
        pass
    row = {"engine": "sync", "kind": "def", "beats": beats,
           "peak_handles": peak, "end_handles": end,
           "samples": len(samples), "max_sample": max(samples or [0])}
    if beats < 200:
        FAILS.append(f"H1/sync: only {beats} beats in 20s")
    if peak > 1:
        FAILS.append(f"H1/sync: peak_handles={peak} (>1, #218 leak)")
    return row


async def h2_cancel_storm(kind: str) -> Dict[str, Any]:
    """Arm 50 ids, cancel all, x10 rounds. Must return to zero each time."""
    cfg = {
        "id": "v2h2",
        "initial": "idle",
        "context": {"n": 0},
        "states": {"idle": {"on": {"PING": {"actions": ["tick"]}}}},
    }
    i = Interpreter(create_machine(cfg, logic=hb_logic(kind)))
    await i.start()
    rounds, N = 10, 50
    peaks, after_cancel, errs = [], [], []
    for r in range(rounds):
        for k in range(N):
            await i._deliver(i, i._prepare_event("PING"), 60000.0, f"s{r}_{k}")
        peaks.append((n_handles(i), n_armed(i)))
        for k in range(N):
            try:
                cancel = i._scheduled_sends.get(f"s{r}_{k}")
                if cancel:
                    cancel()
            except Exception as exc:  # noqa: BLE001
                errs.append(type(exc).__name__)
        after_cancel.append((n_handles(i), n_armed(i)))
    await i.stop()
    row = {"kind": kind, "rounds": rounds, "per_round": N,
           "peak_after_arm": peaks, "after_cancel": after_cancel,
           "errors": sorted(set(errs))}
    if errs:
        FAILS.append(f"H2/{kind}: cancel raised {set(errs)}")
    if any(h != 0 or a != 0 for h, a in after_cancel):
        FAILS.append(f"H2/{kind}: handles/armed not zero after cancel: "
                     f"{after_cancel}")
    if any(h != N or a != N for h, a in peaks):
        FAILS.append(f"H2/{kind}: arm accounting wrong: {peaks}")
    return row


async def h3_supersede(kind: str) -> Dict[str, Any]:
    """Re-arm the SAME send id 500 times. Each re-arm cancels the previous
    (`previous()` in `_deliver`) -- the double-release shape. Exactly one
    send must survive, handles must stay at 1."""
    cfg = {
        "id": "v2h3",
        "initial": "idle",
        "context": {"n": 0},
        "states": {"idle": {"on": {"PING": {"actions": ["tick"]}}}},
    }
    i = Interpreter(create_machine(cfg, logic=hb_logic(kind)))
    await i.start()
    peak, errs = 0, []
    for _ in range(500):
        try:
            await i._deliver(i, i._prepare_event("PING"), 30.0, "same")
        except Exception as exc:  # noqa: BLE001
            errs.append(type(exc).__name__)
        peak = max(peak, n_handles(i))
    armed_before_fire = n_armed(i)
    await asyncio.sleep(0.4)  # let the surviving one fire
    n = i.context.get("n", 0)
    end_h, end_a = n_handles(i), n_armed(i)
    await i.stop()
    row = {"kind": kind, "rearms": 500, "peak_handles": peak,
           "armed_before_fire": armed_before_fire, "fires": n,
           "end_handles": end_h, "end_armed": end_a,
           "errors": sorted(set(errs))}
    if errs:
        FAILS.append(f"H3/{kind}: re-arm raised {set(errs)}")
    if peak > 1 or armed_before_fire != 1:
        FAILS.append(f"H3/{kind}: peak={peak} armed={armed_before_fire} (want 1)")
    if n != 1:
        FAILS.append(f"H3/{kind}: {n} fires from 500 superseding re-arms (want 1)")
    if end_h != 0 or end_a != 0:
        FAILS.append(f"H3/{kind}: not released after fire: h={end_h} a={end_a}")
    return row


async def h4_cancel_after_fire(kind: str) -> Dict[str, Any]:
    """Explicit double-release: cancel a send that has ALREADY fired."""
    cfg = {
        "id": "v2h4",
        "initial": "idle",
        "context": {"n": 0},
        "states": {"idle": {"on": {"PING": {"actions": ["tick"]}}}},
    }
    i = Interpreter(create_machine(cfg, logic=hb_logic(kind)))
    await i.start()
    cancel = None
    await i._deliver(i, i._prepare_event("PING"), 20.0, "one")
    cancel = i._scheduled_sends.get("one")
    await asyncio.sleep(0.3)
    fired = i.context.get("n", 0)
    h_after_fire, a_after_fire = n_handles(i), n_armed(i)
    err = None
    try:
        if cancel:
            cancel()          # double release #1
            cancel()          # double release #2
    except Exception as exc:  # noqa: BLE001
        err = type(exc).__name__
    h_end, a_end = n_handles(i), n_armed(i)
    await i.stop()
    row = {"kind": kind, "fired": fired, "handles_after_fire": h_after_fire,
           "armed_after_fire": a_after_fire, "cancel_error": err,
           "handles_after_double_cancel": h_end, "armed_after_double_cancel": a_end}
    if fired != 1:
        FAILS.append(f"H4/{kind}: fired={fired} (want 1)")
    if err:
        FAILS.append(f"H4/{kind}: cancel-after-fire raised {err}")
    if h_after_fire != 0 or h_end != 0 or a_end != 0:
        FAILS.append(f"H4/{kind}: accounting {h_after_fire}/{h_end}/{a_end}")
    return row


async def h5_200_machines(kind: str, run_s: float = 10.0) -> Dict[str, Any]:
    """200 heartbeat machines for 10 s: total handles flat, RSS flat."""
    N = 200
    gc.collect()
    rss0 = rss_mb()
    interps = [
        Interpreter(create_machine(hb_cfg(f"v2h5_{k}", 10), logic=hb_logic(kind)))
        for k in range(N)
    ]
    await asyncio.gather(*(i.start() for i in interps))
    samples: List[int] = []
    rss_samples: List[float] = []
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < run_s:
        samples.append(sum(n_handles(i) for i in interps))
        rss_samples.append(rss_mb())
        await asyncio.sleep(0.25)
    beats = [i.context.get("n", 0) for i in interps]
    trips = sum(getattr(i, "chain_trips", 0) for i in interps)
    end_handles = sum(n_handles(i) for i in interps)
    await asyncio.gather(*(i.stop() for i in interps))
    del interps
    gc.collect()
    rss_end = rss_mb()
    row = {
        "kind": kind, "machines": N, "run_s": run_s, "period_ms": 10,
        "handles_first": samples[0] if samples else None,
        "handles_max": max(samples or [0]), "handles_min": min(samples or [0]),
        "handles_end": end_handles,
        "rss_mb_start": round(rss0, 1),
        "rss_mb_max": round(max(rss_samples or [0]), 1),
        "rss_mb_after_stop": round(rss_end, 1),
        "beats_min": min(beats), "beats_max": max(beats),
        "chain_trips": trips, "samples": len(samples),
    }
    if max(samples or [0]) > N:
        FAILS.append(f"H5/{kind}: handles peaked at {max(samples)} for {N} "
                     f"machines (>1 each -- #218 leak)")
    if min(beats) < 10:
        FAILS.append(f"H5/{kind}: a heartbeat died (beats_min={min(beats)})")
    if trips:
        FAILS.append(f"H5/{kind}: {trips} chain trips on periodic work")
    growth = max(rss_samples or [0]) - rss0
    if growth > 150:
        FAILS.append(f"H5/{kind}: RSS grew {growth:.0f} MB over {run_s}s")
    return row


async def main() -> int:
    OUT["H1"] = [await h1_async(k) for k in ("def", "async def")]
    OUT["H1"].append(h1_sync("def"))
    OUT["H2"] = [await h2_cancel_storm(k) for k in ("def", "async def")]
    OUT["H3"] = [await h3_supersede(k) for k in ("def", "async def")]
    OUT["H4"] = [await h4_cancel_after_fire(k) for k in ("def", "async def")]
    OUT["H5"] = [await h5_200_machines(k) for k in ("def", "async def")]
    OUT["failures"] = FAILS
    OUT["verdict"] = "DEFECT" if FAILS else "CLEAN"
    emit("v2_timer_handles_and_cancel_storm", OUT)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
