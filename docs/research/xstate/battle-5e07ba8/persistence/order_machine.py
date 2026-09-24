# -*- coding: utf-8 -*-
"""Realistic order machine for the PERSISTENCE battle-test track.

Nested + parallel regions, invoke, `after` (SimulatedClock), onUnhandled
defer, bounded inbox, actionErrorPolicy rollback. Deliberately shaped like
the CandleViewer order path (B1-B20 contracts): a risk/fill parallel region
under a submitted state, a timeout on the exchange ack, and a compensating
rollback transition.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from xstate_statemachine import MachineLogic, create_machine

# ---------------------------------------------------------------------------
# 📜 Machine definition
# ---------------------------------------------------------------------------
ORDER_CONFIG: Dict[str, Any] = {
    "id": "order",
    "initial": "draft",
    "context": {
        "trace": [],
        "qty": 0,
        "filled": 0,
        "risk": "unknown",
        "attempts": 0,
    },
    "onUnhandled": "defer",
    "states": {
        "draft": {
            "entry": ["log_draft"],
            "on": {
                "SUBMIT": {"target": "submitted", "actions": ["set_qty"]},
                "ABANDON": {"target": "closed"},
            },
        },
        "submitted": {
            "type": "parallel",
            "entry": ["log_submitted"],
            "on": {
                "CANCEL": {"target": "cancelling"},
                "FAIL_HARD": {
                    "target": "closed",
                    "actions": ["boom"],
                },
            },
            "states": {
                "exchange": {
                    "initial": "acking",
                    "states": {
                        "acking": {
                            "invoke": {
                                "id": "ackSvc",
                                "src": "ack_service",
                                "onDone": {
                                    "target": "working",
                                    "actions": ["store_ack"],
                                },
                                "onError": {
                                    "target": "rejected",
                                    "actions": ["store_err"],
                                },
                            },
                            "after": {
                                "5000": {
                                    "target": "timed_out",
                                    "actions": ["log_timeout"],
                                }
                            },
                        },
                        "working": {
                            "on": {
                                "FILL": {"actions": ["add_fill"]},
                                "DONE": {"target": "complete"},
                            },
                            "after": {
                                "30000": {
                                    "target": "stale",
                                    "actions": ["log_stale"],
                                }
                            },
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
                                "RISK_OK": {
                                    "target": "passed",
                                    "actions": ["mark_ok"],
                                },
                                "RISK_BAD": {
                                    "target": "blocked",
                                    "actions": ["mark_bad"],
                                },
                            }
                        },
                        "passed": {"on": {"RECHECK": {"target": "checking"}}},
                        "blocked": {"type": "final"},
                    },
                },
            },
        },
        "cancelling": {
            "entry": ["log_cancelling"],
            "on": {"CANCEL_OK": {"target": "closed"}},
        },
        "closed": {"entry": ["log_closed"], "type": "final"},
    },
}


# ---------------------------------------------------------------------------
# 🧩 Logic
# ---------------------------------------------------------------------------
def _t(ctx: Dict[str, Any], what: str) -> None:
    ctx.setdefault("trace", []).append(what)


def log_draft(interp, ctx, event, action_def):  # noqa: ANN001
    _t(ctx, "entry:draft")


def log_submitted(interp, ctx, event, action_def):  # noqa: ANN001
    _t(ctx, "entry:submitted")


def log_cancelling(interp, ctx, event, action_def):  # noqa: ANN001
    _t(ctx, "entry:cancelling")


def log_closed(interp, ctx, event, action_def):  # noqa: ANN001
    _t(ctx, "entry:closed")


def set_qty(interp, ctx, event, action_def):  # noqa: ANN001
    ctx["qty"] = (event.payload or {}).get("qty", 10)
    _t(ctx, f"set_qty:{ctx['qty']}")


def store_ack(interp, ctx, event, action_def):  # noqa: ANN001
    _t(ctx, f"ack:{getattr(event, 'data', None)}")


def store_err(interp, ctx, event, action_def):  # noqa: ANN001
    _t(ctx, "ack_err")


def log_timeout(interp, ctx, event, action_def):  # noqa: ANN001
    _t(ctx, "timeout")


def log_stale(interp, ctx, event, action_def):  # noqa: ANN001
    _t(ctx, "stale")


def add_fill(interp, ctx, event, action_def):  # noqa: ANN001
    ctx["filled"] = ctx.get("filled", 0) + (event.payload or {}).get("n", 1)
    _t(ctx, f"fill:{ctx['filled']}")


def mark_ok(interp, ctx, event, action_def):  # noqa: ANN001
    ctx["risk"] = "ok"
    _t(ctx, "risk_ok")


def mark_bad(interp, ctx, event, action_def):  # noqa: ANN001
    ctx["risk"] = "bad"
    _t(ctx, "risk_bad")


def boom(interp, ctx, event, action_def):  # noqa: ANN001
    _t(ctx, "boom")
    raise RuntimeError("hard failure")


async def ack_service(interp, ctx, event):  # noqa: ANN001
    ctx["attempts"] = ctx.get("attempts", 0) + 1
    await asyncio.sleep(0)
    return {"ack": ctx.get("attempts", 1)}


ACTIONS = {
    "log_draft": log_draft,
    "log_submitted": log_submitted,
    "log_cancelling": log_cancelling,
    "log_closed": log_closed,
    "set_qty": set_qty,
    "store_ack": store_ack,
    "store_err": store_err,
    "log_timeout": log_timeout,
    "log_stale": log_stale,
    "add_fill": add_fill,
    "mark_ok": mark_ok,
    "mark_bad": mark_bad,
    "boom": boom,
}


def build(
    *,
    ack: Any = None,
    action_error_policy: str | None = None,
    on_unhandled: str | None = None,
) -> Any:
    cfg = _deepcopy(ORDER_CONFIG)
    if action_error_policy is not None:
        cfg["actionErrorPolicy"] = action_error_policy
    if on_unhandled is not None:
        cfg["onUnhandled"] = on_unhandled
    logic = MachineLogic(
        actions=dict(ACTIONS),
        services={"ack_service": ack or ack_service},
    )
    return create_machine(cfg, logic=logic)


def _deepcopy(d: Any) -> Any:
    import copy

    return copy.deepcopy(d)


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
    {"type": "NOPE"},
]
