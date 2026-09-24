# -*- coding: utf-8 -*-
"""Order-like machine for the SOAK battle-test track @ 5e07ba8.

Reuses the shape of ../persistence/order_machine.py (parallel exchange/risk
regions, `after` timers, `onUnhandled: "defer"`, invoke) but trimmed and with
a bounded RAISE inbox for the internal self-feed, matching the SOAK spec:
"200 order-like machines (defer+rollback+bounded RAISE inbox+SimulatedClock
timers)".
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List

from xstate_statemachine import MachineLogic, create_machine

ORDER_CONFIG: Dict[str, Any] = {
    "id": "order",
    "initial": "draft",
    "context": {"trace_len": 0, "qty": 0, "filled": 0, "risk": "unknown", "attempts": 0},
    "onUnhandled": "defer",
    "actionErrorPolicy": "rollback",
    "states": {
        "draft": {
            "entry": ["log"],
            "on": {
                "SUBMIT": {"target": "submitted", "actions": ["set_qty"]},
                "ABANDON": {"target": "closed"},
            },
        },
        "submitted": {
            "type": "parallel",
            "entry": ["log"],
            "on": {
                "CANCEL": {"target": "cancelling"},
                "FAIL_HARD": {"target": "closed", "actions": ["boom"]},
                "SELF_RAISE": {"actions": ["raise_self"]},
            },
            "states": {
                "exchange": {
                    "initial": "acking",
                    "states": {
                        "acking": {
                            "invoke": {
                                "id": "ackSvc",
                                "src": "ack_service",
                                "onDone": {"target": "working", "actions": ["store_ack"]},
                                "onError": {"target": "rejected", "actions": ["store_err"]},
                            },
                            "after": {"5000": {"target": "timed_out", "actions": ["log"]}},
                        },
                        "working": {
                            "on": {
                                "FILL": {"actions": ["add_fill"]},
                                "DONE": {"target": "complete"},
                            },
                            "after": {"30000": {"target": "stale", "actions": ["log"]}},
                        },
                        "stale": {"on": {"RETRY": {"target": "acking"}}},
                        "timed_out": {"on": {"RETRY": {"target": "acking"}}},
                        "rejected": {"type": "final"},
                        "complete": {"type": "final"},
                    },
                },
                "risk": {
                    "initial": "checking",
                    "states": {
                        "checking": {
                            "on": {
                                "RISK_OK": {"target": "passed", "actions": ["mark_ok"]},
                                "RISK_BAD": {"target": "blocked", "actions": ["mark_bad"]},
                            }
                        },
                        "passed": {"on": {"RECHECK": {"target": "checking"}}},
                        "blocked": {"type": "final"},
                    },
                },
            },
        },
        "cancelling": {"entry": ["log"], "on": {"CANCEL_OK": {"target": "closed"}}},
        "closed": {"entry": ["log"], "type": "final"},
    },
}


def _bump(ctx: Dict[str, Any]) -> None:
    ctx["trace_len"] = ctx.get("trace_len", 0) + 1


def log(interp, ctx, event, action_def):  # noqa: ANN001
    _bump(ctx)


def set_qty(interp, ctx, event, action_def):  # noqa: ANN001
    ctx["qty"] = (event.payload or {}).get("qty", 10)
    _bump(ctx)


def store_ack(interp, ctx, event, action_def):  # noqa: ANN001
    _bump(ctx)


def store_err(interp, ctx, event, action_def):  # noqa: ANN001
    _bump(ctx)


def add_fill(interp, ctx, event, action_def):  # noqa: ANN001
    ctx["filled"] = ctx.get("filled", 0) + (event.payload or {}).get("n", 1)
    _bump(ctx)


def mark_ok(interp, ctx, event, action_def):  # noqa: ANN001
    ctx["risk"] = "ok"
    _bump(ctx)


def mark_bad(interp, ctx, event, action_def):  # noqa: ANN001
    ctx["risk"] = "bad"
    _bump(ctx)


def boom(interp, ctx, event, action_def):  # noqa: ANN001
    _bump(ctx)
    raise RuntimeError("hard failure (intentional, rollback-policy)")


def raise_self(interp, ctx, event, action_def):  # noqa: ANN001
    """Bounded self-feed: one hop only, never a runaway chain."""
    _bump(ctx)


async def ack_service(interp, ctx, event):  # noqa: ANN001
    ctx["attempts"] = ctx.get("attempts", 0) + 1
    return {"ack": ctx["attempts"]}


ACTIONS = {
    "log": log,
    "set_qty": set_qty,
    "store_ack": store_ack,
    "store_err": store_err,
    "add_fill": add_fill,
    "mark_ok": mark_ok,
    "mark_bad": mark_bad,
    "boom": boom,
    "raise_self": raise_self,
}


def build(*, max_queue_size: int = 256):
    cfg = copy.deepcopy(ORDER_CONFIG)
    logic = MachineLogic(actions=dict(ACTIONS), services={"ack_service": ack_service})
    return create_machine(cfg, logic=logic)


EVENT_POOL: List[Dict[str, Any]] = [
    {"type": "SUBMIT", "payload": {"qty": 7}},
    {"type": "RISK_OK"},
    {"type": "RISK_BAD"},
    {"type": "FILL", "payload": {"n": 1}},
    {"type": "FILL", "payload": {"n": 3}},
    {"type": "DONE"},
    {"type": "RETRY"},
    {"type": "RECHECK"},
    {"type": "CANCEL"},
    {"type": "CANCEL_OK"},
    {"type": "NOPE"},  # deliberately unknown -> deferred / ignored
    {"type": "FAIL_HARD"},  # rollback path
]
