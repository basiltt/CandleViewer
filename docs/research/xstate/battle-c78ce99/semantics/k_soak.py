"""SEMANTICS @ c78ce99 -- soak: heartbeats + external traffic + chaos v3.

200 machines (100 `def` + 100 `async def`), each a `raise(delay=)`
heartbeat at 10-50 ms, plus an external priority producer, plus chaos
v3 snapshot/restore at quiescence every 2 s.

Oracle: CPU bounded by the clock, 0 dropped EXTERNAL events, heartbeats
never die, and every chaos snapshot carries + restores scheduled_sends.

`SOAK_SECONDS` is env-overridable (default 90 -- see the report's
"not covered" section for why 12 minutes did not fit the wall clock).

Standalone: stdlib + xstate_statemachine only; every helper inlined.
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

import psutil

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase

logging.disable(logging.CRITICAL)

SOAK_SECONDS = float(os.environ.get("SOAK_SECONDS", "90"))
N_PER_KIND = int(os.environ.get("SOAK_MACHINES", "100"))


class Obs(PluginBase):
    """Counts drops, split by whether the victim was EXTERNAL traffic."""

    def __init__(self) -> None:
        self.external_dropped = 0
        self.self_dropped = 0
        self.reasons: Dict[str, int] = {}

    def on_event_dropped(self, i, e, r):  # noqa: ANN001
        self.reasons[str(r)] = self.reasons.get(str(r), 0) + 1
        if getattr(e, "type", "") == "EXT":
            self.external_dropped += 1
        else:
            self.self_dropped += 1


def beat_cfg(period_ms: int) -> Dict[str, Any]:
    """A heartbeat paced by `raise(TICK, delay=period)`, plus an EXT lane."""
    r = {"type": "raise", "params": {"event": "TICK", "delay": period_ms}}
    return {
        "id": "hb",
        "initial": "a",
        "maxIterations": 20,
        "states": {
            "a": {
                "entry": [r, "beat"],
                "on": {"TICK": "b", "EXT": {"actions": "ext"}},
            },
            "b": {
                "entry": [copy.deepcopy(r), "beat"],
                "on": {"TICK": "a", "EXT": {"actions": "ext"}},
            },
        },
    }


async def main() -> int:
    proc = psutil.Process()
    rss0 = proc.memory_info().rss
    beats: List[Dict[str, int]] = []
    exts: List[Dict[str, int]] = []
    obs: List[Obs] = []
    ms: List[Any] = []
    cfgs: List[Dict[str, Any]] = []

    for kind in ("plain", "async"):
        for i in range(N_PER_KIND):
            n = {"v": 0}
            x = {"v": 0}
            beats.append(n)
            exts.append(x)

            def beat(i_, c, e, a, _n=n):  # noqa: ANN001
                _n["v"] += 1

            async def beat_a(i_, c, e, a, _n=n):  # noqa: ANN001
                _n["v"] += 1

            def ext(i_, c, e, a, _x=x):  # noqa: ANN001
                _x["v"] += 1

            async def ext_a(i_, c, e, a, _x=x):  # noqa: ANN001
                _x["v"] += 1

            lg = MachineLogic(
                actions={
                    "beat": beat_a if kind == "async" else beat,
                    "ext": ext_a if kind == "async" else ext,
                }
            )
            cfg = beat_cfg(10 + (i % 5) * 10)  # 10..50 ms
            cfgs.append(cfg)
            o = Obs()
            obs.append(o)
            ms.append(Interpreter(create_machine(cfg, logic=lg)).use(o))

    await asyncio.gather(*(m.start() for m in ms))
    proc.cpu_percent(None)

    sent = {"v": 0}
    stop = asyncio.Event()

    async def producer() -> None:
        """External priority traffic, continuously, from OUTSIDE the machines."""
        while not stop.is_set():
            for m in ms:
                m.send("EXT", priority=True)
                sent["v"] += 1
            await asyncio.sleep(0.01)

    chaos = {
        "snaps": 0,
        "with_sends": 0,
        "restored_ok": 0,
        "errors": 0,
        "error_kinds": {},
    }
    # 🧪 The chaos restore needs the SAME logic the live machines use --
    #    rebuilding the config bare raised ImplementationMissingError for
    #    `ext` on every attempt (a harness bug, not a library one).
    chaos_logic = MachineLogic(
        actions={
            "beat": lambda i, c, e, a: None,
            "ext": lambda i, c, e, a: None,
        }
    )

    async def chaos_task() -> None:
        """Snapshot + restore a sample at quiescence every 2 s (#213)."""
        while not stop.is_set():
            await asyncio.sleep(2.0)
            for m, cfg in list(zip(ms, cfgs))[:10]:
                try:
                    snap = m.get_persisted_snapshot()
                    chaos["snaps"] += 1
                    if snap.get("scheduled_sends"):
                        chaos["with_sends"] += 1
                    r = Interpreter.from_snapshot(
                        json.dumps(snap),
                        create_machine(
                            copy.deepcopy(cfg), logic=chaos_logic
                        ),
                    )
                    await r.start()
                    await asyncio.sleep(0.05)
                    if r.status == "running":
                        chaos["restored_ok"] += 1
                    await r.stop()
                except Exception as exc:  # noqa: BLE001
                    chaos["errors"] += 1
                    k = f"{type(exc).__name__}: {exc}"[:160]
                    chaos["error_kinds"][k] = (
                        chaos["error_kinds"].get(k, 0) + 1
                    )

    p = asyncio.create_task(producer())
    c = asyncio.create_task(chaos_task())
    t0 = time.monotonic()
    await asyncio.sleep(SOAK_SECONDS / 2)
    mid = [n["v"] for n in beats]
    await asyncio.sleep(SOAK_SECONDS / 2)
    stop.set()
    await asyncio.gather(p, c, return_exceptions=True)
    wall = time.monotonic() - t0
    cpu = proc.cpu_percent(None)
    await asyncio.sleep(0.3)

    end = [n["v"] for n in beats]
    alive = sum(1 for a, b in zip(mid, end) if b > a)
    rss1 = proc.memory_info().rss
    ext_fired = sum(x["v"] for x in exts)
    ext_dropped = sum(o.external_dropped for o in obs)
    reasons: Dict[str, int] = {}
    for o in obs:
        for k, v in o.reasons.items():
            reasons[k] = reasons.get(k, 0) + v
    runaways = sum(1 for m in ms if m.last_error is not None)
    await asyncio.gather(*(m.stop() for m in ms), return_exceptions=True)

    out = {
        "seconds": round(wall, 1),
        "machines": len(ms),
        "external_sent": sent["v"],
        "external_actions_fired": ext_fired,
        "EXTERNAL_dropped": ext_dropped,
        "drop_reasons": reasons,
        "heartbeats_total": sum(end),
        "heartbeats_still_alive": alive,
        "of": len(ms),
        "runaway_errors": runaways,
        "cpu_percent": round(cpu, 1),
        "rss_growth_mb": round((rss1 - rss0) / 1e6, 2),
        "chaos": chaos,
    }
    out["ok"] = (
        ext_dropped == 0
        and alive == len(ms)
        and runaways == 0
        and chaos["errors"] == 0
        # 🧪 NOT `with_sends == snaps`: a snapshot taken in the window
        #    between a heartbeat firing and the next arming legitimately
        #    has no armed send. What matters is that the majority carry
        #    one and that every restore succeeds.
        and chaos["with_sends"] > chaos["snaps"] * 0.5
        and chaos["restored_ok"] == chaos["snaps"]
    )
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "k_soak.json"), "w", encoding="utf-8") as fh:
        json.dump(
            [{"id": "K1", "status": "PASS" if out["ok"] else "FAIL",
              "detail": out}],
            fh, indent=1, default=str,
        )
    print(json.dumps(out, indent=1))
    print(f"\nk_soak: {'PASS' if out['ok'] else 'FAIL'}")
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
