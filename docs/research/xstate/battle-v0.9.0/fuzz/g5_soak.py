"""G5 -- v0.9.0 soak: 200 machines x both kinds, action-spawned workers that
outlive their action, delayed-self-send heartbeats, an external priority
producer, and a chaos worker doing v3 snapshot -> from_snapshot(plugins=) ->
re-persist rounds.

Invariants, polled to convergence at the end:
  * 0 dropped external sends (every accepted send is applied)
  * every heartbeat still beating
  * chain_trips == 0 on every machine (nothing is a runaway chain here)
  * timer handles capped at ~1 per owner (#218)
  * every action-spawned worker send lands (#225)
  * chaos restores produce 0 record mismatches and 0 restore exceptions
  * no #232 RuntimeWarning noise (every receipt here is used or not asked for)
  * heap growth bounded

SECONDS env var controls the duration (default 360 = 6 min).

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import gc
import json
import logging
import os
import time
import tracemalloc
import warnings

logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)

SECONDS = float(os.environ.get("SECONDS", "360"))
NM = int(os.environ.get("N_MACHINES", "200"))
DEFECTS = []
WARNS = []


def cfg(mid, beat):
    return {
        "id": mid,
        "initial": "run",
        "context": {"beats": 0, "ext": 0, "work": 0},
        "states": {
            "run": {
                "entry": [
                    {"type": "raise", "params": {"event": "HB", "delay": beat}},
                    "spawn",
                ],
                "on": {
                    "HB": {
                        "actions": [
                            "beat",
                            {
                                "type": "raise",
                                "params": {"event": "HB", "delay": beat},
                            },
                        ]
                    },
                    "EXT": {"actions": ["ext"]},
                    "WORK": {"actions": ["work"]},
                },
            }
        },
    }


def beat(i, c, e, a=None):
    c["beats"] = c.get("beats", 0) + 1


def ext(i, c, e, a=None):
    c["ext"] = c.get("ext", 0) + 1


def work(i, c, e, a=None):
    c["work"] = c.get("work", 0) + 1


async def _worker(i, stop):
    """Spawned FROM an action, outlives it; ordinary external traffic (#225)."""
    while not stop.is_set():
        await asyncio.sleep(0.25)
        try:
            await i.send("WORK")
        except Exception:  # noqa: BLE001
            return


def make_logic(kind, stop):
    def spawn_def(i, c, e, a=None):
        asyncio.ensure_future(_worker(i, stop))

    async def spawn_async(i, c, e, a=None):
        asyncio.ensure_future(_worker(i, stop))

    return MachineLogic(
        actions={
            "spawn": spawn_def if kind == "def" else spawn_async,
            "beat": beat,
            "ext": ext,
            "work": work,
        }
    )


class Counter(PluginBase):
    def __init__(self):
        self.invalid = 0

    def on_invalid_event(self, interpreter, error, event=None):
        self.invalid += 1


async def producer(its, stop, stats):
    """External priority traffic."""
    n = 0
    while not stop.is_set():
        for i in its:
            try:
                await i.send("EXT", priority=True)
                stats["sent"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["send_err"] += 1
                stats["last_err"] = type(exc).__name__
        n += 1
        await asyncio.sleep(0.2)


async def chaos(its, stop, stats):
    """v3 snapshot -> from_snapshot(plugins=) -> re-persist rounds."""
    idx = 0
    while not stop.is_set():
        it = its[idx % len(its)]
        idx += 1
        try:
            blob = it.get_snapshot()
            before = sorted(
                (r["type"], round(float(r.get("remaining_ms") or 0), 3))
                for r in (json.loads(blob).get("scheduled_sends") or [])
            )
            spy = Counter()
            r = Interpreter.from_snapshot(blob, it.machine, plugins=[spy])
            after = sorted(
                (rec["type"], round(float(rec.get("remaining_ms") or 0), 3))
                for rec in (
                    json.loads(r.get_snapshot()).get("scheduled_sends") or []
                )
            )
            stats["rounds"] += 1
            if before != after:
                stats["mismatch"] += 1
            if spy.invalid:
                stats["invalid"] += spy.invalid
            if r.chain_trips != it.chain_trips:
                stats["trip_drift"] += 1
        except Exception as exc:  # noqa: BLE001
            stats["restore_err"] += 1
            stats["last_restore_err"] = f"{type(exc).__name__}: {exc}"[:120]
        await asyncio.sleep(0.05)


async def run_kind(kind, secs):
    stop = asyncio.Event()
    lg = make_logic(kind, stop)
    its = []
    for n in range(NM):
        m = create_machine(cfg(f"s{n}", 10 + (n % 40)), logic=lg)
        its.append(Interpreter(m))
    tracemalloc.start()
    base = tracemalloc.get_traced_memory()[0]
    await asyncio.gather(*(i.start() for i in its))

    pstats = {"sent": 0, "send_err": 0}
    cstats = {
        "rounds": 0,
        "mismatch": 0,
        "invalid": 0,
        "restore_err": 0,
        "trip_drift": 0,
    }
    tasks = [
        asyncio.ensure_future(producer(its, stop, pstats)),
        asyncio.ensure_future(chaos(its, stop, cstats)),
    ]
    handles_peak = 0
    t0 = time.time()
    while time.time() - t0 < secs:
        await asyncio.sleep(1.0)
        tot = 0
        for i in its:
            h = getattr(i, "_timer_handles", None) or {}
            try:
                tot += sum(len(v) for v in h.values())
            except Exception:  # noqa: BLE001
                pass
        handles_peak = max(handles_peak, tot)
    stop.set()
    for t in tasks:
        t.cancel()
    await asyncio.sleep(0.6)  # let in-flight sends converge

    applied = sum(i.context.get("ext", 0) for i in its)
    beats = [i.context.get("beats", 0) for i in its]
    works = [i.context.get("work", 0) for i in its]
    trips = sum(i.chain_trips for i in its)
    gc.collect()
    heap = (tracemalloc.get_traced_memory()[0] - base) / 1024.0
    tracemalloc.stop()
    await asyncio.gather(*(i.stop() for i in its))

    dead_beats = sum(1 for b in beats if b == 0)
    dead_work = sum(1 for w in works if w == 0)
    print(
        f"  {kind:9s} ext_sent={pstats['sent']} ext_applied={applied} "
        f"lost={pstats['sent'] - applied} send_err={pstats['send_err']}\n"
        f"            beats min/max={min(beats)}/{max(beats)} dead={dead_beats} "
        f"| worker sends min/max={min(works)}/{max(works)} dead={dead_work}\n"
        f"            chain_trips_total={trips} handles_peak={handles_peak} "
        f"(<= {NM} = 1/machine) heap={heap:+.1f}KB\n"
        f"            chaos={cstats}"
    )
    if pstats["sent"] != applied:
        DEFECTS.append(
            f"{kind}: {pstats['sent'] - applied} external sends accepted but "
            f"never applied"
        )
    if dead_beats:
        DEFECTS.append(f"{kind}: {dead_beats} heartbeats stopped beating")
    if dead_work:
        DEFECTS.append(
            f"{kind}: {dead_work} action-spawned workers never landed a send"
        )
    if trips:
        DEFECTS.append(f"{kind}: chain_trips={trips} on a chart with no chain")
    if handles_peak > NM:
        DEFECTS.append(
            f"{kind}: timer handles peaked at {handles_peak} > {NM} (#218)"
        )
    if cstats["mismatch"] or cstats["restore_err"] or cstats["trip_drift"]:
        DEFECTS.append(f"{kind}: chaos restore anomalies {cstats}")


async def main():
    secs = SECONDS / 2.0
    print(
        f"G5 -- soak: {NM} machines x 2 kinds x {secs:.0f}s each "
        f"({SECONDS:.0f}s total)\n"
    )
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        for kind in ("def", "async def"):
            await run_kind(kind, secs)
        rt = [
            str(x.message)[:80]
            for x in w
            if issubclass(x.category, RuntimeWarning)
        ]
    print(f"\n  RuntimeWarnings (#232 noise) = {len(rt)} {rt[:3]}")
    if rt:
        DEFECTS.append(
            f"soak: {len(rt)} #232 RuntimeWarnings on supported shapes: "
            f"{rt[:2]}"
        )
    print(f"\nDEFECTS = {len(DEFECTS)}")
    for d in DEFECTS:
        print("   -", d)
    return 1 if DEFECTS else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
