# -*- coding: utf-8 -*-
"""V4: v0.9.0 safety-net mandates against the contract charts.

  #232  a `def` action that DROPS a `wait=True` receipt must warn; the
        supported hand-out shapes must stay silent (this is why every
        driver runs under `-W error::RuntimeWarning`).
  #233  the sync engine honours the priority lane on restore (B18).
  #226  a real chain trip is latched, survives a snapshot, stays monotonic.
  bounded RAISE inbox + SimulatedClock timers.

STANDALONE: stdlib + xstate_statemachine only, neutral cwd.
"""
from __future__ import annotations
import asyncio, json, os, pathlib, sys, warnings

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cv9 as K  # noqa: E402
os.chdir("<home>")

from xstate_statemachine import Interpreter, OverflowPolicy  # noqa: E402
from xstate_statemachine.clock import SimulatedClock  # noqa: E402


async def w232_dropped_receipt():
    """A `def` action that calls send(wait=True) and throws the result away
    must produce a RuntimeWarning (#232)."""
    c = K.cfg("B1")

    def dropper(interp, ctx, evt, ad):
        interp.send("SEND", wait=True)   # receipt dropped on the floor

    st = K.Stub(c, guard_vals={"passes_all_gates": True},
                act_impl={"stamp_validated": dropper})
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        m, i, p = await K.new_async(c, st)
        await K.send(i, "VALIDATE")
        await K.quiesce(i, 4)
        await i.stop()
        del st
        import gc; gc.collect()
        await K.quiesce(i, 1)
        msgs = [str(x.message) for x in w if issubclass(x.category, RuntimeWarning)]
    K.rec("V4.232.dropped_receipt_warns", bool(msgs),
          "RuntimeWarnings=%r" % (msgs[:2],))


async def w232_handout_silent():
    """The supported hand-out shape must NOT warn."""
    c = K.cfg("B1")
    keep = {}

    def handout(interp, ctx, evt, ad):
        keep["fut"] = asyncio.ensure_future(interp.send("SEND", wait=True))

    st = K.Stub(c, guard_vals={"passes_all_gates": True},
                act_impl={"stamp_validated": handout})
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        m, i, p = await K.new_async(c, st)
        await K.send(i, "VALIDATE")
        await K.quiesce(i, 4)
        if keep.get("fut"):
            try:
                await asyncio.wait_for(keep["fut"], 3)
            except Exception:
                pass
        await i.stop()
        import gc; gc.collect()
        msgs = [str(x.message) for x in w if issubclass(x.category, RuntimeWarning)]
    K.rec("V4.232.handout_silent", not msgs, "RuntimeWarnings=%r" % (msgs[:2],))


async def b18_priority_restore():
    """#233: a `lane: priority` record restores ahead of the inbox on the
    SYNC engine too. Asserted as observable parity of the landing state."""
    c = K.cfg("B18")
    st = K.Stub(c, guard_vals={"owner_and_elevated": True})
    m, i, p = await K.new_async(c, st)
    await K.send(i, "ENGAGE", cancel_working=True, flatten=True)
    await K.quiesce(i, 3)
    blob = i.get_persisted_snapshot()
    if isinstance(blob, dict):
        blob = json.dumps(blob)
    raw = json.loads(blob)
    lanes = [r.get("lane") for r in (raw.get("pending_events") or [])]
    async_states = K.ids(i)
    await i.stop()
    # sync: restore the SAME blob into a SyncInterpreter
    from xstate_statemachine import SyncInterpreter
    p2 = K.CvHooks()
    j = SyncInterpreter.from_snapshot(
        blob, K.build(c, K.Stub(c, guard_vals={"owner_and_elevated": True},
                                sync=True)),
        clock=SimulatedClock(), minimum_version=3, plugins=[p2])
    j.start()
    sync_states = K.ids(j)
    K.rec("V4.233.sync_restore_matches_async", sync_states == async_states,
          "async=%s sync=%s lanes=%r" % (async_states, sync_states, lanes))
    K.rec("V4.233.sync_restore_chain_clean",
          getattr(j, "chain_trips", -1) == 0,
          "chain_trips=%r" % getattr(j, "chain_trips", None))
    j.stop()


async def bounded_inbox():
    """OverflowPolicy.RAISE on the order path: a burst beyond max_queue_size
    is refused loudly, never silently dropped."""
    c = K.cfg("B1")
    st = K.Stub(c, guard_vals={"passes_all_gates": True})
    m = K.build(c, st)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=4,
                    overflow_policy=OverflowPolicy.RAISE)
    p = K.CvHooks()
    i.use(p)
    await i.start()
    refused, sent = 0, 0
    for n in range(40):
        try:
            i.send("EXEC", exec_id="e%d" % n, wait=False)
            sent += 1
        except Exception:
            refused += 1
    await K.quiesce(i, 3)
    K.rec("V4.inbox.raise_is_loud_not_silent",
          refused > 0 or not p.dropped,
          "sent=%d refused=%d dropped=%r" % (sent, refused, p.dropped[:2]))
    K.rec("V4.inbox.survives_burst", i.status == "running",
          "status=%r states=%s" % (i.status, K.ids(i)))
    await i.stop()


async def main():
    await w232_dropped_receipt()
    await w232_handout_silent()
    await b18_priority_restore()
    await bounded_inbox()
    K.dump("v4_mandates.json")


asyncio.run(main())
