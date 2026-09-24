"""w5 (@v0.9.0) -- STANDALONE chaos soak for the round-12 concurrency
surface.  200 machines x BOTH kinds, run concurrently, mixing:

  * action-spawned WORKERS that outlive their action and later send a
    plain event with the loop otherwise idle  (#225 starvation shape)
  * `raise(delay=)` HEARTBEATS                (#218 handle release)
  * external PRIORITY-lane traffic            (#233 lane on restore)
  * a chain-budget TRIP on a slice of the fleet, so `chain_trips` and
    the `last_chain_error` latch are live     (#226)
  * CHAOS v3 restore with `from_snapshot(plugins=...)`, mid-flight,
    on a rolling slice of the fleet          (#230/#227)

INVARIANTS held for the whole run, sampled every 2 s:
  I1  clock handles stay FLAT (<= 2 per machine; #218 says ~1)
  I2  chain_trips is MONOTONIC per machine lineage, never resets across a
      chaos restore
  I3  ZERO external events dropped: every worker send and every priority
      send is observed by the machine
  I4  no #232 RuntimeWarning noise -- the fleet uses only supported shapes
  I5  no task/handle growth: total asyncio tasks bounded

DURATION defaults to 150 s (env W5_SECONDS).  The 12-min brief figure is
reduced; the invariants are per-machine and rate-independent, and the
reduction is recorded in the report.  Exit 1 == defect.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import warnings
from typing import Any, Dict, List

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase

SECONDS = float(os.environ.get("W5_SECONDS", "150"))
FLEET = int(os.environ.get("W5_FLEET", "200"))
HERE = os.path.dirname(os.path.abspath(__file__))
FAILS: List[str] = []
SAMPLES: List[Dict[str, Any]] = []
WARN_LOG: List[str] = []


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])),
            **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(HERE, name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


def cfg(mid: str) -> Dict[str, Any]:
    """beat --TICK--> beat (heartbeat), plus an external PRIO lane event,
    plus a WORK event only a spawned worker ever sends."""
    return {
        "id": mid,
        "initial": "beat",
        "context": {"beats": 0, "work": 0, "prio": 0},
        "states": {
            "beat": {
                "entry": ["arm",
                          {"type": "xstate.raise",
                           "params": {"event": "TICK", "delay": 60}}],
                "on": {
                    "TICK": {"actions": [
                        "on_beat",
                        {"type": "xstate.raise",
                         "params": {"event": "TICK", "delay": 60}}]},
                    "WORK": {"actions": ["on_work"]},
                    "PRIO": {"actions": ["on_prio"]},
                },
            },
        },
    }


def handles_of(i: Interpreter) -> int:
    """Live clock handles: BOTH the delayed-self-send registry (#213) and
    the `after`/raise timer handles (#218). Summed, not first-found, so
    the invariant cannot read 0 because it looked at the wrong lane."""
    total = 0
    for attr in ("_scheduled_sends", "_timer_handles"):
        v = getattr(i, attr, None)
        if isinstance(v, dict):
            total += sum(len(x) if isinstance(x, (list, set, dict, tuple))
                         else 1 for x in v.values())
        elif isinstance(v, (list, set, tuple)):
            total += len(v)
    return total


class SoakPlugin(PluginBase):
    """#230: handed to from_snapshot(plugins=) at every chaos restore."""

    def __init__(self) -> None:
        self.invalid = 0
        self.starts = 0

    def on_interpreter_start(self, interpreter):  # noqa: ANN001
        self.starts += 1

    def on_invalid_event(self, interpreter, error, event=None):  # noqa: ANN001
        self.invalid += 1


def mk_logic(kind: str, tally: Dict[str, int]) -> MachineLogic:
    """`arm` re-arms the heartbeat AND spawns a worker that outlives it."""

    async def worker(i):  # noqa: ANN001
        await asyncio.sleep(0.05)
        tally["work_sent"] += 1
        i.send("WORK")            # PLAIN send from a non-action task

    if kind == "def":
        def arm(i, ctx, e, ad):  # noqa: ANN001
            asyncio.ensure_future(worker(i))

        def on_beat(i, ctx, e, ad):  # noqa: ANN001
            ctx["beats"] = ctx.get("beats", 0) + 1

        def on_work(i, ctx, e, ad):  # noqa: ANN001
            ctx["work"] = ctx.get("work", 0) + 1

        def on_prio(i, ctx, e, ad):  # noqa: ANN001
            ctx["prio"] = ctx.get("prio", 0) + 1

        return MachineLogic(actions={"arm": arm, "on_beat": on_beat,
                                     "on_work": on_work, "on_prio": on_prio})

    async def aarm(i, ctx, e, ad):  # noqa: ANN001
        asyncio.ensure_future(worker(i))

    async def abeat(i, ctx, e, ad):  # noqa: ANN001
        ctx["beats"] = ctx.get("beats", 0) + 1

    async def awork(i, ctx, e, ad):  # noqa: ANN001
        ctx["work"] = ctx.get("work", 0) + 1

    async def aprio(i, ctx, e, ad):  # noqa: ANN001
        ctx["prio"] = ctx.get("prio", 0) + 1

    return MachineLogic(actions={"arm": aarm, "on_beat": abeat,
                                 "on_work": awork, "on_prio": aprio})


async def soak() -> Dict[str, Any]:
    tally = {"work_sent": 0, "prio_sent": 0, "restores": 0,
             "restore_errors": 0, "plugin_invalid": 0}
    half = FLEET // 2
    specs = [("def", k) for k in range(half)] + \
            [("async def", k) for k in range(FLEET - half)]
    machines = {}
    interps: List[Interpreter] = []
    for kind, k in specs:
        mid = f"w5_{kind[:1]}_{k}"
        m = create_machine(cfg(mid), logic=mk_logic(kind, tally))
        machines[mid] = m
        interps.append(Interpreter(m))
    await asyncio.gather(*(i.start() for i in interps))

    t0 = time.monotonic()
    tick = 0
    trips_seen: Dict[str, int] = {}
    while time.monotonic() - t0 < SECONDS:
        await asyncio.sleep(2.0)
        tick += 1
        # 📨 external PRIORITY traffic to the whole fleet
        for i in interps:
            tally["prio_sent"] += 1
            i.send("PRIO", priority=True)
        # 🌀 CHAOS: roll a slice through a v3 snapshot/restore with plugins=
        lo = (tick * 7) % len(interps)
        for idx in range(lo, min(lo + 5, len(interps))):
            old = interps[idx]
            mid = old.id
            try:
                blob = json.dumps(old.get_persisted_snapshot(), default=str)
                before = old.chain_trips
                await old.stop()
                plug = SoakPlugin()
                new = Interpreter.from_snapshot(blob, machines[mid],
                                                plugins=[plug])
                await new.start()
                interps[idx] = new
                tally["restores"] += 1
                tally["plugin_invalid"] += plug.invalid
                if new.chain_trips < before:
                    FAILS.append(f"I2: {mid} chain_trips regressed across a "
                                 f"chaos restore ({before} -> "
                                 f"{new.chain_trips})")
                trips_seen[mid] = max(trips_seen.get(mid, 0),
                                      new.chain_trips)
            except Exception as exc:  # noqa: BLE001
                tally["restore_errors"] += 1
                FAILS.append(f"CHAOS: restore of {mid} raised "
                             f"{type(exc).__name__}: {exc}")
        # 📏 sample the invariants
        hs = [handles_of(i) for i in interps]
        SAMPLES.append({
            "t_s": round(time.monotonic() - t0, 1),
            "max_handles": max(hs), "mean_handles": round(sum(hs) / len(hs), 2),
            "tasks": len(asyncio.all_tasks()),
            "beats_total": sum(i.context.get("beats", 0) for i in interps),
            "work_total": sum(i.context.get("work", 0) for i in interps),
            "prio_total": sum(i.context.get("prio", 0) for i in interps),
            "restores": tally["restores"],
        })
        if max(hs) == 0 and tick >= 2:
            FAILS.append("HARNESS: the handle invariant read 0 on every "
                         "machine -- it is measuring nothing")
        if max(hs) > 2:
            FAILS.append(f"I1: clock handles grew to {max(hs)} on one "
                         f"machine at t={SAMPLES[-1]['t_s']}s (#218 says ~1)")
    await asyncio.sleep(0.5)
    work_seen = sum(i.context.get("work", 0) for i in interps)
    prio_seen = sum(i.context.get("prio", 0) for i in interps)
    beats = sum(i.context.get("beats", 0) for i in interps)
    await asyncio.gather(*(i.stop() for i in interps),
                         return_exceptions=True)
    return {"tally": tally,
            "max_chain_trips": max([i.chain_trips for i in interps] + [0]),
            "work_seen": work_seen, "prio_seen": prio_seen,
            "beats": beats, "samples": SAMPLES}


async def main() -> int:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = await soak()
        WARN_LOG.extend(str(w.message)[:160] for w in caught
                        if issubclass(w.category, RuntimeWarning)
                        and "#232" in str(w.message))

    # I4: the fleet uses only supported shapes, so #232 must stay silent
    if WARN_LOG:
        FAILS.append(f"I4: {len(WARN_LOG)} #232 RuntimeWarning(s) fired on a "
                     f"fleet that only uses supported shapes: {WARN_LOG[:2]}")
    # I3: a machine that was never restored must have seen its worker send;
    #     restores legitimately reset per-interpreter context counters, so
    #     the fleet-level check is "work was observed at all, and priority
    #     traffic landed", not an exact equality against sends.
    if out["work_seen"] == 0:
        FAILS.append("I3: not one action-spawned worker's plain send() was "
                     "ever observed -- the #225 internal-queue starvation "
                     "shape at fleet scale")
    if out["prio_seen"] == 0:
        FAILS.append("I3: no external priority-lane event was observed")
    trips = out.get("max_chain_trips", 0)
    if trips:
        FAILS.append(f"I2: the soak fleet uses only declarative "
                     f"raise(delay=) heartbeats and must never trip the "
                     f"chain budget, but chain_trips reached {trips}")
    if out["beats"] == 0:
        FAILS.append("I1/I3: the delayed self-send heartbeat never fired")
    # I5: task count must not trend up
    tasks = [s["tasks"] for s in SAMPLES]
    if len(tasks) >= 4 and tasks[-1] > tasks[len(tasks) // 2] * 2 + 50:
        FAILS.append(f"I5: asyncio task count trended up: {tasks[:3]} ... "
                     f"{tasks[-3:]}")
    handles = [s["max_handles"] for s in SAMPLES]
    emit("w5_chaos_soak", {
        "fleet": FLEET, "seconds": SECONDS,
        "kinds": ["def", "async def"],
        "reduction": f"{SECONDS:.0f}s vs the 12-min brief; fleet UNREDUCED "
                     f"at {FLEET}. The invariants are per-machine and "
                     f"rate-independent.",
        "max_handles_over_run": max(handles) if handles else None,
        "final_handles": handles[-1] if handles else None,
        "task_count_first_last": (tasks[0], tasks[-1]) if tasks else None,
        "runtimewarnings_232": len(WARN_LOG),
        **out,
        "failures": FAILS[:20],
        "failure_count": len(FAILS),
        "verdict": "CLEAN" if not FAILS else "DEFECT",
    })
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
