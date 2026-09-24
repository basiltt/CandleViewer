# -*- coding: utf-8 -*-
"""V0: every contract chart B1-B5 builds on v0.9.0 under the MANDATORY
round-12 config, starts, quiesces, and round-trips a v3 snapshot with
`from_snapshot(plugins=...)` (#230) and chain_trips == 0 (#226).

STANDALONE: stdlib + xstate_statemachine only, neutral cwd.
Run twice: CV_SVC_STYLE=async then CV_SVC_STYLE=def.
"""
from __future__ import annotations
import asyncio, os, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cv9 as K  # noqa: E402
os.chdir("C:/Users/basil")

BIDS = ["B1", "B2", "B3", "B4", "B5"]


async def main():
    for b in BIDS:
        try:
            c = K.cfg(b)
        except Exception as e:
            K.rec("V0.%s.load" % b, False, repr(e)[:200]); continue
        st = K.Stub(c)
        try:
            m = K.build(c, st)
            K.rec("V0.%s.build" % b, True,
                  "acts=%d guards=%d svcs=%d delays=%d"
                  % (len(st.acts), len(st.guards), len(st.svcs), len(st.delays)))
        except Exception as e:
            K.rec("V0.%s.build" % b, False, repr(e)[:250]); continue
        # start + quiesce + snapshot round-trip at t0
        try:
            r = await K.drive(c, K.Stub(c), [], snapshots=True)
        except Exception as e:
            K.rec("V0.%s.start" % b, False, repr(e)[:250]); continue
        K.rec("V0.%s.start" % b, r["status"] == "running" and bool(r["states"]),
              "states=%s status=%s" % (r["states"], r["status"]))
        K.rec("V0.%s.snapshot_v3_plugins" % b, r["snapshot_ok"],
              "; ".join(r["notes"])[:300])
        K.rec("V0.%s.chain_trips_zero" % b, r["chain_trips"] == 0,
              "chain_trips=%r lce=%s" % (r["chain_trips"], r["last_chain_error"]))
        # sync engine parity: build + start + restore
        stx = K.Stub(c, sync=True)
        try:
            m2, i2, p2 = K.new_sync(c, stx)
            notes = []
            ok = K.snap_roundtrip_sync(i2, c, lambda: K.Stub(c, sync=True),
                                       "s0", notes)
            K.rec("V0.%s.sync_start_restore" % b, ok and i2.status == "running",
                  "states=%s %s" % (K.ids(i2), "; ".join(notes)[:250]))
            i2.stop()
        except Exception as e:
            K.rec("V0.%s.sync_start_restore" % b, False, repr(e)[:250])
    K.dump("v0_build.json")


asyncio.run(main())
