# -*- coding: utf-8 -*-
"""S4 -- snapshot from `on_interpreter_start` (#199), both engines.

R8-09 / #199: the hook fired a few lines before #182's in-flight guard was
raised, so `get_persisted_snapshot()` from it returned `status:"running"`
with an empty configuration -- a torn blob its own reader refuses. The fix
raises the flag BEFORE the hook on both engines, so the call must now be
REFUSED with `SnapshotMidStepError`.

Checked here, on both engines and both service kinds, from every plausible
early hook:
  - `on_interpreter_start`
  - `on_transition` for the init record
  - an `entry` action of the initial state

Accept criterion: every early snapshot attempt either REFUSES, or returns
a blob its own reader ACCEPTS. A blob that is written and then refused on
read is the #182 tear and is a FAILURE.

STANDALONE. XS_SVC=def|async.
"""
from __future__ import annotations

import asyncio
import json
import os

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.plugins import PluginBase

KIND = os.environ.get("XS_SVC", "async")
FAIL: list[str] = []

SPEC = {
    "id": "w",
    "type": "parallel",
    "states": {
        "r1": {"initial": "a", "states": {"a": {"entry": ["snap"]}, "b": {}}},
        "r2": {
            "initial": "c",
            "states": {
                "c": {"invoke": [{"id": "k", "src": "svc",
                                  "onDone": {"target": "d"}}]},
                "d": {},
            },
        },
    },
}


class Grab(PluginBase):
    """Snapshots from every early hook; records write/read outcomes."""

    def __init__(self) -> None:
        self.rows = []  # (window, outcome, detail)

    def _try(self, interp, window):
        try:
            blob = interp.get_persisted_snapshot()
        except Exception as exc:  # noqa: BLE001
            self.rows.append((window, "refused", type(exc).__name__))
            return
        # write succeeded -- does the READER accept it?
        try:
            j = Interpreter.from_snapshot(
                json.dumps(blob), _machine(self)[0]
            )
            self.rows.append((window, "accepted",
                              str(sorted(j.current_state_ids))))
        except Exception as exc:  # noqa: BLE001
            self.rows.append((window, "TORN", "%s: %s"
                              % (type(exc).__name__, str(exc)[:60])))

    def on_interpreter_start(self, interp):  # noqa: ANN001
        self._try(interp, "on_interpreter_start")

    def on_transition(self, interp, frm, to, t):  # noqa: ANN001
        if getattr(t, "event", "").startswith("___"):
            self._try(interp, "on_transition(init)")


def _machine(grab=None):
    calls = {"n": 0}

    async def svc_async(interp, ctx, ev):
        calls["n"] += 1
        await asyncio.sleep(0.5)
        return 1

    def svc_def(interp, ctx, ev):
        calls["n"] += 1
        import time

        time.sleep(0.05)
        return 1

    def snap(interp, ctx, ev, act):
        if grab is not None:
            grab._try(interp, "entry@start")

    logic = MachineLogic(
        actions={"snap": snap},
        services={"svc": svc_async if KIND == "async" else svc_def},
    )
    return create_machine(SPEC, logic=logic), calls


async def run_async():
    g = Grab()
    m, _ = _machine(g)
    i = Interpreter(m)
    i.use(g)
    await i.start()
    await asyncio.sleep(0.05)
    await i.stop()
    return g.rows


def run_sync():
    g = Grab()
    m, _ = _machine(g)
    i = SyncInterpreter(m)
    i.use(g)
    try:
        i.start()
    except Exception as exc:  # noqa: BLE001
        g.rows.append(("start", "raised", type(exc).__name__))
    try:
        i.stop()
    except Exception:  # noqa: BLE001
        pass
    return g.rows


async def main() -> None:
    print("=== S4 snapshot from on_interpreter_start [%s] ===" % KIND)
    for engine, rows in (("async", await run_async()), ("sync", run_sync())):
        print("\n--- %s engine" % engine)
        if not rows:
            print("  (no early hook fired)")
        for window, outcome, det in rows:
            print("  %-22s %-9s %s" % (window, outcome, det))
            if outcome == "TORN":
                FAIL.append("%s/%s: write-accepted, read-refused (%s)"
                            % (engine, window, det))
    print("\nFAILURES:", FAIL if FAIL else "none")
    print("VERDICT:", "FAIL" if FAIL else "PASS")


asyncio.run(main())
