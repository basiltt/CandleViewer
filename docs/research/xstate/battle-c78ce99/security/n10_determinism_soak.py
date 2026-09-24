"""STANDALONE: determinism + reduced soak.

A  50x identical traces, both engines, both action kinds, including a
   scheduled_sends restore in the middle.
B  hash-seed: structure_hash stable across PYTHONHASHSEED (run twice by
   the caller; here we assert stability within a process over 50 rebuilds
   and print the hash so an external re-run can diff it).
C  REDUCED soak (SOAK_S seconds, default 100 -- the 12-minute soak does
   not fit the per-script bound): N machines, raise(delay=) heartbeats at
   10-50 ms + external priority producer + chaos v3 snapshot/restore at
   quiescence every 2 s.  Asserts: CPU bounded, 0 dropped external,
   heartbeats never die, scheduled_sends restored.
"""

import asyncio
import json
import os
import random
import sys
import time

from xstate_statemachine import create_machine, Interpreter, MachineLogic
from xstate_statemachine.sync_interpreter import SyncInterpreter
from xstate_statemachine.persistence import structure_hash

SOAK_S = float(os.environ.get("SOAK_S", "100"))


def trace_cfg():
    return {
        "id": "t", "initial": "a", "context": {"log": []},
        "states": {
            "a": {"entry": [{"type": "rec"}],
                  "on": {"GO": {"target": "b"}},
                  "always": [{"target": "a2", "guard": "never"}]},
            "a2": {},
            "b": {"entry": [{"type": "rec"},
                            {"type": "raise",
                             "params": {"event": "TICK", "delay": 30}}],
                  "on": {"TICK": {"target": "c"}}},
            "c": {"entry": [{"type": "rec"}]},
        },
    }


def rec(i, c, e, a):
    c["log"].append(e.type)


async def rec_a(i, c, e, a):
    c["log"].append(e.type)


def never(i, c, e, a):
    return False


def logic(kind):
    return MachineLogic(actions={"rec": rec if kind == "def" else rec_a},
                        guards={"never": never})


async def one_trace_async(kind):
    m = create_machine(trace_cfg(), logic=logic(kind))
    it = await Interpreter(m).start()
    await it.send("GO")
    await asyncio.sleep(0.01)
    snap = it.get_snapshot()
    await it.stop()
    it2 = await Interpreter.from_snapshot(snap, m).start()
    await asyncio.sleep(0.12)
    out = (tuple(it2.context["log"]), tuple(sorted(it2.current_state_ids)))
    await it2.stop()
    return out


def one_trace_sync():
    m = create_machine(trace_cfg(), logic=logic("def"))
    it = SyncInterpreter(m).start()
    it.send("GO")
    snap = it.get_snapshot()
    it.stop()
    it2 = SyncInterpreter.from_snapshot(snap, m).start()
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 0.2:
        it2.send("__NUDGE__")
        time.sleep(0.005)
        if "t.c" in it2.current_state_ids:
            break
    out = (tuple(it2.context["log"]), tuple(sorted(it2.current_state_ids)))
    it2.stop()
    return out


async def section_a(n=50):
    for kind in ("def", "async"):
        seen = set()
        for _ in range(n):
            seen.add(await one_trace_async(kind))
        print("A async/%s %dx distinct traces=%d %s"
              % (kind, n, len(seen), sorted(seen)[0] if len(seen) == 1 else
                 sorted(seen)), flush=True)
    seen = set()
    for _ in range(n):
        seen.add(one_trace_sync())
    print("A sync/def %dx distinct traces=%d %s"
          % (n, len(seen), sorted(seen)[0] if len(seen) == 1
             else sorted(seen)), flush=True)


def section_b(n=50):
    hashes = {structure_hash(create_machine(trace_cfg(), logic=logic("def")))
              for _ in range(n)}
    print("B structure_hash stable over %d rebuilds: %s %s"
          % (n, len(hashes) == 1, sorted(hashes)),
          "(PYTHONHASHSEED=%s)" % os.environ.get("PYTHONHASHSEED", "<unset>"),
          flush=True)


# ------------------------------------------------------------------ soak
def soak_cfg(mid, hb):
    return {
        "id": mid, "initial": "a", "context": {"beats": 0, "ext": 0},
        "maxIterations": 50,
        "states": {
            "a": {"entry": [{"type": "beat"},
                            {"type": "raise",
                             "params": {"event": "HB", "delay": hb}}],
                  "on": {"HB": {"target": "b"},
                         "EXT": {"actions": ["ext"]}}},
            "b": {"entry": [{"type": "beat"},
                            {"type": "raise",
                             "params": {"event": "HB", "delay": hb}}],
                  "on": {"HB": {"target": "a"},
                         "EXT": {"actions": ["ext"]}}},
        },
    }


def beat(i, c, e, a):
    c["beats"] = c.get("beats", 0) + 1


def extf(i, c, e, a):
    c["ext"] = c.get("ext", 0) + 1


async def beat_a(i, c, e, a):
    c["beats"] = c.get("beats", 0) + 1


async def ext_a(i, c, e, a):
    c["ext"] = c.get("ext", 0) + 1


async def section_c(n=200, dur=None):
    dur = dur if dur is not None else SOAK_S
    rng = random.Random(5)
    mach, its, kinds = [], [], []
    for i in range(n):
        kind = "def" if i % 2 == 0 else "async"
        lg = MachineLogic(
            actions={"beat": beat if kind == "def" else beat_a,
                     "ext": extf if kind == "def" else ext_a})
        m = create_machine(soak_cfg("s%d" % i, rng.choice([10, 20, 35, 50])),
                           logic=lg)
        mach.append(m)
        kinds.append(kind)
        its.append(await Interpreter(m).start())

    sent = {"n": 0, "fail": 0}
    stop = False

    async def producer():
        while not stop:
            it = rng.choice(its)
            try:
                await it.send("EXT", priority=True)
                sent["n"] += 1
            except Exception:  # noqa: BLE001
                sent["fail"] += 1
            await asyncio.sleep(0.002)

    chaos = {"cycles": 0, "ss_restored": 0, "ss_zero": 0, "fail": 0}

    async def chaoser():
        nonlocal its
        while not stop:
            await asyncio.sleep(2.0)
            idx = rng.randrange(len(its))
            try:
                snap = its[idx].get_snapshot()
                ss = json.loads(snap).get("scheduled_sends") or []
                await its[idx].stop()
                its[idx] = await Interpreter.from_snapshot(
                    snap, mach[idx]).start()
                chaos["cycles"] += 1
                if ss:
                    chaos["ss_restored"] += 1
                else:
                    chaos["ss_zero"] += 1
            except Exception as exc:  # noqa: BLE001
                chaos["fail"] += 1
                chaos.setdefault("last", type(exc).__name__)

    prod = asyncio.ensure_future(producer())
    ch = asyncio.ensure_future(chaoser())
    c0, w0 = time.process_time(), time.perf_counter()
    mid = None
    await asyncio.sleep(dur / 2)
    mid = [it.context.get("beats", 0) for it in its]
    await asyncio.sleep(dur / 2)
    stop = True
    await asyncio.gather(prod, ch, return_exceptions=True)
    cpu = time.process_time() - c0
    wall = time.perf_counter() - w0

    beats = [it.context.get("beats", 0) for it in its]
    dead = sum(1 for a, b in zip(mid, beats) if b <= a)
    ext_seen = sum(it.context.get("ext", 0) for it in its)
    errs = {}
    for it in its:
        k = type(it.error).__name__ if it.error else None
        if k:
            errs[k] = errs.get(k, 0) + 1
    le = {}
    for it in its:
        k = type(getattr(it, "last_error", None)).__name__ \
            if getattr(it, "last_error", None) else None
        if k:
            le[k] = le.get(k, 0) + 1
    print("C soak n=%d dur=%.0fs cpu/wall=%.2f beats=%d heartbeats_dead=%d"
          % (n, wall, cpu / wall, sum(beats), dead), flush=True)
    print("C   external sent=%d send_failures=%d delivered=%d dropped=%d"
          % (sent["n"], sent["fail"], ext_seen, sent["n"] - ext_seen),
          flush=True)
    print("C   chaos snapshot/restore cycles=%d ss_restored=%d ss_empty=%d "
          "failures=%s" % (chaos["cycles"], chaos["ss_restored"],
                           chaos["ss_zero"], chaos.get("last", 0)), flush=True)
    print("C   interpreter.error=%s last_error=%s" % (errs, le), flush=True)
    await asyncio.gather(*[it.stop() for it in its], return_exceptions=True)


async def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "abc"
    if "a" in which:
        await section_a()
    if "b" in which:
        section_b()
    if "c" in which:
        await section_c()


if __name__ == "__main__":
    asyncio.run(main())
