# -*- coding: utf-8 -*-
"""R7-05 -- async `start()` never sets the in-flight flag, so the
mid-step snapshot refusal is inert for the whole initial-entry window.

`base_interpreter.py:1389` gates the root-level refusal on
`_step_in_flight()` (`base_interpreter.py:1290-1295`), which reads only
`_processing` / `_is_processing`.

    SyncInterpreter.start()  -- sync_interpreter.py:370-374 -- deliberately
        sets `self._is_processing = True` around its initial descent, so a
        snapshot taken from an entry action of the INITIAL configuration is
        REFUSED.

    Interpreter.start()      -- interpreter.py:536-561 -- runs
        `_enter_states` + `_settle_transient_transitions` +
        `_await_actor_bringups` with `_processing` still False (it is only
        assigned at interpreter.py:420/1654/1698). The identical snapshot
        is ACCEPTED, and the blob it returns is TORN: the new leaf is
        already active (legal) while the context that entry is still
        writing is half-applied.

The torn blob restores clean -- `filled_qty=100, avg_px=0` is a legal
configuration -- so no shipped guard on either side detects it.

Derived from battle-221ce7c/semantics/repro/d7s1_start_entry_window_torn.py
and battle-221ce7c/persistence/q1b_start_entry_window_min.py.
Library only, no project machinery. main @ 221ce7c (unreleased 0.8.1;
`__version__` still reports 0.8.0 -- key on the commit). Python 3.13.

Exit code 1 == async ACCEPTED a torn initial-entry snapshot that sync refused.
"""
import asyncio
import copy
import json
import logging

logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import SnapshotMidStepError  # noqa: E402

WATCHDOG = 60.0

CFG = {
    "id": "oms",
    "initial": "filled",
    "context": {"filled_qty": 0, "avg_px": 0},
    "states": {"filled": {"entry": ["set_qty", "set_px"]}},
}


def logic():
    def set_qty(interp, ctx, evt, action_def):
        ctx["filled_qty"] = 100

    def set_px(interp, ctx, evt, action_def):
        ctx["avg_px"] = 101.5

    return MachineLogic(actions={"set_qty": set_qty, "set_px": set_px})


def build():
    return create_machine(copy.deepcopy(CFG), logic=logic())


class Snapper(PluginBase):
    """Snapshots from inside an action -- the call site the docs say is
    refused (api/index.md:715, :1789)."""

    def __init__(self):
        self.rows = []

    def on_action_execute(self, interp, action):
        try:
            blob = interp.get_persisted_snapshot()
            self.rows.append(("ACCEPTED", dict(blob.get("context", {})), blob))
        except SnapshotMidStepError:
            self.rows.append(("REFUSED", None, None))


def is_torn(ctx):
    return (ctx.get("filled_qty", 0) > 0) != (ctx.get("avg_px", 0) > 0)


async def run_engine(name):
    plug = Snapper()
    if name == "sync":
        it = SyncInterpreter(build()).use(plug).start()
        live = dict(it.context)
        it.stop()
    else:
        it = await Interpreter(build()).use(plug).start()
        live = dict(it.context)
        await it.stop()

    print("--- %s" % name)
    print("  live after start : ctx=%s" % (live,))
    torn_blobs = []
    for verdict, ctx, blob in plug.rows:
        mark = ""
        if verdict == "ACCEPTED" and ctx is not None and is_torn(ctx):
            mark = "   >>> TORN"
            torn_blobs.append(blob)
        print("  snapshot in entry: %-8s ctx=%s%s" % (verdict, ctx, mark))

    for blob in torn_blobs:
        rb = await Interpreter.from_snapshot(json.dumps(blob), build()).start()
        print("     restored: %s ctx=%s last_error=%r"
              % (sorted(rb.current_state_ids), dict(rb.context), rb.last_error))
        await rb.stop()
    return len(torn_blobs)


async def main():
    sync_torn = await run_engine("sync")
    async_torn = await run_engine("async")
    print()
    print("torn ACCEPTED blobs in the initial-entry window: "
          "async=%d sync=%d" % (async_torn, sync_torn))
    if async_torn > 0 and sync_torn == 0:
        print("REPRODUCED: the async engine ACCEPTED a torn snapshot taken "
              "from inside an initial-entry action, which the sync engine "
              "REFUSED on the identical machine.")
        print("EXPECTED  : SnapshotMidStepError on both engines -- "
              "`Interpreter.start()` must set `_processing = True` around "
              "its initial descent the way sync_interpreter.py:370-374 does.")
        return 1
    print("NOT reproduced (async=%d, sync=%d)." % (async_torn, sync_torn))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(asyncio.wait_for(main(), WATCHDOG)))
