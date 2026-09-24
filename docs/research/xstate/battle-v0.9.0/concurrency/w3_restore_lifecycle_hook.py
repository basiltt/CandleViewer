"""w3 (@v0.9.0) -- STANDALONE repro for D13-concurrency-1.

CLAIM UNDER TEST (#230, 0.9.0 changelog):

  "`from_snapshot(plugins=...)`. Plugins are registered *before* the
   persisted events are admitted, so a restore-time refusal reaches
   `on_invalid_event` like a runtime one. Same effect as `.use()` on the
   result, just early enough."

`on_invalid_event` does reach the plugin -- that half is exact (w2/P2,
P3: 320 property cases, every refusal reported exactly once). What does
NOT reach it is the LIFECYCLE hook: `on_interpreter_start` never fires
on a restored interpreter, on either engine, by either registration
route (`plugins=` or `.use()`).

Cause: `Interpreter.start()` detects the restored shape
(status == "running" and no loop task) and takes a dedicated resume
branch that `return self`s -- interpreter.py:582-624 -- before reaching
the `for plugin in self._plugins: plugin.on_interpreter_start(self)`
call at interpreter.py:664. `SyncInterpreter.start()` has the same
shape (sync_interpreter.py:388 is likewise below its resume return).

Consequence for an adopter: every plugin that allocates per-run state in
`on_interpreter_start` -- a metrics span, a log correlation id, an audit
"actor came up" record, a latency clock -- is silently inert for the
whole life of a restored actor, which is exactly the actor whose
start-up you most want recorded. `on_interpreter_stop` still fires, so
the pairing is also unbalanced: stop without start.

Cells: {async, sync} x {def, async def} x {plugins=, .use()}.
Exit 1 == the hook did not fire.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.plugins import PluginBase

ROWS: List[Dict[str, Any]] = []
FAILS: List[str] = []
HERE = os.path.dirname(os.path.abspath(__file__))


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])),
            **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(HERE, name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


class LifecyclePlugin(PluginBase):
    """Counts the two lifecycle hooks. They must PAIR: 1 start, 1 stop."""

    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0

    def on_interpreter_start(self, interpreter):  # noqa: ANN001
        self.starts += 1

    def on_interpreter_stop(self, interpreter):  # noqa: ANN001
        self.stops += 1


CFG: Dict[str, Any] = {
    "id": "w3",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"G": "b"}}, "b": {"entry": ["bump"]}},
}


def mk_logic(kind: str) -> MachineLogic:
    if kind == "def":
        def bump(i, ctx, e, ad):  # noqa: ANN001
            ctx["n"] = ctx.get("n", 0) + 1
        return MachineLogic(actions={"bump": bump})

    async def abump(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1
    return MachineLogic(actions={"bump": abump})


async def cell_async(kind: str, route: str) -> None:
    m = create_machine(CFG, logic=mk_logic(kind))

    # 🅰️ CONTROL: a FRESH interpreter, same plugin, same route.
    ctrl = LifecyclePlugin()
    i = Interpreter(m)
    i.use(ctrl)
    await i.start()
    blob = json.dumps(i.get_persisted_snapshot(), default=str)
    await i.stop()

    # 🅱️ SUBJECT: the SAME plugin class on a RESTORED interpreter.
    sub = LifecyclePlugin()
    if route == "plugins=":
        r = Interpreter.from_snapshot(blob, m, plugins=[sub])
    else:
        r = Interpreter.from_snapshot(blob, m)
        r.use(sub)
    await r.start()
    await r.send("G")             # prove the restored machine is LIVE
    await asyncio.sleep(0.05)
    live = r.context.get("n", 0) == 1
    await r.stop()

    ok = sub.starts == 1
    if not ok:
        FAILS.append(
            f"async/{kind}/{route}: on_interpreter_start fired "
            f"{sub.starts}x on a RESTORED interpreter (fresh control: "
            f"{ctrl.starts}x); on_interpreter_stop fired {sub.stops}x "
            f"-- unbalanced")
    ROWS.append({"engine": "async", "kind": kind, "route": route,
                 "control_starts": ctrl.starts, "control_stops": ctrl.stops,
                 "restored_starts": sub.starts, "restored_stops": sub.stops,
                 "restored_machine_is_live": live, "ok": ok})


def cell_sync(kind: str, route: str) -> None:
    m = create_machine(CFG, logic=mk_logic("def"))   # sync engine: def only

    ctrl = LifecyclePlugin()
    i = SyncInterpreter(m)
    i.use(ctrl)
    i.start()
    blob = json.dumps(i.get_persisted_snapshot(), default=str)
    i.stop()

    sub = LifecyclePlugin()
    if route == "plugins=":
        r = SyncInterpreter.from_snapshot(blob, m, plugins=[sub])
    else:
        r = SyncInterpreter.from_snapshot(blob, m)
        r.use(sub)
    r.start()
    r.send("G")
    live = r.context.get("n", 0) == 1
    r.stop()

    ok = sub.starts == 1
    if not ok:
        FAILS.append(
            f"sync/def/{route}: on_interpreter_start fired {sub.starts}x on "
            f"a RESTORED interpreter (fresh control: {ctrl.starts}x); "
            f"on_interpreter_stop fired {sub.stops}x -- unbalanced")
    ROWS.append({"engine": "sync", "kind": "def", "route": route,
                 "control_starts": ctrl.starts, "control_stops": ctrl.stops,
                 "restored_starts": sub.starts, "restored_stops": sub.stops,
                 "restored_machine_is_live": live, "ok": ok})


async def main() -> int:
    for kind in ("def", "async def"):
        for route in ("plugins=", ".use()"):
            await cell_async(kind, route)
    for route in ("plugins=", ".use()"):
        cell_sync("def", route)
    emit("w3_restore_lifecycle_hook", {
        "claim": "#230: plugins= registered before restored events are "
                 "admitted; 'same effect as .use() on the result'",
        "holds_for": "on_invalid_event (verified exactly-once in w2/P2, "
                     "320 cases)",
        "fails_for": "on_interpreter_start -- never fires on a restored "
                     "interpreter, either engine, either route",
        "site": "interpreter.py:582-624 resume branch returns before the "
                "plugin start-hook loop at interpreter.py:664; "
                "sync_interpreter.py:388 same shape",
        "cells": ROWS,
        "failures": FAILS,
        "verdict": "CLEAN" if not FAILS else "DEFECT",
    })
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
