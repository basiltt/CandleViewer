# -----------------------------------------------------------------------------
# bench_g2_error_channel.py — follow-up: is an action failure OBSERVABLE?
# -----------------------------------------------------------------------------
"""bench_g showed an action raising does not stop the machine. The follow-up
question that decides whether this is usable on an order path:

  1. Does the failed transition ROLL BACK, or does it apply partially?
  2. Can the application OBSERVE the failure — subscribe(), a plugin hook,
     an error event — or is a swallowed exception invisible except in logs?
  3. Does the *sync* engine behave the same way?

If a FILL action raises and the machine silently advances to `filled` with a
stale `filled` quantity, that is a position-accounting bug. This measures
exactly which of those happens.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

import common
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

CFG = {
    "id": "err",
    "initial": "a",
    "context": {"applied": []},
    "states": {
        "a": {
            "on": {
                "GO": {
                    "target": "b",
                    "actions": ["first", "explode", "third"],
                }
            }
        },
        "b": {"entry": ["entered_b"], "on": {"BACK": "a"}},
    },
}


class Recorder(PluginBase):
    """Does any plugin hook see the failure?"""

    def __init__(self) -> None:
        self.events: List[str] = []

    def on_transition(self, interp, from_s, to_s, transition) -> None:
        self.events.append(
            f"transition -> {sorted(s.id for s in to_s)}"
        )

    def on_action_execute(self, interp, action) -> None:
        self.events.append(f"action {action.type}")

    def on_interpreter_start(self, interp) -> None:
        self.events.append("start")

    def on_interpreter_stop(self, interp) -> None:
        self.events.append("stop")


def build(sync: bool):
    def first(i, ctx, e, a):
        ctx["applied"].append("first")

    def explode(i, ctx, e, a):
        ctx["applied"].append("explode_entered")
        raise RuntimeError("action failed mid-transition")

    def third(i, ctx, e, a):
        ctx["applied"].append("third")

    def entered_b(i, ctx, e, a):
        ctx["applied"].append("entry_b")

    logic = MachineLogic(
        actions={
            "first": first,
            "explode": explode,
            "third": third,
            "entered_b": entered_b,
        }
    )
    import json

    return create_machine(json.loads(json.dumps(CFG)), logic=logic)


async def async_probe() -> Dict[str, Any]:
    rec = Recorder()
    interp = Interpreter(build(False))
    interp.use(rec)
    seen: List[Any] = []
    try:
        interp.subscribe(lambda snap: seen.append(sorted(snap.state_ids)))
    except Exception as exc:
        seen.append(f"subscribe unavailable: {exc!r}")
    await interp.start()

    # capture whether the library logs anything at ERROR level
    logs: List[str] = []

    class Cap(logging.Handler):
        def emit(self, record):
            logs.append(f"{record.levelname}:{record.getMessage()[:90]}")

    lg = logging.getLogger("xstate_statemachine")
    lg.setLevel(logging.ERROR)
    logging.disable(logging.NOTSET)
    h = Cap()
    lg.addHandler(h)

    await interp.send("GO")
    await asyncio.sleep(0.3)

    lg.removeHandler(h)
    logging.disable(logging.INFO)

    out = {
        "actions_that_ran": list(interp.context["applied"]),
        "later_actions_in_same_transition_skipped": "third"
        not in interp.context["applied"],
        "target_entry_action_ran": "entry_b" in interp.context["applied"],
        "final_states": sorted(interp.current_state_ids),
        "transition_rolled_back": "err.a" in interp.current_state_ids,
        "status": interp.status,
        "plugin_hook_events": rec.events,
        "subscriber_snapshots": seen,
        "error_logs_emitted": logs,
        "observable_without_reading_logs": False,
    }
    # Is there ANY programmatic signal? status unchanged, states rolled back,
    # no error event delivered -> the only evidence is the log line.
    out["observable_without_reading_logs"] = out["status"] not in (
        "running",
    )
    await interp.stop()
    return out


def sync_probe() -> Dict[str, Any]:
    interp = SyncInterpreter(build(True)).start()
    raised = None
    try:
        interp.send("GO")
    except Exception as exc:
        raised = f"{type(exc).__name__}: {exc}"
    return {
        "actions_that_ran": list(interp.context["applied"]),
        "exception_propagated_to_caller": raised,
        "final_states": sorted(interp.current_state_ids),
        "transition_rolled_back": "err.a" in interp.current_state_ids,
        "status": interp.status,
    }


async def main() -> None:
    common.report(
        "g2_error_observability",
        {
            "async_engine": await async_probe(),
            "sync_engine": sync_probe(),
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
