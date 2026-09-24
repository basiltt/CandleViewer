"""P1b @cec108b -- minimal repro/characterisation of the #116/#149 ordering
window seen by p1 v1 (158/200 machines saw `done.invoke` before an event
queued immediately after `start()` returned; 42 saw the event first).

Q1  After `await interp.start()`, has the plain-def service already
    completed (is the machine in `ok`)?  #116 + #149 say the ENTERING
    MACROSTEP awaits the result, so the initial macrostep -- which
    `start()` drives -- should include it.
Q2  With a service duration sweep, how often does an event sent right
    after `start()` overtake `done.invoke`?
Q3  Sync-engine control: same machine, same question.
"""

from __future__ import annotations

import asyncio
import threading
import time

from common import emit
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

CFG = {
    "id": "ord",
    "initial": "run",
    "context": {"seen": []},
    "states": {
        "run": {
            "invoke": {
                "id": "job",
                "src": "plain",
                "onDone": {"target": "ok", "actions": ["keep"]},
            },
            "on": {"RACE": {"actions": ["mark"]}},
        },
        "ok": {"type": "final"},
    },
}


def keep(i, ctx, e, a):  # noqa: ANN001
    ctx["seen"].append("done")


def mark(i, ctx, e, a):  # noqa: ANN001
    ctx["seen"].append("race")


def mk(sleep_s: float):
    def plain(i, ctx, e):  # noqa: ANN001
        if sleep_s:
            time.sleep(sleep_s)
        return {"tid": threading.get_ident()}

    return create_machine(
        CFG,
        logic=MachineLogic(
            actions={"keep": keep, "mark": mark}, services={"plain": plain}
        ),
    )


async def q1(sleep_s: float) -> dict:
    i = Interpreter(mk(sleep_s))
    await i.start()
    states_right_after_start = sorted(i.current_state_ids)
    seen_right_after_start = list(i.context["seen"])
    i.send("RACE")
    await asyncio.wait_for(i.wait_done(), 5)
    order = list(i.context["seen"])
    await i.stop()
    return {
        "service_sleep_s": sleep_s,
        "states_after_start": states_right_after_start,
        "seen_after_start": seen_right_after_start,
        "final_order": order,
        "done_first": order[:1] == ["done"],
    }


async def q2(sleep_s: float, trials: int = 40) -> dict:
    done_first = 0
    for _ in range(trials):
        r = await q1(sleep_s)
        done_first += 1 if r["done_first"] else 0
    return {
        "service_sleep_s": sleep_s,
        "trials": trials,
        "done_first": done_first,
        "race_first": trials - done_first,
    }


def q3_sync(sleep_s: float) -> dict:
    i = SyncInterpreter(mk(sleep_s))
    i.start()
    states = sorted(i.current_state_ids)
    seen = list(i.context["seen"])
    i.send("RACE")
    order = list(i.context["seen"])
    i.stop()
    return {
        "service_sleep_s": sleep_s,
        "states_after_start": states,
        "seen_after_start": seen,
        "final_order": order,
        "done_first": order[:1] == ["done"],
    }


async def main() -> int:
    res = {
        "q1_async_single_0ms": await q1(0.0),
        "q1_async_single_20ms": await q1(0.02),
        "q2_sweep_0ms": await q2(0.0),
        "q2_sweep_5ms": await q2(0.005, 20),
        "q3_sync_0ms": q3_sync(0.0),
        "q3_sync_20ms": q3_sync(0.02),
    }
    res["async_completes_inside_start"] = (
        res["q1_async_single_20ms"]["seen_after_start"] == ["done"]
    )
    res["sync_completes_inside_start"] = (
        res["q3_sync_20ms"]["seen_after_start"] == ["done"]
    )
    res["engines_agree_on_start_completion"] = (
        res["async_completes_inside_start"] == res["sync_completes_inside_start"]
    )
    res["result"] = (
        "PASS" if res["engines_agree_on_start_completion"] else "FAIL"
    )
    emit("p1b_invoke_ordering", res)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
