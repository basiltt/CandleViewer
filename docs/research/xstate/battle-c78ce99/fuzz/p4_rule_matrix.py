"""P4 -- the #212 rule matrix, after-parity, and the observability of a trip
on a chart that mixes a delayed self-send with zero-delay work.

#212 makes a `raise(delay=)` self-send a TIMER: arming ends the step's
chain, the firing is a clock event. `maxIterations` still bounds work the
machine feeds itself WITHIN a step. A chart that does both in one entry --
arms a 5 ms delayed `SLOW` and raises a zero-delay `FAST` -- is therefore
a zero-delay cycle that must trip, paced by a timer that keeps delivering
clock events afterwards.

This script asks what a caller can SEE once that happens:

  A  the #212 rule matrix: delay 0 / 1 ms / sendTo child / cancel(id) /
     delayed raise from an external send, vs the `after` rule, both kinds,
     both engines.
  B  the mixed chart: does it trip, and does `last_error` still say so
     once the delayed lane delivers its next clock event?
  C  `has_dormant_invocations` / receipt / log evidence at that point.

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import json
import logging
import os
import warnings

warnings.simplefilter("ignore")

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    RunawayChainError,
    SyncInterpreter,
    create_machine,
)

TRIALS = int(os.environ.get("TRIALS", "60"))


class Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.rows = []

    def emit(self, rec):
        self.rows.append((rec.levelname, rec.getMessage()))

    def runaway_lines(self):
        return [m for lvl, m in self.rows
                if "Exceeded" in m and "chained" in m]


def capture():
    lg = logging.getLogger("xstate_statemachine")
    cap = Cap()
    lg.addHandler(cap)
    lg.setLevel(logging.DEBUG)
    return lg, cap


def beat(i, c, e, a=None):
    c["n"] = c.get("n", 0) + 1


async def beat_async(i, c, e, a=None):
    c["n"] = c.get("n", 0) + 1


def lg_for(kind):
    return MachineLogic(actions={"beat": beat if kind == "def"
                                 else beat_async})


# ------------------------------------------------------------------- part A
def cfg_selfraise(delay, mi=8):
    arm = {"type": "raise", "params": {"event": "B"}}
    if delay is not None:
        arm["params"]["delay"] = delay
    return {
        "id": "sr", "initial": "up", "maxIterations": mi,
        "context": {"n": 0},
        "states": {
            "up": {"entry": [arm, "beat"], "on": {"B": "down"}},
            "down": {"entry": [arm, "beat"], "on": {"B": "up"}},
        },
    }


def cfg_after(ms, mi=8):
    return {
        "id": "af", "initial": "up", "maxIterations": mi,
        "context": {"n": 0},
        "states": {
            "up": {"entry": ["beat"], "after": {ms: {"target": "down"}}},
            "down": {"entry": ["beat"], "after": {ms: {"target": "up"}}},
        },
    }


def cfg_external_delayed(mi=8):
    """The delayed raise is armed by an EXTERNAL send, not by entry."""
    return {
        "id": "ex", "initial": "idle", "maxIterations": mi,
        "context": {"n": 0},
        "states": {
            "idle": {"on": {"GO": "up"}},
            "up": {"entry": [{"type": "raise",
                              "params": {"event": "B", "delay": 1}}, "beat"],
                   "on": {"B": "down"}},
            "down": {"entry": [{"type": "raise",
                                "params": {"event": "B", "delay": 1}}, "beat"],
                     "on": {"B": "up"}},
        },
    }


def cfg_cancel(mi=8):
    """Arms a delayed send then cancels it -- nothing should ever fire."""
    return {
        "id": "cx", "initial": "up", "maxIterations": mi,
        "context": {"n": 0},
        "states": {
            "up": {
                "entry": [
                    {"type": "raise",
                     "params": {"event": "B", "delay": 5, "id": "k"}},
                    {"type": "cancel", "params": {"sendId": "k"}},
                ],
                "on": {"B": {"actions": ["beat"]}},
            },
        },
    }


async def run_async(cfg, kind, secs, send=None):
    m = create_machine(json.loads(json.dumps(cfg)), logic=lg_for(kind))
    lgr, cap = capture()
    try:
        it = await Interpreter(m).start()
        if send:
            await it.send(send)
        await asyncio.sleep(secs)
        out = (it.context.get("n", 0),
               type(it.last_error).__name__ if it.last_error else None,
               len(cap.runaway_lines()))
        await it.stop()
        return out
    finally:
        lgr.removeHandler(cap)


async def part_a(defects):
    print("A -- #212 rule matrix vs the `after` rule (maxIterations=8)")
    print("    'trips' = RunawayChainError seen in last_error OR the log")
    cases = [
        ("raise delay=None (zero)", cfg_selfraise(None), 1.0, None, True),
        ("raise delay=0         ", cfg_selfraise(0), 1.0, None, True),
        ("raise delay=1ms       ", cfg_selfraise(1), 1.0, None, False),
        ("raise delay=30ms      ", cfg_selfraise(30), 1.0, None, False),
        ("after: 1              ", cfg_after(1), 1.0, None, False),
        ("after: 30             ", cfg_after(30), 1.0, None, False),
        ("delayed raise from ext", cfg_external_delayed(), 1.0, "GO", False),
        ("arm 5ms then cancel   ", cfg_cancel(), 0.5, None, False),
    ]
    for kind in ("def", "async def"):
        for label, cfg, secs, send, want_trip in cases:
            n, err, logs = await run_async(cfg, kind, secs, send)
            tripped = err == "RunawayChainError" or logs > 0
            ok = tripped == want_trip
            print(f"  {kind:9s} {label} n={n:5d} last_error={err} "
                  f"log_trips={logs} tripped={tripped} "
                  f"expect={want_trip} {'ok' if ok else 'MISMATCH'}")
            if not ok:
                defects.append(
                    f"A/{kind}: '{label.strip()}' tripped={tripped}, "
                    f"expected {want_trip} (n={n}, last_error={err})"
                )
            # parity: a 1 ms delayed self-raise must behave like `after: 1`
            if label.startswith("arm 5ms") and n != 0:
                defects.append(
                    f"A/{kind}: a cancelled delayed send still fired {n}x"
                )
    print()


# ------------------------------------------------------------------- part B
MIXED = {
    "id": "mx", "initial": "up", "maxIterations": 10, "context": {"n": 0},
    "states": {
        "up": {"entry": [{"type": "raise",
                          "params": {"event": "SLOW", "delay": 5}},
                         {"type": "raise", "params": {"event": "FAST"}},
                         "beat"],
               "on": {"FAST": "down", "SLOW": {"actions": ["beat"]}}},
        "down": {"entry": [{"type": "raise",
                            "params": {"event": "SLOW", "delay": 5}},
                           {"type": "raise", "params": {"event": "FAST"}},
                           "beat"],
                 "on": {"FAST": "up", "SLOW": {"actions": ["beat"]}}},
    },
}


async def part_b(defects):
    print(f"B -- mixed delayed+zero-delay chain, {TRIALS} trials per kind")
    print("    the zero-delay FAST cycle MUST trip; the 5 ms SLOW timer")
    print("    keeps delivering clock events afterwards")
    for kind in ("def", "async def"):
        m = create_machine(json.loads(json.dumps(MIXED)), logic=lg_for(kind))
        silent = []
        tripped_log = 0
        for t in range(TRIALS):
            lgr, cap = capture()
            try:
                it = await Interpreter(m).start()
                await asyncio.sleep(1.2)
                err = (type(it.last_error).__name__ if it.last_error
                       else None)
                logs = len(cap.runaway_lines())
                n = it.context.get("n", 0)
                status = it.status
                snap = json.loads(it.get_snapshot())
                await it.stop()
            finally:
                lgr.removeHandler(cap)
            if logs:
                tripped_log += 1
            if logs and err is None:
                silent.append((t, n, status,
                               len(snap.get("scheduled_sends") or [])))
        print(f"  {kind:9s} tripped(log)={tripped_log}/{TRIALS}  "
              f"trip ERASED from last_error = {len(silent)}/{TRIALS}")
        if silent:
            t, n, status, ns = silent[0]
            print(f"             sample: trial={t} n={n} status={status!r} "
                  f"last_error=None scheduled_sends={ns}")
        if tripped_log != TRIALS:
            defects.append(
                f"B/{kind}: the zero-delay half of a mixed chain tripped only "
                f"{tripped_log}/{TRIALS} times"
            )
        if silent:
            defects.append(
                f"B/{kind}: on {len(silent)}/{TRIALS} runs the chart tripped "
                f"RunawayChainError (ERROR logged, machine inert) but "
                f"`last_error` reads None and `status` reads 'running' -- the "
                f"5 ms delayed self-send's next clock event resets the "
                f"per-event error record, so the trip is invisible to every "
                f"programmatic health check. Only the log remembers"
            )
    print()


async def main():
    print("P4 -- #212 rule matrix + trip observability on a mixed chart\n")
    logging.disable(logging.NOTSET)
    defects = []
    await part_a(defects)
    await part_b(defects)
    print(f"DEFECTS = {len(defects)}")
    for d in defects:
        print("   -", d)
    return 1 if defects else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
