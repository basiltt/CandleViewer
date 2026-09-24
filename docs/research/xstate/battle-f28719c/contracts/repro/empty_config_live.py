# -*- coding: utf-8 -*-
"""STANDALONE: after a bounded rollback+onDone storm the interpreter is left
with an EMPTY configuration while status == "running".

An empty configuration on a live interpreter means:
  - current_state_ids == set()  -> no state is active
  - every subsequent event is unhandled (nothing can handle it)
  - a snapshot taken here is the torn shape #198 forbids for version>=1

Exit 0 = configuration non-empty (or machine cleanly stopped/errored).
Exit 1 = status is a live/running status but configuration is empty.
"""
from __future__ import annotations
import asyncio, json, os, sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

STYLE = os.environ.get("CV_SVC_STYLE", "async")

CFG = {
    "id": "r6", "actionErrorPolicy": "rollback", "onUnhandled": "defer",
    "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
    "initial": "idle", "context": {},
    "states": {
        "idle": {"on": {"GO": {"target": "#r6.starting"},
                        "PING": {"actions": ["noop"]}}},
        "starting": {"invoke": {"id": "sub", "src": "svc",
                                "onDone": {"target": "#r6.recording"},
                                "onError": {"target": "#r6.err"}},
                     "on": {"PING": {"actions": ["noop"]}}},
        "recording": {"entry": ["boom"], "on": {"PING": {"actions": ["noop"]}}},
        "err": {},
    },
}


def make_logic():
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


async def main():
    m = create_machine(json.loads(json.dumps(CFG)), logic=make_logic(),
                       strict_targets=True)
    it = Interpreter(m, clock=SimulatedClock())
    await it.start()
    out = {"style": STYLE, "after_start": sorted(it.current_state_ids)}
    try:
        await asyncio.wait_for(it.send("GO", wait=True), 25)
    except Exception as exc:
        out["send_exc"] = "%s: %s" % (type(exc).__name__, str(exc)[:120])
    for _ in range(8):
        await asyncio.sleep(0.03)

    cfgids = sorted(it.current_state_ids)
    status = str(getattr(it, "status", "?"))
    out["configuration_after_storm"] = cfgids
    out["status_after_storm"] = status

    # Can the machine still do anything at all?
    try:
        r = await asyncio.wait_for(it.send("PING", wait=True), 10)
        out["ping_receipt"] = repr(r)[:240]
    except Exception as exc:
        out["ping_exc"] = "%s: %s" % (type(exc).__name__, str(exc)[:160])
    out["pings_applied"] = it.context.get("pings", 0)
    out["configuration_after_ping"] = sorted(it.current_state_ids)

    # What does a snapshot of this look like?
    try:
        snap = it.get_snapshot()
        s = json.loads(snap) if isinstance(snap, str) else snap
        out["snapshot_status"] = s.get("status")
        out["snapshot_state_ids"] = s.get("state_ids")
        out["snapshot_configuration"] = s.get("configuration")
    except Exception as exc:
        out["snapshot_exc"] = "%s: %s" % (type(exc).__name__, str(exc)[:160])

    try:
        await asyncio.wait_for(it.stop(), 10)
    except asyncio.TimeoutError:
        out["stop_hung"] = True

    live = status in ("running", "Status.RUNNING") or "running" in status.lower()
    bad = live and not cfgids
    out["VERDICT"] = ("LIVE INTERPRETER WITH EMPTY CONFIGURATION" if bad
                      else "ok")
    print(json.dumps(out, indent=1, default=str))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
