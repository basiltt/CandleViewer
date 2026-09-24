"""N6 — SOAK: order-like machines incl. parallel regions + executor services
+ chaos snapshot/restore, snapshots taken ONLY at quiescence.

Reduced run: SOAK_SECONDS (default 300) instead of the brief's 720 — see the
reductions table in semantics.md. Everything else is at the stated size.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SnapshotMidStepError,
    XStateMachineError,
    create_machine,
)

SOAK_SECONDS = float(os.environ.get("SOAK_SECONDS", "300"))
N_MACHINES = int(os.environ.get("SOAK_MACHINES", "200"))

ORDER = {
    "id": "ord",
    "type": "parallel",
    "context": {"filled": 0, "seq": 0},
    "states": {
        "life": {
            "initial": "new",
            "states": {
                "new": {"on": {"SUBMIT": "working"}},
                "working": {
                    "invoke": {"src": "price", "onDone": {"target": "live", "actions": ["fill"]}}
                },
                "live": {"on": {"FILL": {"actions": ["fill"]}, "CANCEL": "done"}},
                "done": {"type": "final"},
            },
        },
        "risk": {
            "initial": "ok",
            "states": {
                "ok": {"on": {"BREACH": "halted"}},
                "halted": {"on": {"CLEAR": "ok"}},
            },
        },
    },
}


def _logic() -> MachineLogic:
    def price(i_, ctx, e):  # noqa: ANN001  (plain def -> service_executor, #149)
        return {"px": 101.5}

    def fill(i_, ctx, e, am):  # noqa: ANN001
        ctx["filled"] = ctx.get("filled", 0) + 1

    return MachineLogic(actions={"fill": fill}, services={"price": price})


def _mk():
    return create_machine(ORDER, logic=_logic())


async def main() -> None:
    rng = random.Random(9001)
    stats: Dict[str, int] = {
        "events": 0, "snapshots": 0, "restores": 0, "orders": 0,
        "midstep_at_quiescence": 0, "restore_drift": 0, "inert_running": 0,
        "typed_errors": 0, "untyped_errors": 0, "lost_fills": 0,
    }
    samples: List[str] = []
    try:
        import psutil  # type: ignore

        proc = psutil.Process()
        rss0 = proc.memory_info().rss
    except Exception:  # noqa: BLE001
        proc, rss0 = None, 0

    machines = [await Interpreter(_mk()).start() for _ in range(N_MACHINES)]
    stats["orders"] = N_MACHINES
    t_end = time.monotonic() + SOAK_SECONDS
    last_chaos = time.monotonic()
    EVENTS = ["SUBMIT", "FILL", "CANCEL", "BREACH", "CLEAR", "NOPE"]

    while time.monotonic() < t_end:
        for i in machines:
            ev = rng.choice(EVENTS)
            try:
                await i.send(ev, wait=True)
                stats["events"] += 1
            except XStateMachineError:
                stats["typed_errors"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["untyped_errors"] += 1
                if len(samples) < 5:
                    samples.append(f"send {ev}: {type(exc).__name__}: {exc}")

        # 🌀 chaos every ~2 s: snapshot at quiescence, restore, compare
        if time.monotonic() - last_chaos >= 2.0:
            last_chaos = time.monotonic()
            for idx in rng.sample(range(len(machines)), k=max(1, len(machines) // 10)):
                src = machines[idx]
                try:
                    blob = src.get_persisted_snapshot()  # quiescent: no step open
                    stats["snapshots"] += 1
                except SnapshotMidStepError:
                    stats["midstep_at_quiescence"] += 1
                    continue
                except Exception as exc:  # noqa: BLE001
                    stats["untyped_errors"] += 1
                    if len(samples) < 5:
                        samples.append(f"snapshot: {type(exc).__name__}: {exc}")
                    continue
                before_ids = sorted(src.current_state_ids)
                before_fill = src.context.get("filled")
                try:
                    r = await Interpreter.from_snapshot(json.dumps(blob), _mk()).start()
                    stats["restores"] += 1
                except Exception as exc:  # noqa: BLE001
                    stats["untyped_errors"] += 1
                    if len(samples) < 5:
                        samples.append(f"restore: {type(exc).__name__}: {exc}")
                    continue
                if sorted(r.current_state_ids) != before_ids:
                    stats["restore_drift"] += 1
                if r.status == "running" and not r.current_state_ids:
                    stats["inert_running"] += 1
                if r.context.get("filled") != before_fill:
                    stats["lost_fills"] += 1
                await src.stop()
                machines[idx] = r
                stats["orders"] += 1

    for i in machines:
        await i.stop()
    rss1 = proc.memory_info().rss if proc else 0
    out = {
        "soak_seconds": SOAK_SECONDS,
        "machines": N_MACHINES,
        **stats,
        "rss_delta_mb": round((rss1 - rss0) / 1e6, 2),
        "untyped_samples": samples,
        "ok": (
            stats["untyped_errors"] == 0
            and stats["midstep_at_quiescence"] == 0
            and stats["restore_drift"] == 0
            and stats["inert_running"] == 0
            and stats["lost_fills"] == 0
        ),
    }
    here = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(here, "results"), exist_ok=True)
    with open(os.path.join(here, "results", "n6_soak.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    import logging

    logging.disable(logging.CRITICAL)
    asyncio.run(main())
