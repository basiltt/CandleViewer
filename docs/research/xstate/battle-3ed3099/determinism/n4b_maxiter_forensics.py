"""N4b -- forensics on N4/C1a: 8 asyncio producers x 100 sends each against a
machine with `maxIterations: 10`, only 501/800 observed processed with ZERO
errors raised.

Before calling that a loss, rule out the harness: drain harder, and measure
where the events went -- still queued? dropped with a reason? counted as
handled? Per-run repeat to see if the number is stable.

Instruments:
  * on_event_dropped / on_unhandled_event / on_transition_failed hooks
  * inbox depth at the end
  * a long drain (20k loop turns) and a wall-clock drain
  * maxIterations present vs absent (the control)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)

CFG = {
    "id": "cnt",
    "initial": "up",
    "context": {"n": 0},
    "states": {"up": {"on": {"TICK": {"actions": ["bump"]}}}},
}


class Spy(PluginBase):
    def __init__(self):
        self.dropped, self.unhandled, self.failed, self.errors = [], [], [], []

    def on_event_dropped(self, interp, event, reason=None, **kw):
        self.dropped.append((getattr(event, "type", "?"), reason))

    def on_unhandled_event(self, interp, event, **kw):
        self.unhandled.append(getattr(event, "type", "?"))

    def on_transition_failed(self, interp, event=None, error=None, **kw):
        self.failed.append(repr(error)[:100])

    def on_plugin_error(self, interp, plugin, hook, error, **kw):
        self.errors.append(f"{hook}:{type(error).__name__}")


def mk(max_iterations):
    def bump(i, c, e, a):
        c["n"] += 1

    cfg = dict(CFG)
    if max_iterations is not None:
        cfg = {**CFG, "maxIterations": max_iterations}
    return create_machine(cfg, logic=MachineLogic(actions={"bump": bump}))


async def run(max_iterations, n_producers=8, per=100, drain_turns=20000):
    spy = Spy()
    i = Interpreter(mk(max_iterations))
    i.use(spy)
    await i.start()
    errs = []

    async def prod(p):
        for k in range(per):
            try:
                await i.send("TICK", p=p, k=k)
            except Exception as e:  # noqa: BLE001
                errs.append(f"{type(e).__name__}: {e}"[:120])

    await asyncio.gather(*(prod(p) for p in range(n_producers)))
    after_gather = i.context["n"]
    for _ in range(drain_turns):
        await asyncio.sleep(0)
    after_turns = i.context["n"]
    # wall-clock drain too, in case the loop needs real time
    for _ in range(50):
        await asyncio.sleep(0.01)
    after_sleep = i.context["n"]
    depth = None
    try:
        depth = i._event_queue.qsize()
    except Exception:  # noqa: BLE001
        pass
    out = {
        "maxIterations": max_iterations,
        "expected": n_producers * per,
        "n_after_gather": after_gather,
        "n_after_20k_turns": after_turns,
        "n_after_wallclock_drain": after_sleep,
        "inbox_depth_at_end": depth,
        "send_exceptions": len(errs),
        "send_exception_examples": errs[:3],
        "dropped_hook": len(spy.dropped),
        "dropped_examples": spy.dropped[:5],
        "unhandled_hook": len(spy.unhandled),
        "transition_failed": len(spy.failed),
        "transition_failed_examples": spy.failed[:3],
        "plugin_errors": spy.errors[:3],
        "status": i.status,
        "last_error": repr(getattr(i, "last_error", None))[:160],
    }
    await i.stop()
    out["n_after_stop"] = i.context["n"]
    out["LOST"] = n_producers * per - out["n_after_stop"]
    return out


async def main():
    res = {}
    for label, mi in (
        ("maxiter_10", 10),
        ("maxiter_10_repeat", 10),
        ("maxiter_100", 100),
        ("control_no_maxiter", None),
    ):
        res[label] = await run(mi)
        print(f"\n== {label} ==")
        for k, v in res[label].items():
            print(f"   {k:28s}: {v}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "n4b_maxiter_forensics.json"), "w") as f:
        json.dump(res, f, indent=2, default=str)
    print("\nwrote out/n4b_maxiter_forensics.json")


if __name__ == "__main__":
    asyncio.run(main())
