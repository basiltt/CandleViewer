# -*- coding: utf-8 -*-
"""X13 -- isolate the RSS growth X12 reported (708 MB over 102 s, 200
machines, both kinds).

STANDALONE. Neutral cwd. Four arms, each the SAME duration, so the delta
is attributable:

  A  200 idle machines, NO heartbeat, no external traffic   (baseline)
  B  200 `raise(delay=)` heartbeat machines, no external, no chaos
  C  200 `after:` heartbeat machines (the parity control)
  D  200 heartbeat machines + external producer + chaos restore

If B >> A and B ~= C, the growth is inherent to running timers at all; if
B >> C, it is specific to the #213 `raise(delay=)` path. RSS is sampled
every 10 s so a LEAK (monotone) is distinguishable from a plateau.
"""
from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes as wt
import gc
import json
import os
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine

KIND = os.environ.get("XS_SVC", "async")
NM = int(os.environ.get("XS_NM", "200"))
SECS = float(os.environ.get("XS_SECS", "24"))


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


ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
    wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]


def rss_mb():
    c = PMC()
    c.cb = ctypes.sizeof(c)
    ctypes.windll.psapi.GetProcessMemoryInfo(
        ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return c.WorkingSetSize / 1048576.0


IDLE = {"id": "s", "initial": "a", "context": {"beats": 0},
        "states": {"a": {"on": {"EXT": {"actions": "beat"}}}}}

RAISE_HB = {
    "id": "s", "initial": "a", "context": {"beats": 0},
    "states": {
        "a": {"entry": [{"type": "raise",
                         "params": {"event": "HB", "delay": 10, "id": "hb"}},
                        "beat"],
              "on": {"HB": "b", "EXT": {"actions": "beat"}}},
        "b": {"entry": [{"type": "raise",
                         "params": {"event": "HB", "delay": 10, "id": "hb"}},
                        "beat"],
              "on": {"HB": "a", "EXT": {"actions": "beat"}}},
    },
}

AFTER_HB = {
    "id": "s", "initial": "a", "context": {"beats": 0},
    "states": {
        "a": {"entry": ["beat"], "after": {"10": "b"},
              "on": {"EXT": {"actions": "beat"}}},
        "b": {"entry": ["beat"], "after": {"10": "a"},
              "on": {"EXT": {"actions": "beat"}}},
    },
}


def build(spec):
    def beat(i, c, e, a):  # noqa: ANN001
        c["beats"] += 1

    async def sa(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return 1

    def sd(i, c, e):  # noqa: ANN001
        return 1

    return create_machine(
        json.loads(json.dumps(spec)),
        logic=MachineLogic(actions={"beat": beat},
                           services={"s": sa if KIND == "async" else sd}),
    )


async def arm(label, spec, external=False, chaos=False):
    gc.collect()
    interps = [Interpreter(build(spec)) for _ in range(NM)]
    await asyncio.gather(*(i.start() for i in interps))
    await asyncio.sleep(0.5)
    gc.collect()
    r0 = rss_mb()
    t0 = time.monotonic()
    samples = []
    nxt_chaos = t0 + 2.0
    k = 0
    while time.monotonic() - t0 < SECS:
        await asyncio.sleep(0.25)
        if external:
            for _ in range(20):
                k = (k + 7) % NM
                if interps[k].status == "running":
                    await interps[k].send("EXT")
        if chaos and time.monotonic() >= nxt_chaos:
            nxt_chaos = time.monotonic() + 2.0
            j = (k + 3) % NM
            try:
                blob = interps[j].get_snapshot()
                await interps[j].stop()
                n = Interpreter.from_snapshot(blob, build(spec))
                await n.start()
                interps[j] = n
            except Exception:  # noqa: BLE001
                pass
        el = time.monotonic() - t0
        if len(samples) < int(el / 6):
            samples.append((round(el), round(rss_mb(), 1)))
    gc.collect()
    r1 = rss_mb()
    beats = sum(i.context["beats"] for i in interps)
    for i in interps:
        if i.status == "running":
            await i.stop()
    await asyncio.sleep(0.2)
    del interps
    gc.collect()
    r2 = rss_mb()
    print(f"   {label:34s} rss {r0:7.1f} -> {r1:7.1f} MB "
          f"(+{r1 - r0:7.1f}) after stop+gc {r2:7.1f} MB  beats={beats}")
    print(f"        trace {samples}")
    return r1 - r0


async def main():
    print(f"X13 kind={KIND} NM={NM} SECS={SECS}  (RSS attribution)")
    a = await arm("A idle, no timers            ", IDLE)
    b = await arm("B raise(delay=) heartbeat    ", RAISE_HB)
    c = await arm("C after: heartbeat (control) ", AFTER_HB)
    d = await arm("D heartbeat + ext + chaos    ", RAISE_HB,
                  external=True, chaos=True)
    print(f"\n   growth MB over {SECS}s: idle={a:.1f} raise={b:.1f} "
          f"after={c:.1f} full={d:.1f}")
    print("   -> a heartbeat arm that grows while an idle arm does not is "
          "the signal; raise vs after says whether #213 is implicated.")


asyncio.run(main())
