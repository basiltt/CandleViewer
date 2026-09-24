"""v6 (@de2da4e) -- STANDALONE. Soak: many machines, mixed 10-50 ms
heartbeats, external priority producer, chaos v3 snapshot/restore/
re-persist. Invariants: timer HANDLES flat (#218), RSS flat, 0 external
dropped, no heartbeat dies, chain_trips stable at 0 (#222), and every
chaos round carries the beat across the snapshot (#213/#221).

REDUCTION (stated, per the whole-task bound): the brief asks 12 min x
200 machines; this runs SOAK_S / N_SOAK below. The soak invariants are
PER MACHINE and rate-independent, and v2-H5 separately ran 200 machines
for 10 s with handle and RSS sampling. Recorded in the report's
"not covered".

Chaos adds the #221 shape the round-11 fix is about: every chaos round
does snapshot -> restore -> RE-PERSIST (no start) -> restore -> start,
so the parked-record path is exercised thousands of times, not once.

Run: python v6_soak.py   (exit 1 == defect)
"""

from __future__ import annotations

import asyncio
import copy
import ctypes
import json
import os
import sys
import time
from ctypes import wintypes
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)

SOAK_S = float(os.environ.get("V6_SOAK_S", "150"))
N_SOAK = int(os.environ.get("V6_N", "200"))
CHAOS_EVERY_S = 1.5
HERE = os.path.dirname(os.path.abspath(__file__))
#: mixed heartbeat periods, per the brief's "10-50 ms heartbeats"
PERIODS = [10, 20, 25, 40, 50]


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {
        "probe": name,
        "py": ".".join(map(str, sys.version_info[:3])),
        **data,
    }
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(HERE, name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


def rss_mb() -> float:
    """RSS with no psutil (standalone rule)."""
    if sys.platform != "win32":
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0

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
    k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD
    ]
    psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc),
                               pmc.cb)
    return pmc.WorkingSetSize / 1e6


def cpu_s() -> float:
    t = os.times()
    return t.user + t.system


def n_handles(i: Any) -> int:
    return sum(len(v) for v in getattr(i, "_timer_handles", {}).values())


def soak_cfg(period_ms: int) -> Dict[str, Any]:
    # 💓 `reenter: True` -- without it the self-target is INTERNAL, entry
    #    never re-runs and the beat fires once (CV-C51).
    return {
        "id": "v6s", "initial": "beat", "maxIterations": 12,
        "context": {"n": 0, "ext": 0},
        "states": {
            "beat": {
                "entry": [{"type": "raise",
                           "params": {"event": "TICK", "delay": period_ms}}],
                "on": {"TICK": {"target": "beat", "reenter": True,
                                "actions": ["tick"]},
                       "EXT": {"actions": ["ext"]}},
            },
        },
    }


def soak_logic(kind: str) -> MachineLogic:
    def ext(i, ctx, e, ad):  # noqa: ANN001
        ctx["ext"] = ctx.get("ext", 0) + 1

    if kind == "def":

        def tick(i, ctx, e, ad):  # noqa: ANN001
            ctx["n"] = ctx.get("n", 0) + 1

        return MachineLogic(actions={"tick": tick, "ext": ext})

    async def atick(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    return MachineLogic(actions={"tick": atick, "ext": ext})


class SoakSpy(PluginBase):
    def __init__(self) -> None:
        self.dropped: Dict[str, int] = {}
        self.chain_hooks = 0

    def on_event_dropped(self, interpreter, event, reason):  # noqa: ANN001
        if getattr(event, "type", "") == "EXT":
            self.dropped[reason] = self.dropped.get(reason, 0) + 1

    def on_chain_budget_exceeded(self, interpreter, error, event):  # noqa: ANN001
        self.chain_hooks += 1


def blob_of(i: Any) -> str:
    s = i.get_persisted_snapshot()
    return s if isinstance(s, str) else json.dumps(s, default=str)


async def soak() -> Dict[str, Any]:
    kinds = ["def" if k % 2 == 0 else "async def" for k in range(N_SOAK)]
    periods = [PERIODS[k % len(PERIODS)] for k in range(N_SOAK)]
    spies = [SoakSpy() for _ in range(N_SOAK)]
    interps: List[Any] = []
    for k in range(N_SOAK):
        i = Interpreter(create_machine(copy.deepcopy(soak_cfg(periods[k])),
                                       logic=soak_logic(kinds[k])))
        i.use(spies[k])
        interps.append(i)
    await asyncio.gather(*(i.start() for i in interps))

    sent = 0
    chaos_rounds = 0
    chaos_with_record = chaos_inflight = 0
    chaos_failures: List[str] = []
    reemit_mismatches = 0
    handle_samples: List[int] = []
    rss_samples: List[float] = []
    rss0, c0 = rss_mb(), cpu_s()
    t0 = time.perf_counter()
    next_chaos = t0 + CHAOS_EVERY_S
    while time.perf_counter() - t0 < SOAK_S:
        for i in interps:
            await i.send("EXT", priority=True)
            sent += 1
        await asyncio.sleep(0.05)
        handle_samples.append(sum(n_handles(i) for i in interps))
        rss_samples.append(rss_mb())
        if time.perf_counter() < next_chaos:
            continue
        next_chaos = time.perf_counter() + CHAOS_EVERY_S
        chaos_rounds += 1
        idx = chaos_rounds % N_SOAK
        old = interps[idx]
        blob = blob_of(old)
        snapd = json.loads(blob)
        recs = snapd.get("scheduled_sends") or []
        inflight = [r for r in (snapd.get("pending_events") or [])
                    if r.get("type") == "TICK"]
        if recs:
            chaos_with_record += 1
        elif inflight:
            chaos_inflight += 1
        else:
            chaos_failures.append(
                f"round {chaos_rounds}: snapshot carried the heartbeat "
                f"NEITHER armed nor in-flight")
        n_before = old.context.get("n", 0)
        await old.stop()
        # 🔁 #221 shape: restore -> RE-PERSIST (no start) -> restore -> start
        mid = create_machine(copy.deepcopy(soak_cfg(periods[idx])),
                             logic=soak_logic(kinds[idx]))
        parked = Interpreter.from_snapshot(blob, mid)
        blob2 = blob_of(parked)
        recs2 = json.loads(blob2).get("scheduled_sends") or []
        if len(recs2) != len(recs):
            reemit_mismatches += 1
            chaos_failures.append(
                f"round {chaos_rounds}: #221 re-persist changed the parked "
                f"record count {len(recs)} -> {len(recs2)}")
        m = create_machine(copy.deepcopy(soak_cfg(periods[idx])),
                           logic=soak_logic(kinds[idx]))
        new = Interpreter.from_snapshot(blob2, m)
        new.use(spies[idx])
        await new.start()
        await asyncio.sleep(0.2)
        if new.context.get("n", 0) <= n_before:
            chaos_failures.append(
                f"round {chaos_rounds}: heartbeat did not resume after the "
                f"two-hop restore (n {n_before} -> {new.context.get('n')})")
        interps[idx] = new
    wall = time.perf_counter() - t0
    cpu = cpu_s() - c0
    beats = [i.context.get("n", 0) for i in interps]
    exts = sum(i.context.get("ext", 0) for i in interps)
    trips = sum(getattr(i, "chain_trips", 0) for i in interps)
    hooks = sum(s.chain_hooks for s in spies)
    dropped: Dict[str, int] = {}
    for sp in spies:
        for k, v in sp.dropped.items():
            dropped[k] = dropped.get(k, 0) + v
    errs = [str(i.last_error) for i in interps if i.last_error is not None]
    await asyncio.gather(*(i.stop() for i in interps), return_exceptions=True)
    rss1 = rss_mb()
    # beats are per-machine at DIFFERENT periods; normalise for the oracle
    ideal = [SOAK_S * 1000.0 / p for p in periods]
    ratios = [b / i for b, i in zip(beats, ideal)]
    out: Dict[str, Any] = {
        "machines": N_SOAK, "soak_s": SOAK_S, "wall_s": round(wall, 1),
        "periods_ms": sorted(set(periods)),
        "cpu_s": round(cpu, 1), "cpu_over_wall": round(cpu / wall, 2),
        "cores": os.cpu_count(),
        "rss_mb_start": round(rss0, 1),
        "rss_mb_max": round(max(rss_samples or [0]), 1),
        "rss_mb_end": round(rss1, 1),
        "handles_first": handle_samples[0] if handle_samples else None,
        "handles_max": max(handle_samples or [0]),
        "handles_last": handle_samples[-1] if handle_samples else None,
        "handles_per_machine_max": round(
            max(handle_samples or [0]) / N_SOAK, 2),
        "external_sent": sent, "external_handled": exts,
        "external_dropped": dropped,
        "beats_min": min(beats), "beats_max": max(beats),
        "beat_ratio_min": round(min(ratios), 3),
        "chain_trips": trips, "chain_hooks": hooks,
        "chaos_rounds": chaos_rounds,
        "chaos_blobs_with_armed_record": chaos_with_record,
        "chaos_blobs_beat_inflight": chaos_inflight,
        "chaos_221_reemit_mismatches": reemit_mismatches,
        "n_chaos_failures": len(chaos_failures),
        "chaos_failures": chaos_failures[:5],
        "last_errors": errs[:3],
        "reduction": (
            f"{SOAK_S:.0f} s / {N_SOAK} machines instead of the briefed "
            f"12 min / 200 -- the 20-minute whole-task bound. Machine count "
            f"is UNREDUCED; only the duration is. Soak invariants are "
            f"per-machine and rate-independent; v2-H5 sampled handles and "
            f"RSS on 200 machines separately."
        ),
    }
    fails: List[str] = []
    if dropped:
        fails.append(f"external events dropped: {dropped}")
    if min(ratios) < 0.2:
        fails.append(f"a heartbeat stalled (worst machine ran "
                     f"{min(ratios):.1%} of its ideal beats)")
    if chaos_failures:
        fails.append(chaos_failures[0])
    if max(handle_samples or [0]) > N_SOAK * 2:
        fails.append(f"timer handles peaked at {max(handle_samples)} for "
                     f"{N_SOAK} machines (#218 leak)")
    if max(rss_samples or [0]) - rss0 > 400:
        fails.append(f"RSS grew {max(rss_samples) - rss0:.0f} MB")
    if trips or hooks:
        fails.append(f"chain trips on purely periodic work: {trips} "
                     f"(hooks {hooks})")
    out["failures"] = fails
    out["verdict"] = "DEFECT" if fails else "CLEAN"
    return out


async def main() -> int:
    row = await soak()
    emit("v6_soak", row)
    return 1 if row["failures"] else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
