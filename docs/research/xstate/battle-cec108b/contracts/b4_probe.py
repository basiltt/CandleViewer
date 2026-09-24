# -*- coding: utf-8 -*-
"""B4 INV-B4-d isolation: is the lost LEG_B_FILL a library or contract defect?"""
from __future__ import annotations
import asyncio, json, copy
from xstate_statemachine import Interpreter, OverflowPolicy, SimulatedClock, create_machine
import charness as H

BASE = json.load(open("B4.machine.json", encoding="utf-8"))
GV = {"position_overshoots": False, "other_leg_terminal": True,
      "partial_settle_remaining": False, "error_is_order_gone": True,
      "settle_retries_left": True, "cancel_on_position_flat": True}


def ai(st):
    def c(key):
        def f(i, ctx, e, a):
            ctx[key] = int(ctx.get(key) or 0) + 1
        return f
    return {"record_fill_a": c("filled_a"), "record_fill_b": c("filled_b")}


async def run(cfg, label):
    gate = asyncio.Event()

    async def hang(i, ctx, e):
        await gate.wait()
        return {}

    st = H.Stub(cfg, guard_vals=GV, act_impl=None,
                svc={"submit_both_legs": {"a": 1}, "settle_other_leg": {},
                     "cancel_all_children": {}, "reconcile_children": {},
                     "reduce_only_market_excess": {}})
    st.act_impl = ai(st)
    logic = st.logic()
    logic.services["settle_other_leg"] = hang
    m = create_machine(copy.deepcopy(cfg), logic=logic)
    i = Interpreter(m, clock=SimulatedClock(), overflow_policy=OverflowPolicy.RAISE)
    p = H.TraceP()
    i.use(p)
    await i.start()
    await H.quiesce(i, 3)
    await i.send("LEG_A_FILL")
    await H.quiesce(i, 3)
    assert "oco.settling_b" in H.ids(i), H.ids(i)
    r = await i.send("LEG_B_FILL", wait=True)
    await H.quiesce(i, 2)
    held = i.deferred_count
    gate.set()
    await H.quiesce(i, 8)
    print("%-10s ids=%s deferred_at_send=%d deferred_now=%d record_fill_b=%d "
          "unhandled=%s dropped=%s receipt.deferred=%s"
          % (label, H.ids(i), held, i.deferred_count,
             st.trace.count("record_fill_b"), p.unhandled, p.dropped,
             getattr(r, "deferred", None)))
    await i.stop()


async def main():
    await run(BASE, "as-written")
    # Patched contract: `completing` declares LEG_B_FILL (self-transition,
    # records the fill) so the replayed deferred event has a home.
    fixed = copy.deepcopy(BASE)
    fixed["states"]["completing"].setdefault("on", {})["LEG_B_FILL"] = {
        "actions": ["record_fill_b"]}
    fixed["states"]["completed"].setdefault("on", {})["LEG_B_FILL"] = {
        "actions": ["record_fill_b"]}
    await run(fixed, "patched")

asyncio.run(main())
