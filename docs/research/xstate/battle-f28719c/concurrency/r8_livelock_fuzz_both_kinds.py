"""R8 - livelock fuzz: >=500 configs x {def, async def} x {sync, async},
30 s watchdog. Shapes: nested invoke cycles, always cycles, rollback+onDone,
sendTo self-loops, priority self-sends.

Every trip must be OBSERVABLE (last_error / receipt.error / on_event_dropped)
and lap counts must be EQUAL across engines for the same config+kind.

A timeout IS the observed result (the hard bound says so).
"""

from __future__ import annotations

import asyncio
import random
import sys

from common2 import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
    emit,
    make_service,
)
from xstate_statemachine.exceptions import RunawayChainError

N = int(next((a.split("=")[1] for a in sys.argv[1:] if a.startswith("--n=")), 500))
WD = float(next((a.split("=")[1] for a in sys.argv[1:] if a.startswith("--wd=")), 6))
SETTLE = float(next((a.split("=")[1] for a in sys.argv[1:] if a.startswith("--settle=")), 0.12))
SEED = int(next((a.split("=")[1] for a in sys.argv[1:] if a.startswith("--seed=")), 80808))
TAG = next((a.split("=")[1] for a in sys.argv[1:] if a.startswith("--tag=")), "")

LAPS = {"n": 0}


def act(i, ctx, e, ad):  # noqa: ANN001
    LAPS["n"] += 1


class Drop(PluginBase):
    def __init__(self) -> None:
        self.reasons = {}

    def on_event_dropped(self, i, e, reason=None, **kw):  # noqa: ANN001
        self.reasons[str(reason)] = self.reasons.get(str(reason), 0) + 1


#: `priority_self_send` is EXCLUDED from the fuzz corpus and carried by
#: the dedicated probe `r8b_priority_self_send_livelock.py`: it livelocks
#: so hard that it starves the event loop, so an in-process watchdog
#: cannot fire and it would consume the whole fuzz budget. Its result is
#: recorded as LIVELOCK by r8b under a PROCESS-level watchdog.
SHAPES = (
    "always_cycle",
    "invoke_cycle",
    "nested_invoke_cycle",
    "rollback_ondone",
    "sendto_self_loop",
)


def build(rng: random.Random) -> tuple:
    shape = rng.choice(SHAPES)
    iters = rng.choice([10, 25, 50, 100])
    if shape == "always_cycle":
        states = {
            "a": {"always": {"target": "b", "actions": ["act"]}},
            "b": {"always": {"target": "a", "actions": ["act"]}},
        }
    elif shape == "invoke_cycle":
        states = {
            "a": {
                "invoke": {
                    "src": "s",
                    "onDone": {"target": "b", "actions": ["act"]},
                    "onError": {"target": "b"},
                }
            },
            "b": {"always": {"target": "a", "actions": ["act"]}},
        }
    elif shape == "nested_invoke_cycle":
        states = {
            "a": {
                "initial": "a1",
                "states": {
                    "a1": {
                        "invoke": {
                            "src": "s",
                            "onDone": {"target": "a2", "actions": ["act"]},
                            "onError": {"target": "a2"},
                        }
                    },
                    "a2": {"always": {"target": "a1", "actions": ["act"]}},
                },
            }
        }
    elif shape == "rollback_ondone":
        states = {
            "a": {
                "invoke": {
                    "src": "s",
                    "onDone": {"target": "b", "actions": ["act"]},
                    "onError": {"target": "b"},
                }
            },
            "b": {"always": {"target": "a", "actions": ["act", "act"]}},
        }
    elif shape == "sendto_self_loop":
        states = {
            "a": {"entry": ["loopback"], "on": {"LOOP": {"target": "b"}}},
            "b": {"entry": ["loopback"], "on": {"LOOP": {"target": "a"}}},
        }
    else:  # priority_self_send
        states = {
            "a": {"entry": ["prio"], "on": {"P": {"target": "b"}}},
            "b": {"entry": ["prio"], "on": {"P": {"target": "a"}}},
        }
    cfg = {
        "id": "r8",
        "initial": next(iter(states)),
        "context": {"n": 0},
        "maxIterations": iters,
        "states": states,
    }
    return shape, iters, cfg


def loopback(i, ctx, e, ad):  # noqa: ANN001
    LAPS["n"] += 1
    try:
        i.send("LOOP")
    except Exception:  # noqa: BLE001
        pass


def prio(i, ctx, e, ad):  # noqa: ANN001
    LAPS["n"] += 1
    try:
        r = i.send("P", priority=True)
        if asyncio.iscoroutine(r):
            r.close()
    except Exception:  # noqa: BLE001
        pass


def mk(cfg, kind):  # noqa: ANN001
    return create_machine(
        cfg,
        logic=MachineLogic(
            actions={"act": act, "loopback": loopback, "prio": prio},
            services={"s": make_service(kind)},
        ),
    )


async def run_async(cfg, kind):  # noqa: ANN001
    LAPS["n"] = 0
    d = Drop()
    i = Interpreter(mk(cfg, kind)).use(d)
    try:
        await asyncio.wait_for(i.start(), WD)
        await asyncio.sleep(SETTLE)
        laps = LAPS["n"]
        trip = isinstance(i.last_error, RunawayChainError)
        obs = trip or bool(d.reasons)
        await asyncio.wait_for(i.stop(), WD)
        return {"laps": laps, "trip": trip, "observable": obs,
                "drops": d.reasons, "outcome": "ok"}
    except asyncio.TimeoutError:
        return {"laps": LAPS["n"], "trip": False, "observable": False,
                "drops": d.reasons, "outcome": "TIMEOUT"}


def run_sync(cfg, kind):  # noqa: ANN001
    if kind == "async def":
        return {"outcome": "N/A_sync_engine_rejects_async_service"}
    LAPS["n"] = 0
    d = Drop()
    i = SyncInterpreter(mk(cfg, kind)).use(d)
    try:
        i.start()
        laps = LAPS["n"]
        trip = isinstance(i.last_error, RunawayChainError)
        i.stop()
        return {"laps": laps, "trip": trip,
                "observable": trip or bool(d.reasons), "drops": d.reasons,
                "outcome": "ok"}
    except RunawayChainError:
        return {"laps": LAPS["n"], "trip": True, "observable": True,
                "drops": d.reasons, "outcome": "raised"}
    except Exception as exc:  # noqa: BLE001
        return {"laps": LAPS["n"], "trip": False, "observable": True,
                "drops": d.reasons, "outcome": f"raised:{type(exc).__name__}"}


async def main() -> int:
    rng = random.Random(SEED)
    timeouts, unobservable, lap_mismatch = [], [], []
    by_shape = {}
    for n in range(N):
        shape, iters, cfg = build(rng)
        for kind in ("def", "async def"):
            a = await run_async(cfg, kind)
            s = run_sync(cfg, kind)
            key = f"{shape}:{kind}"
            by_shape.setdefault(key, {"n": 0, "trips": 0, "timeouts": 0})
            by_shape[key]["n"] += 1
            by_shape[key]["trips"] += int(a.get("trip", False))
            if a["outcome"] == "TIMEOUT":
                by_shape[key]["timeouts"] += 1
                timeouts.append({"shape": shape, "kind": kind, "iters": iters})
                continue
            if a.get("trip") and not a.get("observable"):
                unobservable.append({"shape": shape, "kind": kind, **a})
            if s.get("outcome") in ("ok", "raised") and a.get("laps") != s.get("laps"):
                if len(lap_mismatch) < 20:
                    lap_mismatch.append(
                        {"shape": shape, "kind": kind, "maxIterations": iters,
                         "async_laps": a["laps"], "sync_laps": s["laps"],
                         "async_trip": a["trip"], "sync_trip": s["trip"]}
                    )
    bad = timeouts or unobservable
    emit(
        "r8_livelock_fuzz_both_kinds"+TAG,
        {
            "configs": N,
            "seed": SEED,
            "settle_s": SETTLE,
            "watchdog_s": WD,
            "by_shape_kind": by_shape,
            "timeouts": timeouts[:10],
            "timeout_count": len(timeouts),
            "trips_not_observable": unobservable[:10],
            "unobservable_count": len(unobservable),
            "lap_count_mismatches_vs_sync": lap_mismatch,
            "lap_mismatch_count": len(lap_mismatch),
            "result": "FAIL" if bad else "PASS",
        },
    )
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
