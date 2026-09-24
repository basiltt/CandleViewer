"""Q4 - config fuzzer for LIVELOCK across BOTH engines, 30 s watchdog.

Generates configs from the shapes the round-6 fixes were written for:
nested invoke cycles, `always` cycles, rollback + onDone re-arm, and
`sendTo` self-loops. Each config is run on `Interpreter` and
`SyncInterpreter`. Requirements:

  L1 no run exceeds the watchdog (a timeout IS the observed result and is
     reported as a livelock, with the config serialised for repro)
  L2 if the run does self-generated work at all, a trip must be
     OBSERVABLE -- `last_error` is `RunawayChainError`, or the receipt
     carries an error, or the run settles on its own
  L3 the two engines agree on whether a config trips

Watchdog implementation: each async case is `asyncio.wait_for`-bounded;
each SYNC case runs in a worker thread that the main thread abandons on
timeout (a sync livelock cannot be interrupted -- that is the point).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import random
import sys

from common import emit
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import RunawayChainError

N = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--n=")), 500))
WATCHDOG = float(
    next((a.split("=")[1] for a in sys.argv if a.startswith("--wd=")), 6.0)
)


def svc_ok(i, ctx, e):  # noqa: ANN001
    return {"v": 1}


async def svc_async(i, ctx, e):  # noqa: ANN001
    await asyncio.sleep(0)
    return {"v": 1}


def svc_boom(i, ctx, e):  # noqa: ANN001
    raise RuntimeError("boom")


def act(i, ctx, e, ad):  # noqa: ANN001
    ctx["n"] = ctx.get("n", 0) + 1


def act_boom(i, ctx, e, ad):  # noqa: ANN001
    ctx["n"] = ctx.get("n", 0) + 1
    raise RuntimeError("action boom")


LOGIC = dict(
    actions={"act": act, "act_boom": act_boom},
    services={"ok": svc_ok, "aok": svc_async, "boom": svc_boom},
)


def gen(rng: random.Random, i: int) -> dict:
    mid = f"f{i}"
    shape = rng.choice(["always_cycle", "invoke_cycle", "rollback", "sendto"])
    if shape == "always_cycle":
        states = {
            "a": {"always": {"target": "b", "actions": ["act"]}},
            "b": {"always": {"target": "a", "actions": ["act"]}},
        }
        initial = rng.choice(["a", "b"])
    elif shape == "invoke_cycle":
        src = rng.choice(["ok", "aok"])
        states = {
            "ver": {
                "invoke": {
                    "src": src,
                    "onDone": {"target": "arm", "actions": ["act"]},
                    "onError": {"target": "arm"},
                }
            },
            "arm": {"always": {"target": "ver", "actions": ["act"]}},
        }
        initial = "ver"
    elif shape == "rollback":
        states = {
            "ver": {
                "invoke": {
                    "src": rng.choice(["ok", "boom"]),
                    "onDone": {"target": "back", "actions": ["act_boom"]},
                    "onError": {"target": "back", "actions": ["act"]},
                }
            },
            "back": {"always": {"target": "ver", "actions": ["act"]}},
        }
        initial = "ver"
    else:  # sendto self-loop
        states = {
            "a": {
                "entry": ["act"],
                "on": {
                    "TICK": {
                        "target": "a",
                        "actions": [
                            {"type": "send", "event": "TICK", "to": mid}
                        ],
                    }
                },
            }
        }
        initial = "a"
    return {
        "id": mid,
        "initial": initial,
        "context": {"n": 0},
        "shape": shape,
        "maxIterations": rng.choice([50, 200, 1000]),
        "states": states,
    }


def mk(cfg: dict):
    c = {k: v for k, v in cfg.items() if k != "shape"}
    return create_machine(c, logic=MachineLogic(**LOGIC))


async def run_async(cfg: dict) -> dict:
    itp = Interpreter(mk(cfg))
    try:
        await asyncio.wait_for(itp.start(), WATCHDOG)
    except asyncio.TimeoutError:
        return {"outcome": "LIVELOCK_IN_START"}
    await asyncio.sleep(0.05)
    trip_at_start = isinstance(itp.last_error, RunawayChainError)
    err = None
    try:
        r = await asyncio.wait_for(itp.send("TICK", wait=True), WATCHDOG)
        err = repr(r.error)
        outcome = "settled"
    except asyncio.TimeoutError:
        outcome = "LIVELOCK"
    except Exception as exc:  # noqa: BLE001
        err = repr(exc)
        outcome = "raised"
    trip = isinstance(itp.last_error, RunawayChainError) or trip_at_start
    try:
        await asyncio.wait_for(itp.stop(), 5)
    except Exception:  # noqa: BLE001
        outcome = outcome + "+STOP_HUNG"
    return {"outcome": outcome, "trip": trip,
            "trip_at_start": trip_at_start, "receipt_error": err}


def run_sync_body(cfg: dict) -> dict:
    itp = SyncInterpreter(mk(cfg))
    itp.start()
    trip_at_start = isinstance(itp.last_error, RunawayChainError)
    err = None
    try:
        itp.send("TICK")
        outcome = "settled"
    except Exception as exc:  # noqa: BLE001
        err = repr(exc)
        outcome = "raised"
    trip = isinstance(itp.last_error, RunawayChainError) or trip_at_start
    try:
        itp.stop()
    except Exception:  # noqa: BLE001
        pass
    return {"outcome": outcome, "trip": trip,
            "trip_at_start": trip_at_start, "receipt_error": err}


def run_sync(cfg: dict, pool) -> dict:  # noqa: ANN001
    fut = pool.submit(run_sync_body, cfg)
    try:
        return fut.result(timeout=WATCHDOG)
    except concurrent.futures.TimeoutError:
        return {"outcome": "LIVELOCK", "trip": None, "receipt_error": None}
    except Exception as exc:  # noqa: BLE001
        return {"outcome": "raised", "trip": None,
                "receipt_error": repr(exc)}


async def main() -> int:
    rng = random.Random(70707)
    by_shape: dict = {}
    livelocks: list = []
    disagree: list = []
    unobservable: list = []
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    for i in range(N):
        cfg = gen(rng, i)
        shape = cfg["shape"]
        a = await run_async(cfg)
        s = run_sync(cfg, pool)
        rec = by_shape.setdefault(
            shape,
            {"n": 0, "async": {}, "sync": {}, "trip_async": 0,
             "trip_sync": 0},
        )
        rec["n"] += 1
        rec["async"][a["outcome"]] = rec["async"].get(a["outcome"], 0) + 1
        rec["sync"][s["outcome"]] = rec["sync"].get(s["outcome"], 0) + 1
        rec["trip_async"] += int(bool(a.get("trip")))
        rec["trip_sync"] += int(bool(s.get("trip")))
        if "LIVELOCK" in a["outcome"] or "LIVELOCK" in s["outcome"]:
            if len(livelocks) < 20:
                livelocks.append({"cfg": cfg, "async": a, "sync": s})
        elif bool(a.get("trip")) != bool(s.get("trip")):
            if len(disagree) < 20:
                disagree.append({"cfg": cfg, "async": a, "sync": s})
        # L2: a cyclic shape that settled with no trip and no error is
        # only fine for `sendto` (external event, bounded by design).
        if (
            shape in ("always_cycle", "invoke_cycle", "rollback")
            and a["outcome"] == "settled"
            and not a.get("trip")
            and a.get("receipt_error") in ("None", None)
            and len(unobservable) < 20
        ):
            unobservable.append({"cfg": cfg, "async": a})
    pool.shutdown(wait=False, cancel_futures=True)
    ok = not livelocks and not disagree
    emit(
        "q4_livelock_fuzz",
        {
            "configs": N,
            "watchdog_s": WATCHDOG,
            "REDUCED": "watchdog 6 s (brief says 30 s); every livelock "
                       "observed here hangs indefinitely, and the 120 s "
                       "per-script bound does not fit 500 x 30 s",
            "by_shape": by_shape,
            "L1_livelocks": livelocks[:10],
            "L1_livelock_count": len(livelocks),
            "L3_engine_trip_disagreements": disagree[:10],
            "L3_disagreement_count": len(disagree),
            "L2_cycle_settled_with_no_observable_trip": unobservable[:5],
            "L2_count": len(unobservable),
            "result": "PASS" if ok else "FAIL",
        },
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
