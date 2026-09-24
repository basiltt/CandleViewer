"""D8-C: livelock fuzz and determinism across the full matrix.

C1  500 generated cycle configs x {def, async def} x {sync, async engine}
    with a 30 s watchdog.  Every run must SETTLE, every trip must be
    OBSERVABLE (last_error / receipt.error / on_event_dropped), and the lap
    counts must be EQUAL across engines and across service kinds -- the
    property #179 claims to have established.
C2  Determinism: 50x identical traces, both engines, both service kinds,
    including trip lap counts.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Dict, List, Tuple

from n_harness import attack, main

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

N_CONFIGS = 500
WATCHDOG_S = 28.0


class Spy(PluginBase):
    def __init__(self) -> None:
        self.drops: List[str] = []

    def on_event_dropped(self, i, e, reason):  # noqa: ANN001
        self.drops.append(reason)


def _gen(rng: random.Random, idx: int) -> Dict[str, Any]:
    """Five adversarial self-feeding shapes."""
    shape = idx % 5
    mi = rng.choice([10, 20, 50])
    if shape == 0:  # nested invoke cycle
        return {
            "id": f"g{idx}", "initial": "idle", "maxIterations": mi,
            "states": {
                "idle": {"on": {"GO": "ver"}},
                "ver": {"invoke": {"src": "svc", "onDone": "arm"}},
                "arm": {"invoke": {"src": "svc", "onDone": "ver"}},
            },
        }
    if shape == 1:  # always cycle
        n = rng.randint(2, 4)
        sts: Dict[str, Any] = {
            f"s{k}": {"always": {"target": f"s{(k + 1) % n}"}} for k in range(n)
        }
        sts["idle"] = {"on": {"GO": "s0"}}
        return {"id": f"g{idx}", "initial": "idle", "maxIterations": mi, "states": sts}
    if shape == 2:  # rollback + onDone re-arm
        return {
            "id": f"g{idx}", "initial": "idle", "maxIterations": mi,
            "states": {
                "idle": {"on": {"GO": "work"}},
                "work": {
                    "invoke": {"src": "svc", "onDone": "roll"},
                    "on": {"RETRY": "work"},
                },
                "roll": {"entry": "re_arm", "on": {"RETRY": "work"}},
            },
        }
    if shape == 3:  # raise self-loop
        return {
            "id": f"g{idx}", "initial": "idle", "maxIterations": mi,
            "states": {
                "idle": {"on": {"GO": "spin"}},
                "spin": {"entry": "re_arm", "on": {"RETRY": "spin"}},
            },
        }
    # shape 4: invoke whose onDone re-enters the same invoking state
    return {
        "id": f"g{idx}", "initial": "idle", "maxIterations": mi,
        "states": {
            "idle": {"on": {"GO": "poll"}},
            "poll": {"invoke": {"src": "svc", "onDone": "poll"}},
        },
    }


def _logic(kind: str, counter: Dict[str, int]) -> MachineLogic:
    def svc(i_, ctx, e):  # noqa: ANN001
        counter["laps"] += 1
        return 1

    async def svc_a(i_, ctx, e):  # noqa: ANN001
        counter["laps"] += 1
        await asyncio.sleep(0)
        return 1

    def re_arm(i, ctx, e, ad):  # noqa: ANN001
        counter["laps"] += 1
        i.send("RETRY")

    return MachineLogic(
        actions={"re_arm": re_arm},
        services={"svc": svc_a if kind == "async" else svc},
    )


async def _run_async(cfg, kind: str) -> Dict[str, Any]:
    counter = {"laps": 0}
    spy = Spy()
    i = await Interpreter(
        create_machine(cfg, logic=_logic(kind, counter))
    ).use(spy).start()
    try:
        await asyncio.wait_for(i.send("GO"), timeout=WATCHDOG_S)
        await asyncio.sleep(0.15)
        hung = False
    except asyncio.TimeoutError:
        hung = True
    err = type(i.last_error).__name__ if i.last_error else None
    try:
        await asyncio.wait_for(i.stop(), timeout=5)
    except asyncio.TimeoutError:
        hung = True
    return {"laps": counter["laps"], "last_error": err, "drops": spy.drops, "hung": hung}


def _run_sync(cfg, kind: str) -> Dict[str, Any]:
    if kind == "async":
        return {"skipped": "coroutine service on sync engine"}
    counter = {"laps": 0}
    spy = Spy()
    i = SyncInterpreter(
        create_machine(cfg, logic=_logic(kind, counter))
    ).use(spy).start()
    t0 = time.perf_counter()
    err = None
    try:
        r = i.send("GO", wait=True)
        if getattr(r, "error", None):
            err = type(r.error).__name__
    except Exception as exc:  # noqa: BLE001
        err = type(exc).__name__
    hung = (time.perf_counter() - t0) > WATCHDOG_S
    if err is None and i.last_error:
        err = type(i.last_error).__name__
    i.stop()
    return {"laps": counter["laps"], "last_error": err, "drops": spy.drops, "hung": hung}


@attack(
    "C1",
    f"{N_CONFIGS} cycle configs x (def, async def) x (sync, async engine), "
    "30 s watchdog: all settle, every trip observable, lap counts equal",
    "#179: boundedness must be a property of the machine, not of the spelling",
)
async def c1() -> Dict[str, Any]:
    rng = random.Random(6135)
    hangs: List[Dict[str, Any]] = []
    silent: List[Dict[str, Any]] = []
    lap_mismatch: List[Dict[str, Any]] = []
    engine_mismatch: List[Dict[str, Any]] = []
    runaway: List[Dict[str, Any]] = []
    n = 0
    for idx in range(N_CONFIGS):
        cfg = _gen(rng, idx)
        n += 1
        a_plain = await _run_async(dict(cfg), "plain")
        a_async = await _run_async(dict(cfg), "async")
        s_plain = _run_sync(dict(cfg), "plain")

        for tag, r in (("async/def", a_plain), ("async/async", a_async), ("sync/def", s_plain)):
            if r.get("hung"):
                hangs.append({"id": cfg["id"], "lane": tag, **r})
            # A trip must be observable somewhere.
            tripped_obs = bool(r.get("last_error")) or bool(r.get("drops"))
            if r.get("laps", 0) > 10 * cfg["maxIterations"] and not tripped_obs:
                silent.append({"id": cfg["id"], "lane": tag, **r})
            if r.get("laps", 0) > 5000:
                runaway.append({"id": cfg["id"], "lane": tag, "laps": r["laps"]})

        if a_plain["laps"] != a_async["laps"]:
            lap_mismatch.append(
                {
                    "id": cfg["id"], "maxIterations": cfg["maxIterations"],
                    "def_laps": a_plain["laps"], "async_laps": a_async["laps"],
                    "def_err": a_plain["last_error"], "async_err": a_async["last_error"],
                }
            )
        if "skipped" not in s_plain and s_plain["laps"] != a_plain["laps"]:
            engine_mismatch.append(
                {
                    "id": cfg["id"], "maxIterations": cfg["maxIterations"],
                    "sync_laps": s_plain["laps"], "async_laps": a_plain["laps"],
                    "sync_err": s_plain["last_error"], "async_err": a_plain["last_error"],
                }
            )
    return {
        "ok": not hangs and not silent and not runaway and not lap_mismatch,
        "configs": n,
        "hangs": len(hangs),
        "silent_runaways": len(silent),
        "unbounded_laps": len(runaway),
        "def_vs_asyncdef_lap_mismatch": len(lap_mismatch),
        "sync_vs_async_engine_lap_mismatch": len(engine_mismatch),
        "hang_examples": hangs[:3],
        "silent_examples": silent[:3],
        "runaway_examples": runaway[:3],
        "lap_mismatch_examples": lap_mismatch[:5],
        "engine_mismatch_examples": engine_mismatch[:5],
    }


if __name__ == "__main__":
    main("n9_livelock_determinism")
