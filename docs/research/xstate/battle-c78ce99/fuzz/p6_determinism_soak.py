"""P6 -- determinism across the new v3 surfaces, and the soak.

A  50x traces of a delayed-self-send chart on both engines and both
   service kinds, driven on a SimulatedClock so the trace is a pure
   function of the chart: state ids, context, scheduled_sends records and
   the restored run must all collapse to ONE distinct value.
B  PYTHONHASHSEED sweep over the same trace.
C  soak: N machines both kinds with `raise(delay=)` heartbeats at 10-50 ms
   + an external priority producer + chaos v3 snapshot/restore at
   quiescence every 2 s. CPU bounded, 0 dropped external sends,
   heartbeats never die, scheduled_sends restored correctly.

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import json
import logging
import os
import random
import subprocess
import sys
import time
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    RunawayChainError,
    SimulatedClock,
    SyncInterpreter,
    create_machine,
)

RUNS = int(os.environ.get("RUNS", "50"))
SOAK_SECONDS = float(os.environ.get("SOAK_SECONDS", "60"))
SOAK_MACHINES = int(os.environ.get("SOAK_MACHINES", "200"))


def cpu_now():
    t = os.times()
    return t.user + t.system


TRACE_CFG = {
    "id": "tr",
    "initial": "up",
    "context": {"n": 0, "log": []},
    "states": {
        "up": {"entry": [{"type": "raise",
                          "params": {"event": "B", "delay": 7, "id": "u"}},
                         "beat"],
               "on": {"B": "down"}},
        "down": {"entry": [{"type": "raise",
                            "params": {"event": "B", "delay": 11, "id": "d"}},
                           "beat"],
                 "on": {"B": "up"}},
    },
}


def beat(i, c, e, a=None):
    c["n"] = c.get("n", 0) + 1
    c.setdefault("log", []).append([e.type, round(i.clock.now(), 6)])


async def beat_async(i, c, e, a=None):
    beat(i, c, e, a)


def lg(kind):
    return MachineLogic(actions={"beat": beat if kind == "def"
                                 else beat_async})


async def adv(clk, ms):
    r = clk.increment(ms)
    if r is not None and hasattr(r, "__await__"):
        await r
    for _ in range(4):
        await asyncio.sleep(0)


async def trace_async(kind):
    m = create_machine(json.loads(json.dumps(TRACE_CFG)), logic=lg(kind))
    it = Interpreter(m, clock=SimulatedClock())
    await it.start()
    await asyncio.sleep(0)
    await adv(it.clock, 55)
    snap = json.loads(it.get_snapshot())
    mid = (sorted(it.current_state_ids), it.context["n"],
           tuple(map(tuple, it.context["log"])),
           tuple(sorted((r["type"], round(r["remaining_ms"], 6))
                        for r in snap.get("scheduled_sends") or [])))
    await it.stop()
    # restore and continue -- the restored half must be deterministic too
    it2 = Interpreter.from_snapshot(json.dumps(snap), m,
                                    clock=SimulatedClock())
    await it2.start()
    await asyncio.sleep(0)
    await adv(it2.clock, 55)
    post = (sorted(it2.current_state_ids), it2.context["n"],
            tuple(map(tuple, it2.context["log"])))
    await it2.stop()
    return (mid, post)


def trace_sync(kind):
    m = create_machine(json.loads(json.dumps(TRACE_CFG)), logic=lg(kind))
    clk = SimulatedClock()
    try:
        it = SyncInterpreter(m, clock=clk)
        it.start()
        clk.increment(55)
        clk.pump()
        snap = json.loads(it.get_snapshot())
        out = (sorted(it.current_state_ids), it.context["n"],
               tuple(map(tuple, it.context["log"])),
               tuple(sorted((r["type"], round(r["remaining_ms"], 6))
                            for r in snap.get("scheduled_sends") or [])))
        it.stop()
        return out
    except Exception as exc:  # noqa: BLE001
        return (type(exc).__name__,)


async def part_a(defects):
    print(f"A -- determinism, {RUNS} identical runs on a SimulatedClock")
    for kind in ("def", "async def"):
        seen = {}
        for _ in range(RUNS):
            t = await trace_async(kind)
            seen[repr(t)] = seen.get(repr(t), 0) + 1
        print(f"  async engine / {kind:9s} distinct traces = {len(seen)}")
        if len(seen) != 1:
            for k, v in list(seen.items())[:3]:
                print(f"     x{v}  {k[:200]}")
            defects.append(
                f"A/{kind}: {len(seen)} distinct traces over {RUNS} identical "
                f"runs on a SimulatedClock (incl. scheduled_sends + restore)"
            )
        seen_s = {}
        for _ in range(RUNS):
            key = repr(trace_sync(kind))
            seen_s[key] = seen_s.get(key, 0) + 1
        print(f"  sync  engine / {kind:9s} distinct traces = {len(seen_s)}"
              f"  {list(seen_s)[0][:120]}")
        if len(seen_s) != 1:
            defects.append(
                f"A/sync/{kind}: {len(seen_s)} distinct traces over {RUNS} runs"
            )
    print()


def part_b(defects):
    print("B -- PYTHONHASHSEED sweep")
    prog = (
        "import asyncio,json,logging,warnings;warnings.simplefilter('ignore');"
        "logging.disable(logging.CRITICAL);"
        "import sys;sys.path.insert(0,r'%s');"
        "from p6_determinism_soak import trace_async;"
        "print(repr(asyncio.run(trace_async('def'))))"
        % os.path.dirname(os.path.abspath(__file__))
    )
    outs = set()
    for seed in ("0", "1", "42", "12345", "random"):
        env = dict(os.environ, PYTHONHASHSEED=seed,
                   PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        r = subprocess.run([sys.executable, "-c", prog], env=env,
                           capture_output=True, text=True, timeout=60)
        outs.add(r.stdout.strip() or f"ERR:{r.stderr.strip()[-200:]}")
    print(f"   distinct results over 5 hash seeds = {len(outs)}")
    if len(outs) != 1:
        for o in list(outs)[:3]:
            print("     ", o[:200])
        defects.append(
            f"B: {len(outs)} distinct results across PYTHONHASHSEED values"
        )
    print()


# --------------------------------------------------------------------- soak
SOAK = {
    "id": "sk",
    "initial": "up",
    "context": {"beats": 0, "ext": 0},
    "states": {
        "up": {"entry": ["arm", "tick"], "on": {"B": "down",
                                                "EXT": {"actions": ["ext"]}}},
        "down": {"entry": ["arm", "tick"], "on": {"B": "up",
                                                  "EXT": {"actions": ["ext"]}}},
    },
}


async def part_c(defects):
    print(f"C -- soak, {SOAK_MACHINES} machines, {SOAK_SECONDS:.0f}s, "
          f"heartbeats 10-50 ms + external producer + chaos v3 snapshots")
    rnd = random.Random(20260922)

    def tick(i, c, e, a=None):
        c["beats"] = c.get("beats", 0) + 1

    async def tick_a(i, c, e, a=None):
        c["beats"] = c.get("beats", 0) + 1

    def ext(i, c, e, a=None):
        c["ext"] = c.get("ext", 0) + 1

    async def ext_a(i, c, e, a=None):
        c["ext"] = c.get("ext", 0) + 1

    its = []
    periods = []
    for k in range(SOAK_MACHINES):
        kind = "def" if k % 2 == 0 else "async def"
        p = rnd.choice([10, 20, 35, 50])
        periods.append(p)
        cfg = json.loads(json.dumps(SOAK))
        arm = {"type": "raise", "params": {"event": "B", "delay": p,
                                           "id": "hb"}}
        for st in cfg["states"].values():
            st["entry"] = [arm, "tick"]
        m = create_machine(cfg, logic=MachineLogic(actions={
            "tick": tick if kind == "def" else tick_a,
            "ext": ext if kind == "def" else ext_a,
        }))
        its.append(Interpreter(m))

    c0, t0 = cpu_now(), time.monotonic()
    await asyncio.gather(*(i.start() for i in its))
    sent = 0
    chaos = {"ok": 0, "refused": 0, "restored": 0, "sched_missing": 0}
    last_chaos = time.monotonic()
    while time.monotonic() - t0 < SOAK_SECONDS:
        for i in its:
            await i.send("EXT")
            sent += 1
        if time.monotonic() - last_chaos > 2.0:
            last_chaos = time.monotonic()
            for i in its[:20]:
                try:
                    blob = i.get_snapshot()
                    chaos["ok"] += 1
                    s = json.loads(blob)
                    # 📏 The heartbeat is accounted for if it is either
                    #    still ARMED (`scheduled_sends`) or already FIRED
                    #    and waiting in the inbox (`pending_events`). A
                    #    snapshot taken in the instant between the two is
                    #    not a lost timer -- only "neither" would be.
                    armed = s.get("scheduled_sends") or []
                    queued = [
                        r for r in (s.get("pending_events") or [])
                        if r.get("type") == "B"
                    ]
                    if not armed and not queued:
                        chaos["sched_missing"] += 1
                    r = Interpreter.from_snapshot(blob, i.machine)
                    chaos["restored"] += 1
                    del r
                except Exception:  # noqa: BLE001
                    chaos["refused"] += 1
        await asyncio.sleep(0.005)
    elapsed = time.monotonic() - t0
    cpu = cpu_now() - c0
    beats = [i.context.get("beats", 0) for i in its]
    got = sum(i.context.get("ext", 0) for i in its)
    errs = sum(1 for i in its if isinstance(i.last_error, RunawayChainError))
    await asyncio.sleep(0.3)
    beats2 = [i.context.get("beats", 0) for i in its]
    alive = sum(1 for a, b in zip(beats, beats2) if b > a)
    await asyncio.gather(*(i.stop() for i in its))

    print(f"   elapsed={elapsed:.1f}s cpu={cpu:.1f}s "
          f"({100.0 * cpu / elapsed:.0f}% of one core)")
    print(f"   ext_sent={sent} ext_applied={got} lost={sent - got}")
    print(f"   beats min={min(beats)} max={max(beats)} "
          f"still_beating={alive}/{SOAK_MACHINES} runaway={errs}")
    print(f"   chaos={chaos}")
    if sent != got:
        defects.append(
            f"C: {sent - got} of {sent} external priority sends were lost "
            f"during the soak"
        )
    if alive != SOAK_MACHINES:
        defects.append(
            f"C: only {alive}/{SOAK_MACHINES} heartbeats still beating at "
            f"the end of the soak"
        )
    if errs:
        defects.append(
            f"C: {errs} heartbeat machines tripped RunawayChainError -- "
            f"#212 says a raise(delay=) heartbeat is a periodic process"
        )
    if chaos["sched_missing"]:
        defects.append(
            f"C: {chaos['sched_missing']} chaos snapshots of a live "
            f"heartbeat accounted for the beat NEITHER as an armed "
            f"scheduled_send NOR as a fired event in the inbox -- the "
            f"heartbeat would restore permanently parked (#213)"
        )
    print()


async def main():
    print("P6 -- determinism + soak on the v3 / #212 surfaces\n")
    defects = []
    await part_a(defects)
    part_b(defects)
    await part_c(defects)
    print(f"DEFECTS = {len(defects)}")
    for d in defects:
        print("   -", d)
    return 1 if defects else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
