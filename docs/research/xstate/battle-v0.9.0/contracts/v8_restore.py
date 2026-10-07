# -*- coding: utf-8 -*-
"""V8: #227 / #230 / #233 / #226 on the ORDER PATH (B18, strict: true).

  #227  an UNDECLARED type in a restored `scheduled_sends` record must be
        refused on a strict machine, reported via on_invalid_event, and the
        rest of the restore must survive.
  #230  plugins= makes that refusal observable at restore time.
  #233  a `lane: "priority"` record restores AT THE HEAD on the SYNC engine.
  #226  the chain-trip latch survives the round trip and RestoredError is
        what a restored trip carries.

STANDALONE: stdlib + xstate_statemachine only, neutral cwd.
"""
from __future__ import annotations
import asyncio, json, os, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cv9 as K  # noqa: E402
from cv9 import Stub  # noqa: E402
os.chdir("<home>")

GV = {"owner_and_elevated": True, "cancel_working_requested": False,
      "flatten_requested": False}


async def snap_of_b18():
    c = K.cfg("B18")
    st = Stub(c, guard_vals=dict(GV))
    m, i, p = await K.new_async(c, st)
    await K.send(i, "ENGAGE")
    await K.quiesce(i, 3)
    blob = i.get_persisted_snapshot()
    if isinstance(blob, dict):
        blob = json.dumps(blob)
    trips = i.chain_trips
    await asyncio.wait_for(i.stop(), 5)
    return c, blob, trips


async def undeclared_in_restored_lane():
    c, blob, trips = await snap_of_b18()
    raw = json.loads(blob)
    K.rec("V8.#226.chain_trips_in_envelope", "chain_trips" in raw,
          "keys=%s trips=%r" % (sorted(raw)[:12], trips))
    # forge an UNDECLARED type into each lane
    raw.setdefault("scheduled_sends", []).append(
        {"kind": "event", "type": "NOT_A_DECLARED_EVENT", "payload": {},
         "remaining_ms": 10.0, "lane": "priority"})
    forged = json.dumps(raw)
    for eng, mk in (("async", K.Interpreter), ("sync", K.SyncInterpreter)):
        st2 = Stub(c, guard_vals=dict(GV), sync=(eng == "sync"))
        m2 = K.build(c, st2)
        pl = K.CvHooks()
        try:
            j = mk.from_snapshot(forged, m2, clock=K.SimulatedClock(),
                                 minimum_version=3, plugins=[pl])
            built = True
            err = None
        except Exception as e:
            built, err = False, repr(e)[:200]
        if not built:
            K.rec("V8.#227.%s.undeclared_refused_not_fatal" % eng, False, err)
            continue
        if eng == "async":
            await j.start(); await K.quiesce(j, 3)
        else:
            j.start()
        seen = bool(pl.invalid) or bool(getattr(j, "last_error", None))
        K.rec("V8.#227.%s.undeclared_refused_not_fatal" % eng,
              seen and K.ids(j) == ["kill_switch.engaged"],
              "invalid=%s last_error=%r states=%s"
              % (pl.invalid[:2], repr(getattr(j, "last_error", None))[:120],
                 K.ids(j)))
        if eng == "async":
            await asyncio.wait_for(j.stop(), 5)
        else:
            j.stop()


async def priority_lane_sync_restore():
    """#233: a declared priority-lane record restores ahead of the inbox on
    the SYNC engine, and actually drives the machine."""
    c, blob, _ = await snap_of_b18()
    raw = json.loads(blob)
    raw.setdefault("scheduled_sends", []).append(
        {"kind": "event", "type": "RELEASE", "payload": {},
         "remaining_ms": 0.0, "lane": "priority"})
    forged = json.dumps(raw)
    for eng, mk in (("async", K.Interpreter), ("sync", K.SyncInterpreter)):
        st2 = Stub(c, guard_vals=dict(GV), sync=(eng == "sync"))
        m2 = K.build(c, st2)
        pl = K.CvHooks()
        j = mk.from_snapshot(forged, m2, clock=K.SimulatedClock(),
                             minimum_version=3, plugins=[pl])
        if eng == "async":
            await j.start()
            await j.clock.increment(1)
            await K.quiesce(j, 4)
        else:
            j.start()
            #: SimulatedClock.increment() returns a _MustAwait sentinel when
            #: called from inside a running loop (the library warns, rightly).
            #: The sync engine is driven from a thread with no loop.
            await asyncio.to_thread(j.clock.increment, 1)
        K.rec("V8.#233.%s.priority_release_replays" % eng,
              K.ids(j) == ["kill_switch.clear"],
              "states=%s trips=%r" % (K.ids(j), getattr(j, "chain_trips", "?")))
        if eng == "async":
            await asyncio.wait_for(j.stop(), 5)
        else:
            j.stop()


async def main():
    await undeclared_in_restored_lane()
    await priority_lane_sync_restore()
    K.dump("results/v8_restore.json")


asyncio.run(main())
