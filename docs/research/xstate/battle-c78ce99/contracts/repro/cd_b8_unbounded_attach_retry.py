# -*- coding: utf-8 -*-
"""CD-B8 @ c78ce99 -- OUR-CONTRACT defect. STANDALONE (stdlib + library).

B8 `position_protection.sl.attaching` retries WITHOUT A BOUND:

    attaching --invoke attach_native_sl
              --onError[guard attach_attempts_left] --> attaching (reenter)
              --onError (fallback)                  --> naked

`attach_attempts_left` is the only thing standing between a rejecting
venue and an infinite attach loop, and `bump_attach_attempts` (the entry
action that feeds it) is in the chart -- but NOTHING in the chart ever
makes the guard false: there is no cap in `context`, and the catalogue
never states one.  Held true (the venue keeps rejecting), the cycle is
pure self-generated work, so the ENGINE stops it at `maxIterations` --
correctly, and observably (#207).

The OMS consequence is the point:

  * the machine parks in `sl.attaching` with a STRANDED invoke, i.e. a
    live position with NO stop-loss attached and nothing in flight;
  * `sl.naked` -- the state that carries `raise_critical_alert` and
    `emit_naked_metric` -- is NEVER reached, so **zero alerts fire**;
  * the only signal is `RunawayChainError` / `on_invocation_stranded`,
    which is an engine-health signal, not a position-risk one.

Compare B6 (`failures_exhausted`) and B10 (`delivery_attempts_left`
against `max_delivery_attempts` in context): both bound their retries in
the chart.  B8's `sl` region does not.  FIX IS OURS: give
`attach_attempts_left` a real cap (`attach_attempts < max_attach_attempts`)
so the chart, not `maxIterations`, decides when to fall through to
`naked` and alert.

Exit 1 = reproduced.
"""
from __future__ import annotations
import asyncio, json
from xstate_statemachine import (
    Interpreter, MachineLogic, OverflowPolicy, create_machine)
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

# Faithful excerpt of our B8 `sl` region (no catalogue file dependency).
CFG = {
    "id": "pp", "actionErrorPolicy": "fail", "onUnhandled": "defer",
    "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
    "maxIterations": 25, "initial": "flat",
    "context": {"attach_attempts": 0, "alerts": 0},
    "states": {
        "flat": {"on": {"POSITION_OPENED": "#pp.attaching"}},
        "attaching": {
            "entry": ["bump_attach_attempts"],
            "invoke": {"id": "att", "src": "attach_native_sl",
                       "onDone": {"target": "#pp.verifying"},
                       "onError": [
                           {"target": "#pp.attaching", "reenter": True,
                            "guard": "attach_attempts_left"},
                           {"target": "#pp.naked"}]}},
        "verifying": {},
        "naked": {"entry": ["raise_critical_alert"]},
    },
}


class Hooks(PluginBase):
    def __init__(self):
        self.stranded = []

    def on_invocation_stranded(self, i, state_id, invoke_id, error):
        self.stranded.append((state_id, invoke_id))


async def main() -> int:
    n = {"attempts": 0, "alerts": 0}

    def bump(i, c, e, a):
        n["attempts"] += 1
        c["attach_attempts"] = n["attempts"]

    def alert(i, c, e, a):
        n["alerts"] += 1

    async def attach(i, c, e):
        raise RuntimeError("venue rejected native SL")

    m = create_machine(json.loads(json.dumps(CFG)), strict_config=True,
                       logic=MachineLogic(
                           actions={"bump_attach_attempts": bump,
                                    "raise_critical_alert": alert},
                           # 🐞 nothing in the chart ever makes this false
                           guards={"attach_attempts_left": lambda c, e: True},
                           services={"attach_native_sl": attach},
                           strict=True))
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=512,
                    overflow_policy=OverflowPolicy.RAISE)
    h = Hooks()
    i.use(h)
    await i.start()
    await i.send("POSITION_OPENED")

    laps, prev = [], -1                     # poll to CONVERGENCE
    for _ in range(15):
        for _ in range(6):
            await asyncio.sleep(0.02)
        laps.append(n["attempts"])
        if n["attempts"] == prev:
            break
        prev = n["attempts"]

    out = {"attach_attempts": n["attempts"], "alerts_fired": n["alerts"],
           "state": sorted(i.current_state_ids),
           "stranded": h.stranded,
           "dormant": bool(getattr(i, "has_dormant_invocations", False)),
           "last_error": repr(i.last_error)[:110], "laps": laps[-3:]}
    await i.stop()
    print(json.dumps(out, indent=1))

    hit = (out["state"] == ["pp.attaching"] and out["alerts_fired"] == 0
           and bool(out["stranded"]) and out["dormant"])
    print("\nCD-B8 REPRODUCED: position parks UNPROTECTED in 'attaching' "
          "after %d attempts, %d risk alerts fired, invoke stranded"
          % (out["attach_attempts"], out["alerts_fired"]) if hit
          else "\nCD-B8 did NOT reproduce")
    return 1 if hit else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
