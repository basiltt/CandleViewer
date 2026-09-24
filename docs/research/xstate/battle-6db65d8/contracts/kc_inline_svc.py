# -*- coding: utf-8 -*-
"""LD-INLINE: a PLAIN `def` service is invoked even when the step that
armed it is rolled back, and even when an `always` guard leaves the
invoking state before the invoke should ever have run.

Minimal chart (no catalogue): `armed --GO--> submitting` where
`submitting` has entry `bump` and invoke `submit_child`.

  case A  `always` roll-forward: `submitting.always` returns to `armed`
          unconditionally, so `submit_child` must never run.
  case B  actionErrorPolicy: "rollback": `bump` raises, so the whole step
          is undone and `submit_child` must never run.

Both are run with the service spelled `def` and spelled `async def`.
In an OMS `submit_child` places a real child order on the exchange: an
invoke that "should never have run" is an unwanted live order.
"""
from __future__ import annotations
import asyncio, json, os, sys
os.environ["CV_SVC_STYLE"] = sys.argv[1] if len(sys.argv) > 1 else "async"
STYLE = os.environ["CV_SVC_STYLE"]

from xstate_statemachine import (
    Interpreter, MachineLogic, OverflowPolicy, create_machine)
from xstate_statemachine.clock import SimulatedClock

CALLS = []


def chart(case):
    sub = {"entry": ["bump"],
           "invoke": {"id": "kid", "src": "submit_child",
                      "onDone": {"target": "#m.armed"},
                      "onError": {"target": "#m.armed"}}}
    if case == "A":
        sub["always"] = [{"target": "#m.armed", "guard": "roll_forward"}]
    return {"id": "m", "initial": "armed",
            "actionErrorPolicy": "rollback", "onUnhandled": "defer",
            "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
            "context": {"n": 0},
            "states": {"armed": {"on": {"GO": {"target": "#m.submitting"}}},
                       "submitting": sub}}


def logic(case):
    def bump(i, ctx, e, ad):
        if case == "B":
            raise RuntimeError("entry action failed")
        ctx["n"] = ctx.get("n", 0) + 1

    def svc_sync(i, ctx, e):
        CALLS.append("submit_child")
        return {"ok": True}

    async def svc_async(i, ctx, e):
        CALLS.append("submit_child")
        return {"ok": True}

    return MachineLogic(
        actions={"bump": bump},
        guards={"roll_forward": lambda ctx, e: True},
        services={"submit_child": svc_sync if STYLE == "def" else svc_async},
        strict=True)


async def run(case):
    CALLS.clear()
    m = create_machine(chart(case), logic=logic(case))
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=64,
                    overflow_policy=OverflowPolicy.RAISE)
    await i.start()
    await asyncio.sleep(0.05)
    try:
        await asyncio.wait_for(i.send("GO", wait=True), 5)
    except Exception as e:
        print("  send raised:", repr(e))
    for _ in range(6):
        await asyncio.sleep(0.03)
    out = {"case": case, "style": STYLE, "states": sorted(i.current_state_ids),
           "context": dict(i.context), "service_calls": list(CALLS)}
    await asyncio.wait_for(i.stop(), 5)
    return out


async def main():
    rows = []
    for case in ("A", "B"):
        r = await run(case)
        rows.append(r)
        want = "never invoked"
        ok = r["service_calls"] == []
        print(("PASS " if ok else "FAIL ")
              + "LD-INLINE/case %s [%s] submit_child %s" % (case, STYLE, want)
              + "  | " + json.dumps(r), flush=True)
    import pathlib
    pathlib.Path("kc_inline_svc.%s.json" % STYLE).write_text(
        json.dumps(rows, indent=1), encoding="utf-8")
    sys.exit(0 if all(r["service_calls"] == [] for r in rows) else 1)

asyncio.run(main())
