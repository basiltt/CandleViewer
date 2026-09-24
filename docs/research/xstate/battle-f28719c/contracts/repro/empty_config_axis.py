# -*- coding: utf-8 -*-
"""STANDALONE: isolate WHEN the rollback+onDone storm leaves an empty
configuration on a live interpreter.

Axis: does the invoking state carry an `on` handler or not?
Everything else identical. Prints configuration at each settle tick.

Exit 1 if any variant ends live-with-empty-configuration.
"""
from __future__ import annotations
import asyncio, json, os, sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

STYLE = os.environ.get("CV_SVC_STYLE", "async")


def cfg(with_handlers: bool):
    starting = {"invoke": {"id": "sub", "src": "svc",
                           "onDone": {"target": "#r6.recording"},
                           "onError": {"target": "#r6.err"}}}
    recording = {"entry": ["boom"]}
    idle = {"on": {"GO": {"target": "#r6.starting"}}}
    if with_handlers:
        starting["on"] = {"PING": {"actions": ["noop"]}}
        recording["on"] = {"PING": {"actions": ["noop"]}}
        idle["on"]["PING"] = {"actions": ["noop"]}
    return {"id": "r6", "actionErrorPolicy": "rollback", "onUnhandled": "defer",
            "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
            "initial": "idle", "context": {},
            "states": {"idle": idle, "starting": starting,
                       "recording": recording, "err": {}}}


def logic():
    def boom(i, c, e, a):
        raise RuntimeError("entry failed")

    def noop(i, c, e, a):
        c["pings"] = c.get("pings", 0) + 1

    if STYLE == "def":
        def svc(i, c, e):
            return {"ok": True}
    else:
        async def svc(i, c, e):
            return {"ok": True}
    return MachineLogic(actions={"boom": boom, "noop": noop},
                        services={"svc": svc}, strict=True)


async def variant(with_handlers: bool):
    m = create_machine(json.loads(json.dumps(cfg(with_handlers))),
                       logic=logic(), strict_targets=True)
    it = Interpreter(m, clock=SimulatedClock())
    await it.start()
    rec = {"with_handlers": with_handlers, "style": STYLE,
           "after_start": sorted(it.current_state_ids)}
    try:
        await asyncio.wait_for(it.send("GO", wait=True), 25)
    except Exception as exc:
        rec["send_exc"] = "%s: %s" % (type(exc).__name__, str(exc)[:100])
    ticks = []
    for _ in range(10):
        await asyncio.sleep(0.03)
        ticks.append(sorted(it.current_state_ids))
    rec["ticks"] = ticks
    rec["final_cfg"] = sorted(it.current_state_ids)
    rec["status"] = str(getattr(it, "status", "?"))
    try:
        await asyncio.wait_for(it.stop(), 10)
    except asyncio.TimeoutError:
        rec["stop_hung"] = True
    rec["bad"] = ("running" in rec["status"].lower()) and not rec["final_cfg"]
    return rec


async def main():
    out = [await variant(False), await variant(True)]
    print(json.dumps(out, indent=1, default=str))
    return 1 if any(r["bad"] for r in out) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
