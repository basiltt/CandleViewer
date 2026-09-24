"""Q5 - determinism, sentinel aliasing, hash-seed sweep.

D1 50x identical traces on BOTH engines for the same machine + input,
   including the lap count at which a self-generated cycle trips.
D2 PR #165/#176 perf work introduced module-level SHARED init/exit
   sentinel Events (`_INIT_EVENT`, `_EXIT_EVENT` in base_interpreter).
   Two machines running concurrently see the SAME object. Attack: mutate
   what is reachable from the sentinel in one machine's action and check
   the other machine's view -- any cross-talk is a defect.
D3 PYTHONHASHSEED sweep is driven by the sibling script
   `q5b_hashseed_sweep.sh`-style loop in q5b_hashseed_sweep.py.
"""

from __future__ import annotations

import asyncio

from common import emit
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import RunawayChainError

CFG = {
    "id": "det",
    "initial": "par",
    "context": {"n": 0},
    "states": {
        "par": {
            "type": "parallel",
            "states": {
                "l": {
                    "initial": "a",
                    "states": {
                        "a": {"entry": ["act"], "on": {"S": "b"}},
                        "b": {"entry": ["act"], "on": {"S": "a"}},
                    },
                },
                "r": {
                    "initial": "x",
                    "states": {
                        "x": {"exit": ["act"], "on": {"S": "y"}},
                        "y": {"entry": ["act"], "on": {"S": "x"}},
                    },
                },
            },
            "on": {"SPIN": {"target": "#det.cycle"}},
        },
        "cycle": {"always": {"target": "cycle2", "actions": ["lap"]}},
        "cycle2": {"always": {"target": "cycle", "actions": ["lap"]}},
    },
}

LAPS = {"n": 0}


def act(i, ctx, e, ad):  # noqa: ANN001
    ctx["n"] = ctx.get("n", 0) + 1


def lap(i, ctx, e, ad):  # noqa: ANN001
    LAPS["n"] += 1


def mk():
    cfg = dict(CFG)
    cfg["maxIterations"] = 100
    return create_machine(
        cfg, logic=MachineLogic(actions={"act": act, "lap": lap})
    )


class Trace(PluginBase):
    def __init__(self) -> None:
        self.t: list = []

    def on_transition(self, i, f, t, tr) -> None:  # noqa: ANN001
        self.t.append(tuple(sorted(s.id for s in t)))


EVENTS = ["S", "S", "S", "SPIN"]


async def trace_async() -> tuple:
    LAPS["n"] = 0
    itp = Interpreter(mk())
    tr = Trace()
    itp.use(tr)
    await itp.start()
    for e in EVENTS:
        try:
            await asyncio.wait_for(itp.send(e, wait=True), 10)
        except Exception:  # noqa: BLE001
            pass
    await asyncio.sleep(0.15)
    trip = isinstance(itp.last_error, RunawayChainError)
    laps = LAPS["n"]
    n = itp.context["n"]
    await itp.stop()
    return (tuple(tr.t), laps, trip, n)


def trace_sync() -> tuple:
    LAPS["n"] = 0
    itp = SyncInterpreter(mk())
    tr = Trace()
    itp.use(tr)
    itp.start()
    for e in EVENTS:
        try:
            itp.send(e)
        except Exception:  # noqa: BLE001
            pass
    trip = isinstance(itp.last_error, RunawayChainError)
    laps = LAPS["n"]
    n = itp.context["n"]
    itp.stop()
    return (tuple(tr.t), laps, trip, n)


async def d1_determinism(runs: int) -> dict:
    a = [await trace_async() for _ in range(runs)]
    s = [trace_sync() for _ in range(runs)]
    a_uniq = {x[0] for x in a}
    s_uniq = {x[0] for x in s}
    a_laps = {x[1] for x in a}
    s_laps = {x[1] for x in s}
    return {
        "runs": runs,
        "async_distinct_traces": len(a_uniq),
        "sync_distinct_traces": len(s_uniq),
        "async_distinct_lap_counts": sorted(a_laps),
        "sync_distinct_lap_counts": sorted(s_laps),
        "async_trip_values": sorted({x[2] for x in a}),
        "sync_trip_values": sorted({x[2] for x in s}),
        "async_context_n": sorted({x[3] for x in a}),
        "sync_context_n": sorted({x[3] for x in s}),
        "engines_same_trace": a_uniq == s_uniq,
        "engines_same_lap_count": a_laps == s_laps,
        "deterministic": len(a_uniq) == 1 and len(s_uniq) == 1
        and len(a_laps) == 1 and len(s_laps) == 1,
    }


SEEN = {"rows": []}

SENT_CFG = {
    "id": "sent",
    "initial": "a",
    "context": {"tag": None},
    "states": {"a": {"entry": ["mark"]}},
}


def make_mark(tag: str, mutate: bool):
    def mark(i, ctx, e, ad):  # noqa: ANN001
        SEEN["rows"].append(
            {
                "machine": tag,
                "event_type": getattr(e, "type", None),
                "event_id": id(e),
                "payload_seen": dict(getattr(e, "payload", {}) or {}),
            }
        )
        if mutate:
            try:
                e.payload["POISON"] = tag
            except Exception:  # noqa: BLE001
                SEEN["rows"][-1]["mutate"] = "refused"
    return mark


async def d2_sentinel_aliasing() -> dict:
    """Two machines; the first mutates the init sentinel's payload, the
    second must not see it."""
    from xstate_statemachine import base_interpreter as _bi

    sentinel_id = id(getattr(_bi, "_INIT_EVENT", None))
    SEEN["rows"].clear()
    m1 = create_machine(
        dict(SENT_CFG, id="s1"),
        logic=MachineLogic(actions={"mark": make_mark("s1", True)}),
    )
    m2 = create_machine(
        dict(SENT_CFG, id="s2"),
        logic=MachineLogic(actions={"mark": make_mark("s2", False)}),
    )
    i1 = Interpreter(m1)
    i2 = Interpreter(m2)
    await i1.start()
    await i2.start()
    await asyncio.sleep(0.05)
    await i1.stop()
    await i2.stop()
    rows = list(SEEN["rows"])
    s2 = [r for r in rows if r["machine"] == "s2"]
    cross_talk = any("POISON" in r["payload_seen"] for r in s2)
    shared_object = (
        len({r["event_id"] for r in rows}) == 1 and len(rows) > 1
    )
    return {
        "module_init_sentinel_id": sentinel_id,
        "rows": rows,
        "same_event_object_across_machines": shared_object,
        "cross_talk_observed": cross_talk,
        "ok": not cross_talk,
    }


async def main() -> int:
    d1 = await d1_determinism(50)
    d2 = await d2_sentinel_aliasing()
    ok = d1["deterministic"] and d1["engines_same_lap_count"] and d2["ok"]
    emit(
        "q5_determinism_sentinel",
        {
            "D1_determinism_50x": d1,
            "D2_sentinel_aliasing": d2,
            "result": "PASS" if ok else "FAIL",
        },
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
