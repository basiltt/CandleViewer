"""R1 - the round-7 defects re-run on BOTH service spellings.

Round 7's D7-concurrency-1 (invoke-cycle machine never drains its inbox)
was found with a plain `def` service. #179 changed which lane completions
travel on, so the shape must be re-measured for `def` AND `async def`.

Also re-runs D7-concurrency-2 (torn blob from `on_action_execute`) on both
spellings and both engines.

Bounded: each storm 6 s, probe deadline 5 s.
"""

from __future__ import annotations

import asyncio
import random
import time

from common2 import KINDS, Interpreter, MachineLogic, create_machine, emit, make_service
from xstate_statemachine.exceptions import RunawayChainError

LAPS = {"n": 0}


def act(i, ctx, e, ad):  # noqa: ANN001
    LAPS["n"] += 1


def cfg(shape: str) -> dict:
    if shape == "invoke_pingpong":
        states = {
            "ver": {
                "invoke": {
                    "src": "exec",
                    "onDone": {"target": "arm", "actions": ["act"]},
                    "onError": {"target": "arm"},
                }
            },
            "arm": {
                "always": {"target": "ver", "actions": ["act"]},
                "on": {"PING": {"actions": ["act"]}},
            },
        }
    elif shape == "rollback_ondone":
        states = {
            "ver": {
                "invoke": {
                    "src": "exec",
                    "onDone": {"target": "back", "actions": ["act"]},
                    "onError": {"target": "back"},
                },
                "on": {"PING": {"actions": ["act"]}},
            },
            "back": {
                "always": {"target": "ver", "actions": ["act"]},
                "on": {"PING": {"actions": ["act"]}},
            },
        }
    else:  # always_cycle control
        states = {
            "ver": {
                "always": {"target": "arm", "actions": ["act"]},
                "on": {"PING": {"actions": ["act"]}},
            },
            "arm": {
                "always": {"target": "ver", "actions": ["act"]},
                "on": {"PING": {"actions": ["act"]}},
            },
        }
    return {
        "id": "r1",
        "initial": "ver",
        "context": {"n": 0},
        "maxIterations": 50,
        "states": states,
    }


def mk(shape: str, kind: str):
    return create_machine(
        cfg(shape),
        logic=MachineLogic(
            actions={"act": act},
            services={"exec": make_service(kind, delay=0.001)},
        ),
    )


async def storm(shape: str, kind: str, n: int, seconds: float) -> dict:
    LAPS["n"] = 0
    itps = [Interpreter(mk(shape, kind), service_pool_size=2) for _ in range(n)]
    await asyncio.gather(*(i.start() for i in itps))
    t0 = time.perf_counter()
    sent = 0
    trace = []
    while time.perf_counter() - t0 < seconds:
        for _ in range(200):
            try:
                random.choice(itps).send_threadsafe("PING")
                sent += 1
            except Exception:  # noqa: BLE001
                pass
        await asyncio.sleep(0.05)
        if len(trace) < 12:
            trace.append(sum(i.queue_depth for i in itps))

    async def probe(i):  # noqa: ANN001
        try:
            await asyncio.wait_for(i.send("PING", wait=True), 5)
            return 0
        except asyncio.TimeoutError:
            return 1
        except Exception:  # noqa: BLE001
            return 0

    wedged = sum(await asyncio.gather(*(probe(i) for i in itps)))
    backlog = sum(i.queue_depth for i in itps)
    tripped = sum(1 for i in itps if isinstance(i.last_error, RunawayChainError))
    try:
        await asyncio.wait_for(asyncio.gather(*(i.stop() for i in itps)), 30)
        stopped = "ok"
    except asyncio.TimeoutError:
        stopped = "HUNG"
    return {
        "shape": shape,
        "service_kind": kind,
        "machines": n,
        "events_sent": sent,
        "backlog_trace": trace,
        "final_backlog": backlog,
        "not_answering_in_5s": wedged,
        "tripped": tripped,
        "statuses": sorted({i.status for i in itps}),
        "laps": LAPS["n"],
        "stop": stopped,
    }


async def main() -> int:
    rows = []
    for kind in KINDS:
        for shape in ("always_cycle", "invoke_pingpong", "rollback_ondone"):
            rows.append(await storm(shape, kind, 10, 6))
    bad = [r for r in rows if r["not_answering_in_5s"]]
    emit(
        "r1_d7_1_both_service_kinds",
        {
            "rows": rows,
            "wedged_rows": [
                (r["shape"], r["service_kind"], r["not_answering_in_5s"],
                 r["final_backlog"])
                for r in bad
            ],
            "result": "FAIL" if bad else "PASS",
        },
    )
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
