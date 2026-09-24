# -*- coding: utf-8 -*-
"""STANDALONE: a plain-`def` service armed by a transition that is rolled
FORWARD by an `always` IS still submitted to the pool.

CHANGELOG [Unreleased] #193 claims:
  "a `def` service armed by a transition that is then rolled back
   (`actionErrorPolicy: rollback`) or rolled forward (an `always` out of the
   state before it stabilises) is never submitted to the pool."

The rollback half holds. The roll-forward half holds for `async def`
(0 submissions) but NOT for plain `def` (1 submission).

Contract shape: B14 `desynced` is a transient state with `always ->
snapshot_pending`. If such a transient state also carries an `invoke` -- an
entirely legal SCXML shape -- the invoked side effect fires on the `def` lane
even though the state is left in the same macrostep and its `onDone` can
never be taken (SCXML 6.4.2). For an OMS that is a real order/socket/IO call
issued from a state the machine never actually settled in.

Run BOTH lanes:
  CV_SVC_STYLE=async  -> doomed_submitted == 0  (exit 0)
  CV_SVC_STYLE=def    -> doomed_submitted == 1  (exit 1)

Exit 0 = rolled-forward invoke never submitted. Exit 1 = it was submitted.
"""
from __future__ import annotations
import asyncio, json, os, sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

STYLE = os.environ.get("CV_SVC_STYLE", "async")

CFG = {
    "id": "d1", "actionErrorPolicy": "rollback", "onUnhandled": "error",
    "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
    "initial": "live", "context": {},
    "states": {
        "live": {"on": {"GAP": {"target": "#d1.desynced"}}},
        # transient: `always` leaves in the same macrostep that armed `doomed`
        "desynced": {
            "invoke": {"id": "doomed", "src": "doomed_svc",
                       "onDone": {"target": "#d1.live"}},
            "always": {"target": "#d1.snapshot_pending"},
        },
        "snapshot_pending": {
            "invoke": {"id": "snap", "src": "snap_svc",
                       "onDone": {"target": "#d1.live"}},
        },
    },
}


async def main():
    hits = {"doomed": 0, "snap": 0}

    def _doomed(i, c, e):
        hits["doomed"] += 1
        return {"ok": 1}

    def _snap(i, c, e):
        hits["snap"] += 1
        return {"ok": 1}

    if STYLE == "def":
        doomed_svc, snap_svc = _doomed, _snap
    else:
        async def doomed_svc(i, c, e):
            return _doomed(i, c, e)

        async def snap_svc(i, c, e):
            return _snap(i, c, e)

    logic = MachineLogic(
        services={"doomed_svc": doomed_svc, "snap_svc": snap_svc}, strict=True)
    it = Interpreter(create_machine(json.loads(json.dumps(CFG)), logic=logic,
                                    strict_targets=True),
                     clock=SimulatedClock())
    await it.start()
    await it.send("GAP", wait=True)
    for _ in range(10):
        await asyncio.sleep(0.03)

    out = {
        "style": STYLE,
        "doomed_submitted": hits["doomed"],
        "snap_submitted": hits["snap"],
        "final_cfg": sorted(it.current_state_ids),
        "expected_doomed": 0,
        "claim": "CHANGELOG #193: rolled-forward invoke is never submitted",
    }
    await asyncio.wait_for(it.stop(), 10)
    out["VERDICT"] = ("ok" if hits["doomed"] == 0 else
                      "ROLLED-FORWARD def INVOKE WAS SUBMITTED")
    print(json.dumps(out, indent=1, default=str))
    return 0 if hits["doomed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
