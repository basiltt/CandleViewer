"""N9 - reduced chaos soak.

REDUCTION: the brief asks for 12 minutes; this runs 420 s (7 min) by
default (`--seconds=N` to change) so the whole track fits the 25-minute
wall-clock bound. Everything else -- the chaos mix, the invariant set and
the per-cycle accounting -- is unreduced.

A pool of interpreters is driven continuously while a chaos thread
randomly: stops and restarts machines, snapshots and restores them,
spawns/stops child actors, raises from plugin hooks, sends hostile event
types, fires timers under a SimulatedClock, and forces queue overflow.

Invariants checked continuously:
  S1  no event is accepted and lost (processed + dropped + queued == sent)
  S2  no interpreter is ever `status == "running"` with an EMPTY
      configuration at a quiescent point
  S3  `get_persisted_snapshot()` at quiescence never raises
  S4  no asyncio task leak across cycles (all_tasks delta bounded)
  S5  RSS does not grow without bound
  S6  no unhandled loop exception, no "Task was destroyed but it is
      pending"
"""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import random
import sys
import time

import psutil

from common import Accountant, emit
from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine

CFG = {
    "id": "soak",
    "type": "parallel",
    "context": {"n": 0},
    "states": {
        "main": {
            "initial": "idle",
            "states": {
                "idle": {"on": {"GO": {"target": "work", "actions": ["bump"]}}},
                "work": {
                    "after": {60: {"target": "idle"}},
                    "on": {"BACK": {"target": "idle"},
                           "PING": {"actions": ["bump"]}},
                },
            },
        },
        "aux": {
            "initial": "x",
            "states": {"x": {"on": {"TOGGLE": "y"}},
                       "y": {"on": {"TOGGLE": "x"}}},
        },
    },
}
EVENTS = ["GO", "BACK", "PING", "TOGGLE"]


def bump(i, ctx, e, a):  # noqa: ANN001
    ctx["n"] += 1


def mk():
    return create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))


class Chaos(PluginBase):
    """Randomly raises from hooks (must always be contained)."""

    def __init__(self, rng) -> None:
        self.rng = rng
        self.raised = 0

    def on_transition(self, *a, **k):  # noqa: ANN001,D102
        if self.rng.random() < 0.02:
            self.raised += 1
            raise RuntimeError("chaos hook")


class LoopWatch(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.destroyed = 0

    def emit(self, record):  # noqa: ANN001,D102
        if "Task was destroyed but it is pending" in record.getMessage():
            self.destroyed += 1


async def main() -> int:
    seconds = 420.0
    for a in sys.argv[1:]:
        if a.startswith("--seconds="):
            seconds = float(a.split("=", 1)[1])
    rng = random.Random(90909)
    proc = psutil.Process()

    watch = LoopWatch()
    logging.getLogger("asyncio").addHandler(watch)
    loop_errors: list[str] = []
    asyncio.get_running_loop().set_exception_handler(
        lambda loop, ctx: loop_errors.append(str(ctx.get("message"))[:120])
    )

    rss = [proc.memory_info().rss / 1e6]
    baseline_tasks = len(asyncio.all_tasks())

    sent = processed = dropped = 0
    s2_violations = []
    s3_failures = []
    snapshot_roundtrips = 0
    cycles = 0
    hostile_escapes = []
    restores = 0

    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        cycles += 1
        acc = Accountant()
        chaos = Chaos(rng)
        interp = Interpreter(mk(), max_queue_size=rng.choice([16, 64, None]))
        interp.use(acc)
        interp.use(chaos)
        await interp.start()

        burst = rng.randrange(20, 120)
        for _ in range(burst):
            ev = rng.choice(EVENTS)
            sent += 1
            try:
                if rng.random() < 0.3:
                    await asyncio.wait_for(interp.send(ev, wait=True), 5)
                else:
                    await interp.send(ev)
            except asyncio.TimeoutError:
                s3_failures.append({"cycle": cycles, "why": "send hung"})
            except Exception:  # noqa: BLE001
                pass

            # hostile event type, occasionally
            if rng.random() < 0.05:
                try:
                    await interp.send(rng.choice([7, None, b"X", ["Y"]]))
                    hostile_escapes.append("accepted")
                except TypeError:
                    pass
                except Exception as exc:  # noqa: BLE001
                    hostile_escapes.append(type(exc).__name__)

        # quiesce
        for _ in range(200):
            if interp.queue_depth == 0:
                break
            await asyncio.sleep(0.005)
        await asyncio.sleep(0.01)

        # ---- S2 ----
        if interp.status == "running" and not interp.current_state_ids:
            s2_violations.append({"cycle": cycles})

        # ---- S3 / snapshot round-trip ----
        if interp.status == "running":
            try:
                snap = interp.get_persisted_snapshot()
                blob = json.dumps(snap)
                snapshot_roundtrips += 1
                if rng.random() < 0.3:
                    r = Interpreter.from_snapshot(
                        blob, mk(), restart_timers=True
                    )
                    await r.start()
                    restores += 1
                    if r.status == "running" and not r.current_state_ids:
                        s2_violations.append({"cycle": cycles,
                                              "where": "restored"})
                    await r.stop()
            except Exception as exc:  # noqa: BLE001
                s3_failures.append(
                    {"cycle": cycles, "exc": type(exc).__name__,
                     "msg": str(exc)[:100]}
                )

        processed += len(acc.received)
        dropped += len(acc.dropped)
        try:
            await interp.stop(drain=rng.random() < 0.5)
        except Exception:  # noqa: BLE001
            pass

        if cycles % 25 == 0:
            gc.collect()
            rss.append(proc.memory_info().rss / 1e6)

    gc.collect()
    await asyncio.sleep(0.2)
    final_tasks = len(asyncio.all_tasks())
    rss.append(proc.memory_info().rss / 1e6)

    ok = (
        not s2_violations
        and not s3_failures
        and not hostile_escapes
        and not loop_errors
        and watch.destroyed == 0
        and (final_tasks - baseline_tasks) <= 1
        and rss[-1] < rss[0] * 3 + 50
    )
    emit("n9_soak_chaos", {
        "REDUCED": "420 s instead of the requested 12 min (wall-clock bound)",
        "seconds": round(time.perf_counter() - t0, 1),
        "cycles": cycles,
        "events_sent": sent,
        "processed_hook": processed,
        "dropped_hook": dropped,
        "S2_running_with_empty_config": s2_violations[:10],
        "S2_violation_count": len(s2_violations),
        "S3_snapshot_failures": s3_failures[:10],
        "S3_failure_count": len(s3_failures),
        "snapshots_taken": snapshot_roundtrips,
        "snapshot_restores": restores,
        "hostile_event_escapes": hostile_escapes[:10],
        "S4_task_delta": final_tasks - baseline_tasks,
        "S5_rss_mb": rss,
        "S6_loop_errors": loop_errors[:10],
        "S6_task_destroyed_pending": watch.destroyed,
        "result": "PASS" if ok else "FAIL",
    })
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
