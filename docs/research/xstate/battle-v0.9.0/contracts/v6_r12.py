# -*- coding: utf-8 -*-
"""V6: the round-12 (#225/#232/#219) contract shapes on the ORDER PATH, on
B18 (kill switch).  A kill-switch action that spawns a drain worker or hands
out a receipt must behave as EXTERNAL traffic, not as an in-step self-send.

STANDALONE: stdlib + xstate_statemachine only, neutral cwd.
Run with -W error::RuntimeWarning (#232).
"""
from __future__ import annotations
import asyncio, json, os, pathlib, sys, warnings
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cv9 as K  # noqa: E402
from cv9 import Stub  # noqa: E402
os.chdir("<home>")


async def worker_outlives_action():
    """#225: an action spawns a helper task that sends AFTER the action has
    returned.  With the loop idle, the machine must still advance."""
    c = K.cfg("B18")
    landed = asyncio.Event()

    def spawn(interp, ctx, evt, ad):
        async def helper():
            await asyncio.sleep(0.02)          # outlive the action
            await interp.send("RELEASE")        # external traffic
            landed.set()
        asyncio.ensure_future(helper())

    st = Stub(c, act_impl={"record_engagement": spawn},
              guard_vals={"owner_and_elevated": True,
                          "cancel_working_requested": False,
                          "flatten_requested": False})
    m, i, p = await K.new_async(c, st)
    r = await K.send(i, "ENGAGE")
    await K.quiesce(i, 6)
    try:
        await asyncio.wait_for(landed.wait(), 5)
        ok = True
    except asyncio.TimeoutError:
        ok = False
    await K.quiesce(i, 4)
    K.rec("V6.#225.worker_outlives_action_advances",
          ok and K.ids(i) == ["kill_switch.clear"],
          "landed=%s states=%s trips=%r err=%r"
          % (ok, K.ids(i), i.chain_trips, repr(i.error)[:120]))
    await asyncio.wait_for(i.stop(), 5)


async def handout_idiom():
    """#225/#219: the documented hand-out idiom -- the action creates the
    receipt task and does NOT await it -- must be accepted, and the action
    may await afterwards."""
    c = K.cfg("B18")
    box = {}

    def handout(interp, ctx, evt, ad):
        box["fut"] = asyncio.ensure_future(
            interp.send("RELEASE", wait=True))

    st = Stub(c, act_impl={"record_engagement": handout},
              guard_vals={"owner_and_elevated": True,
                          "cancel_working_requested": False,
                          "flatten_requested": False})
    m, i, p = await K.new_async(c, st)
    await K.send(i, "ENGAGE")
    await K.quiesce(i, 6)
    try:
        await asyncio.wait_for(box["fut"], 5)
        ok, note = True, "receipt resolved"
    except Exception as e:
        ok, note = False, repr(e)[:200]
    K.rec("V6.#225.handout_receipt_resolves", ok,
          "%s states=%s" % (note, K.ids(i)))
    await asyncio.wait_for(i.stop(), 5)


async def reentrant_still_refused():
    """#219 (narrowed by #225): the GENUINE in-step await is still refused,
    with ReentrantWaitError -- never a deadlock.

    The action must be a real `async def` registered in MachineLogic, so the
    engine awaits it and the await happens WHILE the action runs.
    """
    c = K.cfg("B18")
    box = {}
    st = Stub(c, guard_vals={"owner_and_elevated": True,
                             "cancel_working_requested": False,
                             "flatten_requested": False})
    logic = st.logic()

    async def bad(interp, ctx, evt, ad):
        try:
            await interp.send("RELEASE", wait=True)
            box["r"] = "NO-REFUSAL"
        except Exception as e:
            box["r"] = type(e).__name__

    bad.__name__ = "record_engagement"
    logic.actions["record_engagement"] = bad
    m = K.create_machine(K.copy.deepcopy(c), logic=logic, strict_config=True,
                         strict_targets=True)
    i = K.Interpreter(m, clock=K.SimulatedClock(),
                      max_queue_size=64,
                      overflow_policy=K.OverflowPolicy.RAISE)
    hooks = K.CvHooks()
    i.use(hooks)
    await i.start()
    await K.quiesce(i, 2)
    try:
        await asyncio.wait_for(K.send(i, "ENGAGE", timeout=6), 8)
    except asyncio.TimeoutError:
        box.setdefault("r", "DEADLOCK")
    await K.quiesce(i, 3)
    K.rec("V6.#219.inflight_await_refused_not_deadlock",
          box.get("r") == "ReentrantWaitError",
          "got=%r states=%s" % (box.get("r"), K.ids(i)))
    await asyncio.wait_for(i.stop(), 5)


async def def_action_dropped_receipt():
    """#232: a `def` action that drops a wait=True receipt must emit a
    RuntimeWarning.  Our contract stubs must never do this -- proved by the
    -W error::RuntimeWarning runs -- but the warning must exist."""
    c = K.cfg("B18")

    def dropper(interp, ctx, evt, ad):
        interp.send("RELEASE", wait=True)   # dropped on the floor

    st = Stub(c, act_impl={"record_engagement": dropper},
              guard_vals={"owner_and_elevated": True,
                          "cancel_working_requested": False,
                          "flatten_requested": False})
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        m, i, p = await K.new_async(c, st)
        await K.send(i, "ENGAGE")
        await K.quiesce(i, 4)
        await asyncio.wait_for(i.stop(), 5)
        import gc
        gc.collect()
        msgs = [str(x.message)[:120] for x in w
                if issubclass(x.category, RuntimeWarning)]
    K.rec("V6.#232.def_dropped_receipt_warns", bool(msgs), "%s" % (msgs[:2],))


async def main():
    await worker_outlives_action()
    await handout_idiom()
    await reentrant_still_refused()
    await def_action_dropped_receipt()
    K.dump("results/v6_r12.json")


asyncio.run(main())
