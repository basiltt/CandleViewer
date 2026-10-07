# -*- coding: utf-8 -*-
"""V1 (v0.9.0 / 91bd979): build B16-B20 under the MANDATORY config and
smoke-start both engines.  #220 now recurses strictConfig into every state,
transition and invoke, so this is a real re-test of the catalogue JSON.

STANDALONE: stdlib + xstate_statemachine only, neutral cwd.
Run with -W error::RuntimeWarning (#232).
"""
from __future__ import annotations
import asyncio, os, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cv9 as K  # noqa: E402
os.chdir("<home>")

BS = ["B16", "B17", "B18", "B19", "B20"]


async def main():
    for b in BS:
        c = K.cfg(b)
        st = K.Stub(c)
        try:
            K.build(c, st)
            K.rec("V1.%s.build_strictConfig" % b, True,
                  "acts=%d guards=%d svcs=%d delays=%d"
                  % (len(st.acts), len(st.guards), len(st.svcs), len(st.delays)))
        except Exception as e:
            K.rec("V1.%s.build_strictConfig" % b, False, repr(e)[:300])
            continue
        # async engine smoke
        try:
            st2 = K.Stub(c)
            m, i, p = await K.new_async(c, st2)
            notes = []
            ok, _ = await K.snap_roundtrip(i, c, lambda: K.Stub(c), "t0", notes)
            K.rec("V1.%s.async_start_snap" % b, ok and i.status == "running",
                  "%s %s | %s" % (K.ids(i), i.status, notes[:3]))
            await asyncio.wait_for(i.stop(), 5)
        except Exception as e:
            K.rec("V1.%s.async_start_snap" % b, False, repr(e)[:300])
        # sync engine smoke + #233 restore
        try:
            st3 = K.Stub(c, sync=True)
            m, j, p = K.new_sync(c, st3)
            notes = []
            ok = K.snap_roundtrip_sync(j, c, lambda: K.Stub(c, sync=True), "s0", notes)
            K.rec("V1.%s.sync_start_snap" % b, ok and j.status == "running",
                  "%s %s | %s" % (K.ids(j), j.status, notes[:3]))
            j.stop()
        except Exception as e:
            K.rec("V1.%s.sync_start_snap" % b, False, repr(e)[:300])
    K.dump("res_v1_build.json")


asyncio.run(main())
