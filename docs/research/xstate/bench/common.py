# -----------------------------------------------------------------------------
# common.py — shared harness for xstate-statemachine benchmarks (CandleViewer)
# -----------------------------------------------------------------------------
"""Shared machine definitions, logic and timing helpers for the bench suite.

All benchmarks import from here so the OMS-like machine under test is
identical across (a)-(g).
"""

from __future__ import annotations

import json
import logging
import platform
import statistics
import sys
import time
from typing import Any, Dict, List

# 🔇 The library logs at INFO on every transition. Left on, logging dominates
#    the profile (measured: ~6x slowdown). Production would also disable it.
logging.getLogger("xstate_statemachine").setLevel(logging.CRITICAL)
logging.disable(logging.INFO)

from xstate_statemachine import MachineLogic, create_machine  # noqa: E402

# -----------------------------------------------------------------------------
# 📈 5-state OMS-like machine: pending → submitted → open → (filled | cancelled)
# -----------------------------------------------------------------------------

OMS_CONFIG: Dict[str, Any] = {
    "id": "order",
    "initial": "pending",
    "context": {
        "qty": 0.0,
        "filled": 0.0,
        "avg_px": 0.0,
        "acks": 0,
        "fills": 0,
        "events": 0,
    },
    "states": {
        "pending": {
            "entry": ["count"],
            "on": {
                "SUBMIT": {
                    "target": "submitted",
                    "cond": "has_qty",
                    "actions": ["count", "mark_submitted"],
                },
                "CANCEL": {"target": "cancelled", "actions": ["count"]},
            },
        },
        "submitted": {
            "on": {
                "ACK": {
                    "target": "open",
                    "cond": "is_acceptable",
                    "actions": ["count", "on_ack"],
                },
                "REJECT": {"target": "cancelled", "actions": ["count"]},
            },
        },
        "open": {
            "on": {
                "FILL": [
                    {
                        "target": "filled",
                        "cond": "is_fully_filled",
                        "actions": ["count", "apply_fill"],
                    },
                    {
                        "target": "open",
                        "cond": "is_partial",
                        "actions": ["count", "apply_fill"],
                    },
                ],
                "CANCEL": {"target": "cancelled", "actions": ["count"]},
                "AMEND": {
                    "target": "open",
                    "cond": "has_qty",
                    "actions": ["count", "amend"],
                },
            },
        },
        "filled": {"type": "final"},
        "cancelled": {"type": "final"},
    },
}


# --- guards ------------------------------------------------------------------
def has_qty(ctx: Dict[str, Any], e: Any) -> bool:
    return ctx["qty"] >= 0.0


def is_acceptable(ctx: Dict[str, Any], e: Any) -> bool:
    return ctx["qty"] > 0.0 and ctx["filled"] < ctx["qty"]


def is_fully_filled(ctx: Dict[str, Any], e: Any) -> bool:
    return ctx["filled"] + float(e.payload.get("qty", 0.0)) >= ctx["qty"]


def is_partial(ctx: Dict[str, Any], e: Any) -> bool:
    return not is_fully_filled(ctx, e)


# --- actions -----------------------------------------------------------------
def count(i: Any, ctx: Dict[str, Any], e: Any, a: Any) -> None:
    ctx["events"] += 1


def mark_submitted(i: Any, ctx: Dict[str, Any], e: Any, a: Any) -> None:
    ctx["qty"] = float(e.payload.get("qty", 1000.0))


def on_ack(i: Any, ctx: Dict[str, Any], e: Any, a: Any) -> None:
    ctx["acks"] += 1


def apply_fill(i: Any, ctx: Dict[str, Any], e: Any, a: Any) -> None:
    q = float(e.payload.get("qty", 0.0))
    px = float(e.payload.get("px", 0.0))
    total = ctx["filled"] + q
    if total > 0:
        ctx["avg_px"] = (ctx["avg_px"] * ctx["filled"] + px * q) / total
    ctx["filled"] = total
    ctx["fills"] += 1


def amend(i: Any, ctx: Dict[str, Any], e: Any, a: Any) -> None:
    ctx["qty"] = float(e.payload.get("qty", ctx["qty"]))


OMS_LOGIC_KW = dict(
    actions={
        "count": count,
        "mark_submitted": mark_submitted,
        "on_ack": on_ack,
        "apply_fill": apply_fill,
        "amend": amend,
    },
    guards={
        "has_qty": has_qty,
        "is_acceptable": is_acceptable,
        "is_fully_filled": is_fully_filled,
        "is_partial": is_partial,
    },
)


def oms_machine():
    """Build a fresh OMS MachineNode (with logic bound)."""
    return create_machine(
        json.loads(json.dumps(OMS_CONFIG)), logic=MachineLogic(**OMS_LOGIC_KW)
    )


def oms_event_cycle(n: int) -> List[Dict[str, Any]]:
    """A repeating event stream that keeps the machine in `open` (AMEND loop).

    SUBMIT, ACK, then n-2 AMEND/partial-FILL events. Never reaches a final
    state, so all `n` events are actually processed (a final state would
    make later events no-ops and inflate throughput).
    """
    evs: List[Dict[str, Any]] = [
        {"type": "SUBMIT", "qty": 1_000_000.0},
        {"type": "ACK", "order_id": "x"},
    ]
    for k in range(n - 2):
        if k % 2 == 0:
            evs.append({"type": "FILL", "qty": 0.5, "px": 100.0 + k % 7})
        else:
            evs.append({"type": "AMEND", "qty": 1_000_000.0})
    return evs


# -----------------------------------------------------------------------------
# 🖥️ Machine specs
# -----------------------------------------------------------------------------
def machine_specs() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "machine": platform.machine(),
    }
    try:
        import psutil

        info["logical_cores"] = psutil.cpu_count(logical=True)
        info["physical_cores"] = psutil.cpu_count(logical=False)
        f = psutil.cpu_freq()
        info["cpu_freq_mhz"] = round(f.max or f.current, 0) if f else None
        info["ram_total_gb"] = round(
            psutil.virtual_memory().total / 1024**3, 1
        )
    except Exception as exc:  # pragma: no cover
        info["psutil_error"] = repr(exc)
    try:
        import xstate_statemachine as xs

        info["xstate_statemachine"] = getattr(xs, "__version__", "unknown")
    except Exception:
        pass
    return info


# -----------------------------------------------------------------------------
# ⏱️ Timing helpers
# -----------------------------------------------------------------------------
def pct(vals: List[float], p: float) -> float:
    if not vals:
        return float("nan")
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


def summarize(vals: List[float]) -> Dict[str, float]:
    return {
        "n": len(vals),
        "mean": statistics.fmean(vals),
        "p50": pct(vals, 50),
        "p95": pct(vals, 95),
        "p99": pct(vals, 99),
        "max": max(vals) if vals else float("nan"),
    }


def report(name: str, payload: Dict[str, Any]) -> None:
    print(f"\n=== {name} ===")
    print(json.dumps(payload, indent=2, default=str))


class Timer:
    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *a):
        self.dt = time.perf_counter() - self.t0
