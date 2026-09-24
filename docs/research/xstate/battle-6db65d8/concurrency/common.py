"""Shared helpers for the CONCURRENCY battle-test track @ 5e07ba8.

Never modifies library source. Every script imports the library from the
_ref clone's venv.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any, Dict, List

from xstate_statemachine import (  # noqa: F401
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)

# ---------------------------------------------------------------------------
# Machines
# ---------------------------------------------------------------------------

#: A single-state counter machine. Every PING is handled by a self-transition
#: that bumps context["n"]. `strict` is the mandated CV config value.
COUNTER_CONFIG: Dict[str, Any] = {
    "id": "counter",
    "initial": "idle",
    "context": {"n": 0},
    "strict": True,
    "guardErrorPolicy": "raise",
    "strictTargets": True,
    "states": {
        "idle": {
            "on": {
                "PING": {"actions": ["bump"]},
                "STOPME": {"target": "over"},
            }
        },
        "over": {"type": "final"},
    },
}


def bump(interpreter, ctx, event, action_def) -> None:  # noqa: ANN001
    ctx["n"] = ctx.get("n", 0) + 1


def counter_machine():
    return create_machine(
        COUNTER_CONFIG, logic=MachineLogic(actions={"bump": bump})
    )


# ---------------------------------------------------------------------------
# Plugins
# ---------------------------------------------------------------------------


class Accountant(PluginBase):
    """Records every observable disposition of an event."""

    def __init__(self) -> None:
        self.received: List[str] = []
        self.dropped: List[tuple] = []
        self.unhandled: List[tuple] = []
        self.errors: List[BaseException] = []

    def on_event_received(self, interpreter, event) -> None:  # noqa: ANN001
        self.received.append(event.type)

    def on_event_dropped(self, interpreter, event, reason) -> None:  # noqa: ANN001
        self.dropped.append((event.type, reason))

    def on_unhandled_event(  # noqa: ANN001
        self, interpreter, event, active_state_ids, disposition
    ) -> None:
        self.unhandled.append((event.type, disposition))

    def on_error(self, interpreter, error) -> None:  # noqa: ANN001
        self.errors.append(error)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def emit(name: str, payload: Dict[str, Any]) -> None:
    out = {"probe": name, "py": sys.version.split()[0], **payload}
    text = json.dumps(out, indent=2, default=repr)
    print(text)
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, f"{name}.json"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")


class Stopwatch:
    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.dt = time.perf_counter() - self.t0
        return False
