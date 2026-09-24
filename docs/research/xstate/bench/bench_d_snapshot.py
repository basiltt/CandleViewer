# -----------------------------------------------------------------------------
# bench_d_snapshot.py — (d) snapshot + restore cost and size
# -----------------------------------------------------------------------------
"""Snapshot/restore for a machine with nested + parallel states and ~2 KB ctx.

CandleViewer cares about this for two paths:
  * recorder / crash recovery: snapshot every open order periodically
  * failover: restore 500 order machines on process start

Measures get_snapshot (JSON str), get_persisted_snapshot (dict),
from_snapshot, and the serialized byte size. Also checks WHAT is lost across
a round trip (timers, invoked services) — a correctness property that matters
more than the microseconds.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List

import common
from xstate_statemachine import Interpreter, MachineLogic, create_machine


def big_context(target_bytes: int = 2048) -> Dict[str, Any]:
    """A realistic ~2 KB order context: fills, tags, algo params."""
    ctx: Dict[str, Any] = {
        "order_id": "1f2e3d4c-5b6a-7980-9a0b-1c2d3e4f5a6b",
        "symbol": "BTCUSDT",
        "side": "Buy",
        "qty": 1.234,
        "filled": 0.0,
        "avg_px": 0.0,
        "algo": {
            "kind": "twap",
            "slices": 12,
            "interval_ms": 5000,
            "limit_offset_bps": 2.5,
        },
        "fills": [],
        "tags": [],
    }
    i = 0
    while len(json.dumps(ctx).encode()) < target_bytes:
        ctx["fills"].append(
            {"id": f"f{i}", "px": 65000.0 + i, "qty": 0.01, "ts": 1.7e12 + i}
        )
        ctx["tags"].append(f"tag-{i}")
        i += 1
    return ctx


NESTED_PARALLEL = {
    "id": "orderx",
    "type": "parallel",
    "states": {
        "execution": {
            "initial": "working",
            "states": {
                "working": {
                    "initial": "resting",
                    "states": {
                        "resting": {"on": {"CHASE": "chasing"}},
                        "chasing": {"on": {"REST": "resting"}},
                    },
                    "on": {"DONE": "complete"},
                },
                "complete": {"type": "final"},
            },
        },
        "risk": {
            "initial": "ok",
            "states": {
                "ok": {"on": {"BREACH": "halted"}},
                "halted": {"on": {"CLEAR": "ok"}},
            },
        },
        "reporting": {
            "initial": "pending_ack",
            "states": {
                "pending_ack": {"on": {"ACKED": "acked"}},
                "acked": {"on": {"REPORTED": "reported"}},
                "reported": {},
            },
        },
    },
}


def make(ctx: Dict[str, Any]) -> Any:
    cfg = json.loads(json.dumps(NESTED_PARALLEL))
    cfg["context"] = json.loads(json.dumps(ctx))
    return create_machine(cfg, logic=MachineLogic())


async def main() -> None:
    common.report("machine_specs", common.machine_specs())
    ctx = big_context()
    ctx_bytes = len(json.dumps(ctx).encode())

    interp = await Interpreter(make(ctx)).start()
    await interp.send("CHASE")
    await interp.send("BREACH")
    await interp.send("ACKED")
    await asyncio.sleep(0.05)
    states_before = sorted(interp.current_state_ids)

    N = 2_000
    # --- get_snapshot (JSON string) --------------------------------------
    snap = interp.get_snapshot()
    t0 = time.perf_counter()
    for _ in range(N):
        s = interp.get_snapshot()
    t_get = (time.perf_counter() - t0) / N * 1e6

    # --- get_persisted_snapshot (dict) -----------------------------------
    t0 = time.perf_counter()
    for _ in range(N):
        d = interp.get_persisted_snapshot()
    t_get_dict = (time.perf_counter() - t0) / N * 1e6

    # --- from_snapshot ----------------------------------------------------
    machines = [make(ctx) for _ in range(N)]
    t0 = time.perf_counter()
    for m in machines:
        r = Interpreter.from_snapshot(snap, m)
    t_restore = (time.perf_counter() - t0) / N * 1e6

    # --- restore + resume (start) ----------------------------------------
    R = 200
    machines2 = [make(ctx) for _ in range(R)]
    restored = [Interpreter.from_snapshot(snap, m) for m in machines2]
    t0 = time.perf_counter()
    await asyncio.gather(*(r.start() for r in restored))
    t_resume = (time.perf_counter() - t0) / R * 1e6

    rr = restored[0]
    states_after = sorted(rr.current_state_ids)
    ctx_equal = rr.context == interp.context

    # 🔍 does a restored machine still transition correctly?
    await rr.send("CLEAR")
    await asyncio.sleep(0.05)
    post_restore_transition_works = any(
        s.endswith("risk.ok") for s in rr.current_state_ids
    )

    await asyncio.gather(*(r.stop() for r in restored))
    await interp.stop()

    # --- timer survival check --------------------------------------------
    timer_cfg = {
        "id": "deadline",
        "initial": "armed",
        "context": {"fired": False},
        "states": {
            "armed": {"after": {800: {"target": "expired"}}},
            "expired": {"entry": ["mark"], "type": "final"},
        },
    }

    def mark(i: Any, c: Dict[str, Any], e: Any, a: Any) -> None:
        c["fired"] = True

    logic = MachineLogic(actions={"mark": mark})
    t_i = await Interpreter(create_machine(timer_cfg, logic=logic)).start()
    await asyncio.sleep(0.1)  # 700 ms still to run
    t_snap = t_i.get_snapshot()
    await t_i.stop()
    t_r = await Interpreter.from_snapshot(
        t_snap, create_machine(timer_cfg, logic=logic)
    ).start()
    await asyncio.sleep(1.5)  # well past the original deadline
    timer_survived = t_r.context["fired"]
    await t_r.stop()

    common.report(
        "d_snapshot_restore",
        {
            "context_json_bytes": ctx_bytes,
            "snapshot_json_bytes": len(snap.encode()),
            "snapshot_json_bytes_compact": len(
                json.dumps(json.loads(snap), separators=(",", ":")).encode()
            ),
            "snapshot_overhead_vs_context_bytes": len(snap.encode())
            - ctx_bytes,
            "get_snapshot_us": t_get,
            "get_persisted_snapshot_dict_us": t_get_dict,
            "from_snapshot_us": t_restore,
            "restore_plus_start_us": t_resume,
            "restore_500_orders_estimated_ms": (t_restore + t_resume)
            * 500
            / 1000.0,
            "active_states_before": states_before,
            "active_states_after_restore": states_after,
            "states_round_trip_ok": states_before == states_after,
            "context_round_trip_ok": ctx_equal,
            "post_restore_transition_works": post_restore_transition_works,
            "pending_after_timer_survives_restore": timer_survived,
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
