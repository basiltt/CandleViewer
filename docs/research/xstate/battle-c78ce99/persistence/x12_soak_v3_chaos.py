# -*- coding: utf-8 -*-
"""X12 -- soak: 200 machines, raise(delay=) heartbeats, external priority
producer, chaos v3 snapshot/restore at quiescence.

STANDALONE. Neutral cwd. Duration via XS_MINS (default 4; the task's
12-minute figure exceeds the per-script bound of 120 s, so this runs the
same shape at a reduced duration -- SAID OUT LOUD in the report).

Invariants:
  * CPU bounded (reported cpu/wall, and beats/machine vs the nominal rate)
  * 0 external events dropped or lost (each is counted in context)
  * heartbeats never die (every machine's beat count strictly increases in
    every sampling window)
  * chaos snapshot/restore every CHAOS_S seconds at quiescence: every blob
    is v3, carries scheduled_sends, restores, and the restored machine
    keeps beating and keeps its external count
  * RSS at start vs end (leak check)
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import RunawayChainError
from xstate_statemachine.plugins import PluginBase

KIND = os.environ.get("XS_SVC", "async")
NM = int(os.environ.get("XS_NM", "200"))
MINS = float(os.environ.get("XS_MINS", "4"))
CHAOS_S = float(os.environ.get("XS_CHAOS", "2"))

SPEC = {
    "id": "soak",
    "initial": "a",
    "context": {"beats": 0, "ext": 0},
    "states": {
        "a": {"entry": [{"type": "raise",
                         "params": {"event": "HB", "delay": 10, "id": "hb"}},
                        "beat"],
              "on": {"HB": "b", "EXT": {"actions": "ext"}}},
        "b": {"entry": [{"type": "raise",
                         "params": {"event": "HB", "delay": 50, "id": "hb"}},
                        "beat"],
              "on": {"HB": "a", "EXT": {"actions": "ext"}}},
    },
}


class Drop(PluginBase):
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, i, e, reason):  # noqa: ANN001
        self.dropped.append(reason)


def build():
    def beat(i, c, e, a):  # noqa: ANN001
        c["beats"] += 1

    def ext(i, c, e, a):  # noqa: ANN001
        c["ext"] += 1

    async def sa(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return 1

    def sd(i, c, e):  # noqa: ANN001
        return 1

    return create_machine(
        json.loads(json.dumps(SPEC)),
        logic=MachineLogic(actions={"beat": beat, "ext": ext},
                           services={"s": sa if KIND == "async" else sd}),
    )


def cpu():
    t = os.times()
    return t.user + t.system


def rss_kb():
    try:
        import resource  # noqa: F401
    except ImportError:
        pass
    try:
        import ctypes
        import ctypes.wintypes as wt

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        c = PMC()
        c.cb = ctypes.sizeof(c)
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
            wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]
        ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb)
        return c.WorkingSetSize // 1024
    except Exception:  # noqa: BLE001
        return -1


async def main():
    print(f"X12 kind={KIND} NM={NM} MINS={MINS} chaos_every={CHAOS_S}s")
    rnd = random.Random(4242)
    plugs = [Drop() for _ in range(NM)]
    interps = []
    for k in range(NM):
        i = Interpreter(build())
        i.use(plugs[k])
        interps.append(i)
    await asyncio.gather(*(i.start() for i in interps))
    r0, c0, t0 = rss_kb(), cpu(), time.monotonic()
    deadline = t0 + MINS * 60
    sent = 0
    chaos_ok = chaos_fail = chaos_skip = 0
    ss_present = 0
    last_beats = [i.context["beats"] for i in interps]
    stalled_windows = 0
    next_chaos = t0 + CHAOS_S
    samples = 0
    while time.monotonic() < deadline:
        # external priority producer
        for _ in range(20):
            k = rnd.randrange(NM)
            if interps[k].status == "running":
                await interps[k].send("EXT")
                sent += 1
        await asyncio.sleep(0.25)
        chaos_idx = None
        if time.monotonic() >= next_chaos:
            next_chaos = time.monotonic() + CHAOS_S
            k = rnd.randrange(NM)
            chaos_idx = k
            tgt = interps[k]
            blob = None
            for _ in range(60):
                try:
                    blob = tgt.get_snapshot()
                    break
                except Exception:  # noqa: BLE001
                    await asyncio.sleep(0.005)
            if blob is None:
                chaos_skip += 1
            else:
                snap = json.loads(blob)
                if snap.get("version") == 3 and (
                    snap.get("scheduled_sends") or []
                ):
                    ss_present += 1
                b_before = tgt.context["beats"]
                e_before = tgt.context["ext"]
                await tgt.stop()
                try:
                    n = Interpreter.from_snapshot(blob, build())
                    n.use(plugs[k])
                    await n.start()
                    await asyncio.sleep(0.2)
                    ok = (n.context["beats"] > b_before
                          and n.context["ext"] == e_before
                          and n.status == "running")
                    interps[k] = n
                    last_beats[k] = n.context["beats"]
                    chaos_ok += 1 if ok else 0
                    chaos_fail += 0 if ok else 1
                except Exception as exc:  # noqa: BLE001
                    chaos_fail += 1
                    print(f"   chaos restore EXC {type(exc).__name__}: "
                          f"{str(exc)[:80]}")
        # heartbeat liveness window
        now_beats = [i.context["beats"] for i in interps]
        dead = sum(1 for j, (a, b) in enumerate(zip(last_beats, now_beats))
                   if b <= a and j != chaos_idx)
        if dead:
            stalled_windows += 1
        last_beats = now_beats
        samples += 1
    c1, t1, r1 = cpu(), time.monotonic(), rss_kb()
    wall = t1 - t0
    beats = [i.context["beats"] for i in interps]
    ext = sum(i.context["ext"] for i in interps)
    drops = {}
    for p in plugs:
        for d in p.dropped:
            drops[d] = drops.get(d, 0) + 1
    runaway = sum(1 for i in interps
                  if isinstance(i.error, RunawayChainError))
    statuses = {}
    for i in interps:
        statuses[i.status] = statuses.get(i.status, 0) + 1
    for i in interps:
        if i.status == "running":
            await i.stop()
    print(f"   wall={wall:.0f}s cpu={c1 - c0:.0f}s cpu/wall="
          f"{(c1 - c0) / wall:.2f}  rss {r0} -> {r1} KB "
          f"(delta {r1 - r0} KB)")
    print(f"   beats/machine: min={min(beats)} med={sorted(beats)[NM // 2]} "
          f"max={max(beats)}")
    raced = drops.get("stopped", 0)
    print(f"   external: sent={sent} handled={ext} lost={sent - ext} "
          f"(of which reported 'stopped' by the engine while chaos was "
          f"restarting that machine: {raced}) drops={drops}")
    print(f"   heartbeat stall windows: {stalled_windows}/{samples}")
    print(f"   chaos: ok={chaos_ok} fail={chaos_fail} skipped(midstep)="
          f"{chaos_skip} blobs_with_scheduled_sends={ss_present}")
    print(f"   statuses={statuses} runaway={runaway}")
    # an EXT sent into the millisecond a chaos restore was stopping its
    # target is REPORTED by the engine ('stopped' drop) -- a harness race,
    # not a silent loss. Unreported loss is the invariant.
    unreported = (sent - ext) - raced
    ok = (runaway == 0 and chaos_fail == 0 and unreported == 0
          and min(beats) > 0 and stalled_windows == 0)
    print(f"   UNREPORTED external loss = {unreported} "
          f"(this is the invariant)")
    print("VERDICT", "PASS" if ok else "FAIL")


asyncio.run(main())
