"""R4-21: a plain-sync `invoke` src completes at a different point in the
macrostep on the sync engine vs the async engine, so the same recorded event
script (GO, CANCEL) x10 gives a different context split depending only on
which engine runs it (and, on the async engine, on scheduler interleaving).

SyncInterpreter._invoke_service completes the invoke INLINE within the
macrostep that enters the invoking state, so a CANCEL sent immediately after
GO never observes the invoke as still in-flight: the DoneEvent always wins.
Interpreter._invoke_service always defers the DoneEvent by at least one
event-loop turn, so a CANCEL sent immediately after GO always overtakes it.

Exits 1 (defect present) while sync and async disagree on the {ok,cancel}
split for the identical zero-gap script. Exits 0 if they ever agree.
"""
from __future__ import annotations
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[4] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401

import asyncio
import logging
import sys

sys.path.insert(
    0, str(_XS / 'src')
)
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

CFG = {
    "id": "d8",
    "initial": "idle",
    "context": {"ok": 0, "cancel": 0},
    "states": {
        "idle": {"on": {"GO": {"target": "busy"}}},
        "busy": {
            "invoke": {
                "id": "s",
                "src": "work",
                "onDone": {"target": "idle", "actions": ["ok"]},
            },
            "on": {"CANCEL": {"target": "idle", "actions": ["cancel"]}},
        },
    },
}


def logic():
    def ok(i, c, e, a):
        c["ok"] += 1

    def cancel(i, c, e, a):
        c["cancel"] += 1

    def work(i, c, e):  # plain sync, returns instantly, no awaits
        return 1

    return MachineLogic(actions={"ok": ok, "cancel": cancel}, services={"work": work})


def build():
    return create_machine(CFG, logic=logic())


N = 10


async def a_run():
    i = Interpreter(build(), clock=SimulatedClock())
    await i.start()
    for _ in range(N):
        await i.send("GO")
        await i.send("CANCEL")  # zero-gap: identical script to sync
    for _ in range(200):
        await asyncio.sleep(0)
    out = dict(i.context)
    await i.stop()
    return out


def s_run():
    i = SyncInterpreter(build(), clock=SimulatedClock())
    i.start()
    for _ in range(N):
        i.send("GO")
        i.send("CANCEL")
    out = dict(i.context)
    i.stop()
    return out


if __name__ == "__main__":
    sync_ctx = s_run()
    async_ctx = asyncio.run(a_run())
    print(f"OBSERVED: sync={sync_ctx}  async={async_ctx}")
    print("EXPECTED: sync == async for the identical (GO, CANCEL)x10 script")
    if sync_ctx == async_ctx:
        print("PASS: engines agree")
        sys.exit(0)
    print("FAIL: engines disagree on the same recorded event script")
    sys.exit(1)
