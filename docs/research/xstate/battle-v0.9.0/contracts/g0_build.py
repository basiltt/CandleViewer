# -*- coding: utf-8 -*-
"""G0: build probe for B11-B15 on v0.9.0/main. strictConfig + full mandatory
config; also asserts from_snapshot(plugins=) exists (#230).
STANDALONE: stdlib + xstate_statemachine only."""
from __future__ import annotations
import asyncio, inspect, json, os, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cv9 as K  # noqa: E402
os.chdir("<home>")
from xstate_statemachine import Interpreter, SyncInterpreter  # noqa: E402

GROUP = ["B11", "B12", "B13", "B14", "B15"]


async def main():
    for b in GROUP:
        try:
            c = K.cfg(b)
            st = K.Stub(c)
            m = K.build(c, st)
            K.rec("G0.%s.build" % b, True,
                  "acts=%d guards=%d svcs=%d delays=%d evts=%d" % (
                      len(st.acts), len(st.guards), len(st.svcs),
                      len(st.delays), len(st.events)))
        except Exception as e:
            K.rec("G0.%s.build" % b, False, repr(e)[:300])
            continue
        try:
            m2, i, p = await K.new_async(c, K.Stub(c))
            K.rec("G0.%s.start" % b, i.status == "running",
                  "states=%s status=%s" % (K.ids(i), i.status))
            await asyncio.wait_for(i.stop(), 5)
        except Exception as e:
            K.rec("G0.%s.start" % b, False, repr(e)[:300])
    sig = inspect.signature(Interpreter.from_snapshot)
    K.rec("G0.api.from_snapshot_plugins", "plugins" in sig.parameters,
          str(sig))
    ssig = inspect.signature(SyncInterpreter.from_snapshot)
    K.rec("G0.api.sync_from_snapshot_plugins", "plugins" in ssig.parameters,
          str(ssig))
    K.dump("res_g0_build.json")

asyncio.run(main())
