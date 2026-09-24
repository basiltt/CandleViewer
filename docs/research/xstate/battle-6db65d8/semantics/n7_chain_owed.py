"""D8-A: attacks on the #179 `_chain_owed` debt counter and the #180
external-priority-lane exemption.

A1  100 concurrent NEVER-completing coroutine services + stop(): does the
    debt leak, does stop() hang, are the tasks cancelled?
A2  External `send(priority=True)` at high rate DURING a self-generated
    chain, both service kinds: ZERO may be dropped as `chain_budget`.
A3  `start(children_timeout=)` with 50 slow children: bounded, warned,
    children still register afterwards.
A4  Debt accounting under interleaving: a long service armed by step N
    must not keep step N+k's unrelated chain open, and a genuine
    `a -> done -> b -> done -> a` cycle must still trip, for BOTH kinds.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Dict, List

from n_harness import attack, main

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)


class Drops(PluginBase):
    def __init__(self) -> None:
        self.reasons: List[str] = []

    def on_event_dropped(self, i, e, reason):  # noqa: ANN001
        self.reasons.append(reason)


def _owed(i: Interpreter) -> int:
    return getattr(i, "_chain_owed", -1)


HANG = {
    "id": "hang",
    "initial": "idle",
    "states": {
        "idle": {"on": {"GO": "busy"}},
        "busy": {"invoke": {"src": "never", "onDone": "idle"}},
    },
}


@attack(
    "A1",
    "100 concurrent never-completing coroutine services then stop(): "
    "_chain_owed does not leak, tasks are cancelled, stop() is prompt",
    "#179 debt counter leak / hang under cancellation",
)
async def a1() -> Dict[str, Any]:
    started = 0
    lock = threading.Lock()

    async def never(i_, ctx, e):  # noqa: ANN001
        nonlocal started
        with lock:
            started += 1
        await asyncio.sleep(3600)

    ints: List[Interpreter] = []
    for _ in range(100):
        m = create_machine(HANG, logic=MachineLogic(services={"never": never}))
        ints.append(await Interpreter(m).start())
    await asyncio.gather(*(i.send("GO") for i in ints))
    await asyncio.sleep(0.4)
    owed_mid = [_owed(i) for i in ints]
    tasks_before = len(asyncio.all_tasks())

    t0 = time.perf_counter()
    await asyncio.gather(*(i.stop() for i in ints))
    stop_s = time.perf_counter() - t0
    await asyncio.sleep(0.2)
    owed_after = [_owed(i) for i in ints]
    leftover = [
        t
        for t in asyncio.all_tasks()
        if t is not asyncio.current_task() and not t.done()
    ]

    return {
        "ok": (
            started == 100
            and stop_s < 5.0
            and max(owed_after) <= 1
            and len(leftover) == 0
        ),
        "services_started": started,
        "owed_mid_max": max(owed_mid),
        "owed_after_max": max(owed_after),
        "owed_after_nonzero": sum(1 for v in owed_after if v),
        "stop_seconds": round(stop_s, 3),
        "tasks_before_stop": tasks_before,
        "tasks_left_running": len(leftover),
    }


PINGPONG = {
    "id": "pp",
    "initial": "idle",
    "states": {
        "idle": {"on": {"GO": "a", "EXT": {"actions": "count_ext"}}},
        "a": {
            "invoke": {"src": "svc", "onDone": "b"},
            "on": {"EXT": {"actions": "count_ext"}},
        },
        "b": {
            "invoke": {"src": "svc", "onDone": "a"},
            "on": {"EXT": {"actions": "count_ext"}},
        },
    },
}


async def _ext_flood(kind: str, n_ext: int) -> Dict[str, Any]:
    """Fire `n_ext` EXTERNAL priority sends during a self-generated chain."""
    seen = {"n": 0}

    def count_ext(i_, ctx, e, ad):  # noqa: ANN001
        seen["n"] += 1

    def svc_sync(i_, ctx, e):  # noqa: ANN001
        return 1

    async def svc_async(i_, ctx, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return 1

    logic = MachineLogic(
        actions={"count_ext": count_ext},
        services={"svc": svc_async if kind == "async" else svc_sync},
    )
    cfg = dict(PINGPONG)
    cfg["maxIterations"] = 50
    m = create_machine(cfg, logic=logic)
    drops = Drops()
    i = await Interpreter(m).use(drops).start()
    await i.send("GO")  # ignites the (bounded) self-generated cycle

    accepted = 0
    refused = 0
    for _ in range(n_ext):
        try:
            await i.send("EXT", priority=True)
            accepted += 1
        except Exception:  # noqa: BLE001
            refused += 1
        await asyncio.sleep(0)
    await asyncio.sleep(0.3)
    chain_drops = sum(1 for r in drops.reasons if r == "chain_budget")
    await i.stop()
    return {
        "kind": kind,
        "sent": n_ext,
        "accepted": accepted,
        "refused_at_call": refused,
        "actions_fired": seen["n"],
        "chain_budget_drops": chain_drops,
        "other_drops": sorted(set(drops.reasons) - {"chain_budget"}),
        "last_error": type(i.last_error).__name__ if i.last_error else None,
    }


@attack(
    "A2",
    "External send(priority=True) x2000 DURING a self-generated invoke chain: "
    "ZERO dropped as chain_budget, for def AND async def services",
    "#180 provenance-based charging must hold on the coroutine lane too",
)
async def a2() -> Dict[str, Any]:
    res = [await _ext_flood(k, 2000) for k in ("plain", "async")]
    ok = all(
        r["chain_budget_drops"] == 0 and r["actions_fired"] == r["sent"]
        for r in res
    )
    return {"ok": ok, "runs": res}


def _slow_child(delay: float) -> Dict[str, Any]:
    return {
        "id": "kid",
        "initial": "boot",
        "states": {
            "boot": {"entry": "sleep_a_bit", "on": {"DONE": "up"}},
            "up": {},
        },
    }


@attack(
    "A3",
    "start(children_timeout=0.3) with 50 slow children: bounded wait, WARNING "
    "logged, machine running, children register afterwards",
    "#181 children_timeout under fan-out",
)
async def a3() -> Dict[str, Any]:
    async def sleep_a_bit(i_, ctx, e, ad):  # noqa: ANN001
        await asyncio.sleep(1.0)

    kid = create_machine(
        _slow_child(1.0), logic=MachineLogic(actions={"sleep_a_bit": sleep_a_bit})
    )
    parent = {
        "id": "par",
        "initial": "up",
        "states": {
            "up": {
                "invoke": [
                    {"src": "kid", "id": f"k{n}"} for n in range(50)
                ]
            }
        },
    }
    m = create_machine(parent, logic=MachineLogic(services={"kid": kid}))
    i = Interpreter(m)

    recs: List[logging.LogRecord] = []

    class Cap(logging.Handler):
        def emit(self, r):  # noqa: ANN001
            recs.append(r)

    lg = logging.getLogger("xstate_statemachine")
    prev_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    h = Cap(level=logging.WARNING)
    lg.addHandler(h)
    lg.setLevel(logging.WARNING)
    try:
        t0 = time.perf_counter()
        await i.start(children_timeout=0.3)
        elapsed = time.perf_counter() - t0
    finally:
        lg.removeHandler(h)
        logging.disable(prev_disable)

    status_now = i.status
    actors_now = len(getattr(i, "_actors", {}) or {})
    await asyncio.sleep(1.6)
    actors_later = len(getattr(i, "_actors", {}) or {})
    warned = [r.getMessage()[:120] for r in recs if r.levelno >= logging.WARNING]
    await i.stop()
    return {
        "ok": (
            elapsed < 1.0
            and status_now == "running"
            and len(warned) >= 1
            and actors_later == 50
        ),
        "start_seconds": round(elapsed, 3),
        "status_after_start": status_now,
        "actors_at_return": actors_now,
        "actors_after_bringup": actors_later,
        "warnings": warned[:3],
        "n_warnings": len(warned),
    }


CYCLE = {
    "id": "cy",
    "initial": "idle",
    "maxIterations": 20,
    "states": {
        "idle": {"on": {"GO": "a"}},
        "a": {"invoke": {"src": "svc", "onDone": "b"}},
        "b": {"invoke": {"src": "svc", "onDone": "a"}},
    },
}
ONE_DEEP = {
    "id": "od",
    "initial": "idle",
    "maxIterations": 20,
    "states": {
        "idle": {"on": {"GO": "work"}},
        "work": {"invoke": {"src": "svc", "onDone": "idle"}},
    },
}


async def _laps(cfg, kind: str, n_sends: int = 1, delay: float = 0.0):
    calls = {"n": 0}

    def svc_sync(i_, ctx, e):  # noqa: ANN001
        calls["n"] += 1
        if delay:
            time.sleep(delay)
        return 1

    async def svc_async(i_, ctx, e):  # noqa: ANN001
        calls["n"] += 1
        await asyncio.sleep(delay)
        return 1

    m = create_machine(
        cfg,
        logic=MachineLogic(services={"svc": svc_async if kind == "async" else svc_sync}),
    )
    i = await Interpreter(m).start()
    for _ in range(n_sends):
        await i.send("GO")
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.6)
    err = type(i.last_error).__name__ if i.last_error else None
    owed = _owed(i)
    await i.stop()
    return {"kind": kind, "svc_calls": calls["n"], "last_error": err, "owed": owed}


@attack(
    "A4",
    "Debt accounting: a genuine invoke cycle TRIPS and 30 independent "
    "one-deep completions do NOT, identically for def and async def",
    "#179 _chain_owed must bound cycles without false-tripping honest traffic",
)
async def a4() -> Dict[str, Any]:
    cyc = [await _laps(CYCLE, k) for k in ("plain", "async")]
    od = [await _laps(ONE_DEEP, k, n_sends=30) for k in ("plain", "async")]
    trips = all(r["last_error"] == "RunawayChainError" for r in cyc)
    bounded = all(r["svc_calls"] < 200 for r in cyc)
    no_false = all(
        r["last_error"] is None and r["svc_calls"] == 30 for r in od
    )
    parity = cyc[0]["svc_calls"] == cyc[1]["svc_calls"]
    return {
        "ok": trips and bounded and no_false and parity,
        "cycle_trips": trips,
        "cycle_bounded": bounded,
        "one_deep_clean": no_false,
        "lap_parity_def_vs_async": parity,
        "cycle": cyc,
        "one_deep": od,
    }


if __name__ == "__main__":
    main("n7_chain_owed")
