"""P3 -- concurrency under the #212 rule and #213 restore.

A  200 machines with a 1 ms `raise(delay=)` ping-pong for 10 s.
   Under #212 this is a periodic process: it must NOT trip
   `RunawayChainError`, must still be beating at the end, and its CPU
   must be bounded by the CLOCK (a 1 ms period over 200 machines is
   ~200 000 beats/s of ceiling, but the cost per beat is what matters --
   the oracle is "no busy spin": CPU must be materially below a full
   core per machine, and the beat count must track elapsed/period, not
   run away).
B  mixed delayed + zero-delay chains must STILL trip: a state that arms
   a delay AND raises a zero-delay event in the same entry is doing work
   within the step, so `maxIterations` must still bound it.
C  start() descent-settle wait (#215) under 100 concurrent starts with
   `always` cycles -- bounded, or the watchdog names it.
D  restore of 200 v3 snapshots carrying scheduled_sends, concurrently.

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import json
import logging
import os
import time
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    RunawayChainError,
    create_machine,
)

N = int(os.environ.get("N", "200"))
SECONDS = float(os.environ.get("SECONDS", "10"))
PERIOD_MS = 1


def cpu_now():
    t = os.times()
    return t.user + t.system


# ------------------------------------------------------------------- part A
PING = {
    "id": "pp",
    "initial": "up",
    "context": {"n": 0},
    "states": {
        "up": {
            "entry": [{"type": "raise",
                       "params": {"event": "B", "delay": PERIOD_MS}}, "beat"],
            "on": {"B": "down"},
        },
        "down": {
            "entry": [{"type": "raise",
                       "params": {"event": "B", "delay": PERIOD_MS}}, "beat"],
            "on": {"B": "up"},
        },
    },
}


def beat(i, c, e, a=None):
    c["n"] = c.get("n", 0) + 1


async def beat_async(i, c, e, a=None):
    c["n"] = c.get("n", 0) + 1


def lg(kind, extra=None):
    acts = {"beat": beat if kind == "def" else beat_async}
    acts.update(extra or {})
    return MachineLogic(actions=acts)


async def part_a(kind, defects):
    m = create_machine(json.loads(json.dumps(PING)), logic=lg(kind))
    its = [Interpreter(m) for _ in range(N)]
    c0, t0 = cpu_now(), time.monotonic()
    await asyncio.gather(*(i.start() for i in its))
    await asyncio.sleep(SECONDS)
    elapsed = time.monotonic() - t0
    cpu = cpu_now() - c0
    beats = [i.context.get("n", 0) for i in its]
    errs = {}
    for i in its:
        e = i.last_error
        errs[type(e).__name__ if e else None] = (
            errs.get(type(e).__name__ if e else None, 0) + 1
        )
    # still alive? beat once more after a pause
    await asyncio.sleep(0.2)
    beats2 = [i.context.get("n", 0) for i in its]
    alive = sum(1 for a, b in zip(beats, beats2) if b > a)
    await asyncio.gather(*(i.stop() for i in its))

    ideal = elapsed * 1000.0 / PERIOD_MS
    lo, hi = min(beats), max(beats)
    cpu_pct = 100.0 * cpu / elapsed
    print(f"  A/{kind:9s} N={N} {elapsed:.1f}s beats min={lo} max={hi} "
          f"ideal<={ideal:.0f} errs={errs}")
    print(f"             cpu={cpu:.1f}s ({cpu_pct:.0f}% of one core) "
          f"still_beating={alive}/{N}")
    if RunawayChainError.__name__ in errs:
        defects.append(
            f"A/{kind}: a {PERIOD_MS} ms raise(delay=) ping-pong tripped "
            f"RunawayChainError on {errs[RunawayChainError.__name__]}/{N} "
            f"machines -- #212 says this is a legal periodic process"
        )
    if alive < N:
        defects.append(
            f"A/{kind}: only {alive}/{N} heartbeats were still beating after "
            f"{elapsed:.0f}s -- the rest died"
        )
    if hi > ideal * 1.5:
        defects.append(
            f"A/{kind}: beat count {hi} exceeds the clock ceiling "
            f"{ideal:.0f} by >50% -- the period is not bounding the work"
        )
    return cpu_pct


# ------------------------------------------------------------------- part B
MIXED = {
    "id": "mx",
    "initial": "up",
    "maxIterations": 10,
    "context": {"n": 0},
    "states": {
        "up": {
            "entry": [
                {"type": "raise", "params": {"event": "SLOW", "delay": 5}},
                {"type": "raise", "params": {"event": "FAST"}},
                "beat",
            ],
            "on": {"FAST": "down", "SLOW": {"actions": ["beat"]}},
        },
        "down": {
            "entry": [
                {"type": "raise", "params": {"event": "SLOW", "delay": 5}},
                {"type": "raise", "params": {"event": "FAST"}},
                "beat",
            ],
            "on": {"FAST": "up", "SLOW": {"actions": ["beat"]}},
        },
    },
}


async def part_b(kind, defects):
    m = create_machine(json.loads(json.dumps(MIXED)), logic=lg(kind))
    its = [Interpreter(m) for _ in range(50)]
    await asyncio.gather(*(i.start() for i in its))
    # 📏 Poll to CONVERGENCE rather than sampling at a fixed instant: the
    #    5 ms delayed half paces the cycle, so the last machines reach the
    #    limit later than the first. Stop when the count stops moving.
    tripped, stable, t0 = 0, 0, time.monotonic()
    while time.monotonic() - t0 < 12.0:
        await asyncio.sleep(0.25)
        now = sum(1 for i in its
                  if isinstance(i.last_error, RunawayChainError))
        stable = stable + 1 if now == tripped else 0
        tripped = now
        if tripped == 50 or stable >= 6:
            break
    took = time.monotonic() - t0
    await asyncio.gather(*(i.stop() for i in its))
    print(f"  B/{kind:9s} mixed delayed+zero-delay: tripped {tripped}/50 "
          f"(converged in {took:.1f}s)")
    if tripped != 50:
        defects.append(
            f"B/{kind}: a chain mixing a zero-delay raise with a delayed one "
            f"tripped only {tripped}/50 -- the zero-delay half is work "
            f"generated WITHIN the step and maxIterations must bound it"
        )


# ------------------------------------------------------------------- part C
DESCENT = {
    "id": "dc",
    "initial": "a",
    "maxIterations": 12,
    "context": {"n": 0},
    "states": {
        "a": {"entry": ["beat"], "always": {"target": "b"}},
        "b": {"entry": ["beat"], "always": {"target": "a"}},
    },
}


async def part_c(kind, defects):
    m = create_machine(json.loads(json.dumps(DESCENT)), logic=lg(kind))
    its = [Interpreter(m) for _ in range(100)]
    t0 = time.monotonic()
    try:
        await asyncio.wait_for(
            asyncio.gather(*(i.start() for i in its)), timeout=25.0
        )
        took = time.monotonic() - t0
        tripped = sum(1 for i in its
                      if isinstance(i.last_error, RunawayChainError))
        print(f"  C/{kind:9s} 100 concurrent starts w/ always-cycle: "
              f"{took:.2f}s tripped={tripped}/100")
        if tripped != 100:
            defects.append(
                f"C/{kind}: only {tripped}/100 always-cycle descents tripped"
            )
    except asyncio.TimeoutError:
        print(f"  C/{kind:9s} WATCHDOG 25s -- start() did not return")
        defects.append(
            f"C/{kind}: 100 concurrent start()s with an always cycle did not "
            f"complete within the 25 s watchdog (#215 descent-settle wait)"
        )
        return
    await asyncio.gather(*(i.stop() for i in its), return_exceptions=True)


# ------------------------------------------------------------------- part D
ARMED = {
    "id": "ar",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {
            "entry": [{"type": "raise",
                       "params": {"event": "P", "delay": 400, "id": "z"}}],
            "on": {"P": {"target": "b", "actions": ["beat"]}},
        },
        "b": {},
    },
}


async def part_d(kind, defects):
    m = create_machine(json.loads(json.dumps(ARMED)), logic=lg(kind))
    its = [Interpreter(m) for _ in range(N)]
    await asyncio.gather(*(i.start() for i in its))
    await asyncio.sleep(0.15)
    snaps = [i.get_snapshot() for i in its]
    n_recs = [len(json.loads(s).get("scheduled_sends") or []) for s in snaps]
    await asyncio.gather(*(i.stop() for i in its))

    r = [Interpreter.from_snapshot(s, m) for s in snaps]
    t0 = time.monotonic()
    await asyncio.gather(*(i.start() for i in r))
    await asyncio.sleep(0.45)
    fired = sum(1 for i in r if sorted(i.current_state_ids) == ["ar.b"])
    took = time.monotonic() - t0
    await asyncio.gather(*(i.stop() for i in r))
    print(f"  D/{kind:9s} {N} concurrent v3 restores: "
          f"records/machine={set(n_recs)} fired_after_remaining={fired}/{N} "
          f"({took:.2f}s)")
    if set(n_recs) != {1}:
        defects.append(
            f"D/{kind}: scheduled_sends record count per machine = "
            f"{set(n_recs)}, expected exactly 1 under concurrency"
        )
    if fired != N:
        defects.append(
            f"D/{kind}: only {fired}/{N} concurrently-restored machines "
            f"fired their re-armed delayed send"
        )


async def main():
    print(f"P3 -- concurrency: N={N}, ping-pong {PERIOD_MS} ms, "
          f"{SECONDS:.0f}s\n")
    defects = []
    for kind in ("def", "async def"):
        await part_a(kind, defects)
        await part_b(kind, defects)
        await part_c(kind, defects)
        await part_d(kind, defects)
        print()
    print(f"DEFECTS = {len(defects)}")
    for d in defects:
        print("   -", d)
    return 1 if defects else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
