# -*- coding: utf-8 -*-
"""STANDALONE (#203): only an engine-minted AfterEvent drives an `after`.

Our order path models deadlines as external events, so B1-B5 carry no
`after` blocks -- but the wrapper's timeout supervisor is tempted to fire
one by hand.  This proves a hand-built AfterEvent no longer short-circuits
a 60 s timer, while the SimulatedClock still drives the genuine one.
CV=async|def.  stdlib + xstate_statemachine only.
"""
import asyncio, os, sys
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

STYLE = os.environ.get("CV", "async")

CFG = {
    "id": "sub", "initial": "waiting",
    "actionErrorPolicy": "rollback", "onUnhandled": "defer",
    "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
    "context": {},
    "states": {
        "waiting": {"after": {"60000": {"target": "#sub.timed_out"}}},
        "timed_out": {"type": "final"},
    },
}


async def main():
    i = Interpreter(create_machine(CFG, logic=MachineLogic(strict=True),
                                   strict_targets=True),
                    clock=SimulatedClock())
    await i.start()
    await asyncio.sleep(0.15)
    start = sorted(i.current_state_ids)

    # 1. forged: hand-build the event class the engine uses.
    forged_fired = None
    try:
        from xstate_statemachine.events import AfterEvent
        ev = AfterEvent(type="after.60000.sub.waiting", payload={},
                        delay_ms=60000, owner_id="sub.waiting")
    except Exception:
        try:
            from xstate_statemachine.events import AfterEvent
            ev = AfterEvent("after.60000.sub.waiting", {})
        except Exception as e:
            ev = None
            forged_fired = "could-not-build:%r" % (e,)
    if ev is not None:
        try:
            await asyncio.wait_for(i.send(ev, wait=True), 5)
        except Exception as e:
            forged_fired = "send-raised:%s" % type(e).__name__
        await asyncio.sleep(0.3)
        forged_fired = forged_fired or ("sub.timed_out"
                                        in i.current_state_ids)
    after_forge = sorted(i.current_state_ids)

    # 2. genuine: advance the simulated clock past the delay.
    await i.clock.increment(61000)
    await asyncio.sleep(0.3)
    after_clock = sorted(i.current_state_ids)

    print("style=%s start=%s" % (STYLE, start))
    print("  forged AfterEvent -> %s (fired=%s)" % (after_forge, forged_fired))
    print("  clock +61s        -> %s" % (after_clock,))
    bad = []
    if after_forge != ["sub.waiting"]:
        bad.append("forged AfterEvent drove the transition")
    if after_clock != ["sub.timed_out"]:
        bad.append("genuine timer did not fire: %s" % (after_clock,))
    print("  VERDICT=%s" % ("OK" if not bad else "UNSAFE:" + "; ".join(bad)))
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass
    sys.exit(1 if bad else 0)


asyncio.run(main())
