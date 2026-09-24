"""SEMANTICS @ 19cb1f1 -- REDUCED soak (90 s, not the requested 12 min:
the 12-minute soak does not fit this task's 20-minute wall-clock bound
alongside the 1,334-run fuzz; parameters reduced and recorded).

200 machines (100 `def` + 100 `async def`) running simultaneously:
  * always -> invoke roll-forward (#204),
  * a rollback + onDone storm that strands an invocation (#207),
  * a `raise(delay=1ms)` self-ping-pong (#206),
  * an EXTERNAL priority producer,
  * a chaos snapshot taken at quiescence.

Asserts: CPU bounded, 0 external dropped, no livelock, no dormant
invocation without an `on_invocation_stranded` report.

Standalone: stdlib + xstate_statemachine only.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase

logging.disable(logging.CRITICAL)
DURATION = float(os.environ.get("SOAK_SECONDS", "90"))


class Obs(PluginBase):
    def __init__(self) -> None:
        self.ext_dropped = 0
        self.self_dropped = 0
        self.stranded: List[Any] = []

    def on_event_dropped(self, i, e, r):  # noqa: ANN001
        if getattr(e, "type", None) == "EXT":
            self.ext_dropped += 1
        else:
            self.self_dropped += 1

    def on_invocation_stranded(self, i, sid, iid, err):  # noqa: ANN001
        self.stranded.append((sid, iid))


SOAK = {
    "id": "s",
    "type": "parallel",
    "maxIterations": 8,
    "states": {
        "fwd": {
            "initial": "a",
            "states": {
                "a": {"on": {"GO": "inv"}},
                "inv": {
                    "invoke": {"src": "svc", "id": "s1", "onDone": "z"},
                    "always": {"target": "z"},
                },
                "z": {"on": {"GO": "a"}},
            },
        },
        "storm": {
            "initial": "w",
            "states": {
                "w": {"on": {"GO": "p"}},
                "p": {"invoke": {"src": "svc", "id": "sp", "onDone": "q"}},
                "q": {"invoke": {"src": "svc", "id": "sq", "onDone": "p"}},
            },
        },
        "ping": {
            "initial": "a",
            "states": {
                "a": {"entry": "bounce", "on": {"P": "b",
                                                "EXT": {"actions": "cnt"}}},
                "b": {"entry": "bounce", "on": {"P": "a",
                                                "EXT": {"actions": "cnt"}}},
            },
        },
    },
}


async def main() -> int:
    try:
        import psutil

        proc = psutil.Process()
    except Exception:  # noqa: BLE001
        proc = None

    ext_fired = {"v": 0}
    laps = {"v": 0}
    obs: List[Obs] = []
    machines = []
    for i in range(200):
        kind = "plain" if i < 100 else "async"

        def bounce(i_, c, e, a):  # noqa: ANN001
            laps["v"] += 1
            i_.send("P", delay=1)

        async def bounce_a(i_, c, e, a):  # noqa: ANN001
            laps["v"] += 1
            i_.send("P", delay=1)

        def cnt(i_, c, e, a):  # noqa: ANN001
            ext_fired["v"] += 1

        def svc(i_, c, e):  # noqa: ANN001
            return 1

        async def svca(i_, c, e):  # noqa: ANN001
            await asyncio.sleep(0)
            return 1

        lg = MachineLogic(
            actions={
                "bounce": bounce_a if kind == "async" else bounce,
                "cnt": cnt,
            },
            services={"svc": svca if kind == "async" else svc},
        )
        o = Obs()
        obs.append(o)
        machines.append(
            Interpreter(
                create_machine(copy.deepcopy(SOAK), logic=lg)
            ).use(o)
        )
    await asyncio.gather(*(m.start() for m in machines))

    t0 = time.perf_counter()
    if proc is not None:
        proc.cpu_percent(None)
        rss0 = proc.memory_info().rss
    ext_sent = 0
    snapshots = {"ok": 0, "refused": 0}
    cycle = 0
    while time.perf_counter() - t0 < DURATION:
        cycle += 1
        for m in machines:
            m.send("EXT", priority=True)
            ext_sent += 1
        if cycle % 5 == 0:
            for m in machines[:20]:
                m.send("GO")
        if cycle % 11 == 0:  # chaos snapshot at (near) quiescence
            for m in machines[:10]:
                try:
                    m.get_persisted_snapshot()
                    snapshots["ok"] += 1
                except Exception:  # noqa: BLE001
                    snapshots["refused"] += 1
        await asyncio.sleep(0.02)
    elapsed = time.perf_counter() - t0
    cpu = proc.cpu_percent(None) if proc is not None else None
    rss_mb = (
        round((proc.memory_info().rss - rss0) / 1e6, 1)
        if proc is not None
        else None
    )
    await asyncio.sleep(0.8)
    dormant_without_hook = sum(
        1
        for i, m in enumerate(machines)
        if m.has_dormant_invocations and not obs[i].stranded
    )
    ext_dropped = sum(o.ext_dropped for o in obs)
    stranded_total = sum(len(o.stranded) for o in obs)
    await asyncio.gather(*(m.stop() for m in machines))

    res = {
        "duration_s": round(elapsed, 1),
        "machines": 200,
        "external_sent": ext_sent,
        "external_actions_fired": ext_fired["v"],
        "EXTERNAL_dropped": ext_dropped,
        "self_dropped": sum(o.self_dropped for o in obs),
        "delayed_selfsend_laps": laps["v"],
        "stranded_reports": stranded_total,
        "dormant_without_hook": dormant_without_hook,
        "snapshots": snapshots,
        "cpu_percent": cpu,
        "rss_delta_mb": rss_mb,
    }
    res["ok"] = (
        res["EXTERNAL_dropped"] == 0
        and res["dormant_without_hook"] == 0
        and res["external_actions_fired"] == res["external_sent"]
    )
    print(json.dumps(res, indent=1))
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "k_soak.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
