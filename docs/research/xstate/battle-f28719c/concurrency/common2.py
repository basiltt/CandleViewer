"""Shared helpers for the round-8 CONCURRENCY battle track @ 6db65d8.

Central rule of this round: EVERY service-related probe runs with BOTH
`def` and `async def` services. Round 7's pins were spelled `def` only and
were structurally blind to the coroutine lane (#179).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any, Callable, Dict, List

from xstate_statemachine import (  # noqa: F401
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

KINDS = ("def", "async def")


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


def make_service(kind: str, delay: float = 0.0, value: Any = None):
    """Return a service callable of the requested spelling."""
    val = {"v": 1} if value is None else value

    if kind == "def":

        def svc(i, ctx, e):  # noqa: ANN001
            if delay:
                time.sleep(delay)
            return val

        return svc

    async def asvc(i, ctx, e):  # noqa: ANN001
        if delay:
            await asyncio.sleep(delay)
        return val

    return asvc


def make_action(kind: str, body: Callable[..., None]):
    """Return an action of the requested spelling wrapping `body`."""
    if kind == "def":

        def act(i, ctx, e, ad):  # noqa: ANN001
            body(i, ctx, e, ad)

        return act

    async def aact(i, ctx, e, ad):  # noqa: ANN001
        body(i, ctx, e, ad)

    return aact


class Rec(PluginBase):
    """Records every observability hook with an ordered sequence number."""

    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []
        self._n = 0

    def _add(self, hook: str, **kw: Any) -> None:
        self._n += 1
        self.rows.append({"seq": self._n, "hook": hook, **kw})

    def on_event_received(self, i, e):  # noqa: ANN001
        self._add("on_event_received", type=getattr(e, "type", None))

    def on_transition(self, i, f, t, e):  # noqa: ANN001
        self._add("on_transition", type=getattr(e, "type", None))

    def on_event_dropped(self, i, e, reason=None, **kw):  # noqa: ANN001
        self._add(
            "on_event_dropped", type=getattr(e, "type", None), reason=reason
        )

    def on_unhandled_event(self, i, e, disposition=None, **kw):  # noqa: ANN001
        self._add(
            "on_unhandled_event",
            type=getattr(e, "type", None),
            disposition=disposition,
        )

    def on_action_execute(self, i, a):  # noqa: ANN001
        self._add("on_action_execute")

    def reasons(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for r in self.rows:
            if r["hook"] == "on_event_dropped":
                out[str(r.get("reason"))] = out.get(str(r.get("reason")), 0) + 1
        return out


def counts(rec: "Rec") -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in rec.rows:
        out[r["hook"]] = out.get(r["hook"], 0) + 1
    return out
